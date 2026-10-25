import importlib.util
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from dubdash.performance import distribution
from benchmark import commands, main, SCENARIOS


def test_distribution_interpolation_and_empty():
    assert distribution([])['mean'] is None
    result = distribution([100, 0, 50])
    assert result == dict(count=3, mean=50, p50=50, p95=95, p99=99)
    assert distribution([4])['p99'] == 4
    for invalid in ([math.nan], [math.inf], [-1]):
        with pytest.raises(ValueError):
            distribution(invalid)


def test_scenarios_use_new_database_and_sensor_only_playback(tmp_path):
    for scenario, (pipeline, detect) in SCENARIOS.items():
        jobs, play = commands(scenario, '/bag', tmp_path/'run', .5, 'http://127.0.0.1:8090/')
        assert f'pipeline:={pipeline}' in jobs[0]
        assert f'database_path:={tmp_path}/run/map.db' in jobs[0]
        assert len(jobs) == 1+int(detect)
        assert '--start-paused' not in play
        assert '/cmd_vel' not in play
        assert '/vo' not in play
        assert play[play.index('--rate')+1] == '0.5'


def test_existing_output_rejected_before_ros_import(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['benchmark', 'full', '--output', str(tmp_path)])
    with pytest.raises(SystemExit):
        main()


def test_dry_run_without_ros_or_dataset(tmp_path, monkeypatch, capsys):
    target = tmp_path/'new'
    monkeypatch.setattr(sys, 'argv', ['benchmark', 'vo', '--output', str(target), '--dry-run'])
    main()
    assert json.loads(capsys.readouterr().out)['jobs']
    assert not target.exists()


def test_invalid_playback_rate(tmp_path):
    with pytest.raises(ValueError):
        commands('full', '/bag', tmp_path, float('nan'), 'http://localhost/')


def test_yolo_decode_person_filter_and_letterbox(monkeypatch):
    import numpy as np
    # OpenCV is not installed in the sandbox; mock NMS only, exercise real filtering,
    # coordinate mapping, clipping and class selection with synthetic predictions.
    monkeypatch.setitem(sys.modules, 'cv2', SimpleNamespace(dnn=SimpleNamespace(
        NMSBoxes=lambda boxes, scores, conf, iou: [[i] for i in range(len(boxes))])))
    spec = importlib.util.spec_from_file_location('trt_worker', Path(__file__).parents[1]/'scripts/trt_worker.py')
    worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
    prediction = np.zeros((1,84,3), dtype=np.float32)
    prediction[0,:4,:] = np.array([[100,100,100], [150,150,150], [100,100,100], [100,100,100]])
    prediction[0,4,:] = [.9,.2,.8]
    prediction[0,5,2] = .95
    result = worker.decode_people(prediction, .5, (0,50), (400,400,3))
    assert len(result) == 1
    assert result[0]['xyxy'] == [100.,100.,300.,300.]
    assert result[0]['label'] == 'person'
    assert worker.decode_people(np.zeros((1,84,2)), 1, (0,0), (100,100,3)) == []
    with pytest.raises(ValueError):
        worker.decode_people(np.zeros((1,6,10)), 1, (0,0), (100,100,3))


def test_remote_detector_needs_no_ultralytics_and_records_timing(monkeypatch):
    """Run the actual bridge callback with fake ROS messages and HTTP result."""
    import io
    import types
    def message():
        return SimpleNamespace(header=None, detections=[], results=[], data=None,
                               bbox=SimpleNamespace(center=SimpleNamespace(x=0,y=0),size_x=0,size_y=0),
                               hypothesis=SimpleNamespace(class_id='',score=0.))
    modules = {
        'rclpy': {}, 'rclpy.node': {'Node': object},
        'rclpy.qos': {'QoSProfile': object, 'ReliabilityPolicy': object, 'HistoryPolicy': object},
        'sensor_msgs.msg': {'Image': object}, 'std_msgs.msg': {'String': lambda **kw: SimpleNamespace(**kw)},
        'vision_msgs.msg': {name: message for name in ('Detection2DArray','Detection2D','ObjectHypothesisWithPose')},
        'cv_bridge': {'CvBridge': object},
        'cv2': {'imencode': lambda *a: (True, SimpleNamespace(tobytes=lambda: b'jpeg')),
                'rectangle': lambda *a: None, 'putText': lambda *a: None, 'FONT_HERSHEY_SIMPLEX': 0},
    }
    for name, attributes in modules.items():
        module = types.ModuleType(name)
        vars(module).update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location('detector_under_test', Path(__file__).parents[1]/'src/dubdash/dubdash/person_detector.py')
    detector = importlib.util.module_from_spec(spec); spec.loader.exec_module(detector)
    response = dict(boxes=[dict(xyxy=[10.,20.,30.,40.], label='person',score=.9)],
                    inference_ms=7., worker_ms=12.)
    requests = []
    def urlopen(request, timeout):
        requests.append(request)
        return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(detector, 'urlopen', urlopen)
    node = detector.PersonDetector.__new__(detector.PersonDetector)
    node.endpoint, node.confidence, node.detect_all = 'http://127.0.0.1:8090/', .5, False
    node.processed, node.first_started, node.warmup_frames = 0, None, 1
    node.metrics_file = io.StringIO()
    node.bridge = SimpleNamespace(imgmsg_to_cv2=lambda *a, **kw: object(),
                                  cv2_to_imgmsg=lambda *a, **kw: message())
    published = {}
    for name in ('image_publisher','publisher','metrics_publisher'):
        published[name] = []
        setattr(node, name, SimpleNamespace(publish=published[name].append))
    header = SimpleNamespace(stamp=SimpleNamespace(sec=123,nanosec=456),frame_id='camera')
    node.detect(SimpleNamespace(header=header))
    node.detect(SimpleNamespace(header=header))
    rows = [json.loads(line) for line in node.metrics_file.getvalue().splitlines()]
    assert [row['warmup'] for row in rows] == [True, False]
    assert rows[-1]['stamp_ns'] == 123000000456
    assert rows[-1]['inference_ms'] == 7
    assert rows[-1]['worker_ms'] == 12
    assert rows[-1]['detection_fps'] > 0
    assert len(published['publisher'][-1].detections) == 1
    assert published['image_publisher'][-1].header is header
    assert requests[0].data == b'jpeg'


def test_engine_predict_synchronizes_before_and_after_enqueue(monkeypatch):
    import numpy as np
    spec = importlib.util.spec_from_file_location('trt_worker_timing', Path(__file__).parents[1]/'scripts/trt_worker.py')
    worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
    monkeypatch.setitem(sys.modules, 'cv2', SimpleNamespace(
        resize=lambda frame, shape: frame,
        copyMakeBorder=lambda frame, *a, **kw: frame, BORDER_CONSTANT=0))
    calls = []
    def copy(dst, src, size, kind):
        calls.append('h2d' if kind == 1 else 'd2h'); return 0
    def sync(stream):
        calls.append('sync'); return 0
    def execute(stream):
        calls.append('execute'); return True
    engine = worker.Engine.__new__(worker.Engine)
    engine.width = engine.height = 2
    engine.input, engine.output = 'input', 'output'
    engine.arrays = {'input': np.zeros((1,3,2,2), dtype=np.float32),
                     'output': np.zeros((1,84,1), dtype=np.float32)}
    engine.pointers = {'input': 1, 'output': 2}
    engine.stream = SimpleNamespace(value=3)
    engine.cuda = SimpleNamespace(cudaMemcpy=copy, cudaStreamSynchronize=sync)
    engine.context = SimpleNamespace(execute_async_v3=execute)
    ticks = iter([0., .01, .017, .025])
    monkeypatch.setattr(worker.time, 'perf_counter', lambda: next(ticks))
    result = engine.predict(np.zeros((2,2,3), dtype=np.uint8))
    assert calls == ['h2d','sync','execute','sync','d2h']
    assert result['inference_ms'] == pytest.approx(7.)
    assert result['worker_ms'] == pytest.approx(25.)
    assert result['boxes'] == []

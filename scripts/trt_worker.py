#!/usr/bin/env python3
"""Local HTTP TensorRT 10.16 worker: static YOLOv8 COCO ONNX, no embedded NMS.

Only raw TensorRT plans with one NCHW input and one [1,84,N] output are accepted.
Ultralytics metadata-prefixed .engine files are deliberately not supported.
"""
import argparse
import ctypes as C
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import time


def decode_people(prediction, scale, padding, original_shape, confidence=.5):
    import numpy as np
    import cv2
    if prediction.ndim != 3 or prediction.shape[:2] != (1, 84):
        raise ValueError('Expected YOLOv8 COCO output [1,84,N], without NMS')
    rows = prediction[0].T
    # Class zero is person; require it to be the winning class as well.
    rows = rows[(rows[:, 4] >= confidence) & (rows[:, 4:].argmax(axis=1) == 0)]
    if len(rows) == 0:
        return []
    boxes = rows[:, :4].astype(float).copy()
    boxes[:, :2] -= boxes[:, 2:] / 2
    boxes[:, 0] = (boxes[:, 0] - padding[0]) / scale
    boxes[:, 1] = (boxes[:, 1] - padding[1]) / scale
    boxes[:, 2:] /= scale
    scores = rows[:, 4].astype(float)
    indices = np.asarray(cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), confidence, .45)).reshape(-1)
    height, width = original_shape[:2]
    result = []
    for i in indices:
        x, y, w, h = boxes[i]
        x1, y1 = max(0., x), max(0., y)
        x2, y2 = min(float(width), x+w), min(float(height), y+h)
        if x2 > x1 and y2 > y1:
            result.append(dict(xyxy=[x1, y1, x2, y2], score=float(scores[i]), label='person'))
    return result


class Engine:
    def __init__(self, path):
        import tensorrt as trt
        import numpy as np
        if not trt.__version__.startswith('10.16.'):
            raise RuntimeError(f'Expected TensorRT 10.16, got {trt.__version__}')
        self.cuda = C.CDLL('libcudart.so.13')
        self.cuda.cudaMalloc.argtypes = [C.POINTER(C.c_void_p), C.c_size_t]
        self.cuda.cudaFree.argtypes = [C.c_void_p]
        self.cuda.cudaMemcpy.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_int]
        self.cuda.cudaStreamCreate.argtypes = [C.POINTER(C.c_void_p)]
        self.cuda.cudaStreamSynchronize.argtypes = [C.c_void_p]
        self.cuda.cudaStreamDestroy.argtypes = [C.c_void_p]
        self.stream = C.c_void_p()
        self.allocations = []
        self.check(self.cuda.cudaStreamCreate(C.byref(self.stream)))
        self.logger = trt.Logger(trt.Logger.WARNING)
        trt.init_libnvinfer_plugins(self.logger, '')
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(Path(path).read_bytes())
        if self.engine is None:
            raise ValueError('Cannot deserialize raw engine; build on this Jetson with this runtime')
        self.context = self.engine.create_execution_context()
        self.arrays, self.pointers = {}, {}
        inputs, outputs = [], []
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            shape = tuple(self.engine.get_tensor_shape(name))
            if any(d <= 0 for d in shape):
                raise ValueError('Only static batch-one engines supported')
            array = np.empty(shape, dtype=trt.nptype(self.engine.get_tensor_dtype(name)))
            pointer = C.c_void_p()
            self.check(self.cuda.cudaMalloc(C.byref(pointer), array.nbytes))
            self.allocations.append(pointer)
            self.arrays[name], self.pointers[name] = array, pointer
            if not self.context.set_tensor_address(name, pointer.value):
                raise RuntimeError(f'Cannot set tensor address: {name}')
            (inputs if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT else outputs).append(name)
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError('Expected one input and one output')
        self.input, self.output = inputs[0], outputs[0]
        shape = self.arrays[self.input].shape
        if len(shape) != 4 or shape[:2] != (1, 3):
            raise ValueError('Expected [1,3,H,W] input')
        if len(self.arrays[self.output].shape) != 3 or self.arrays[self.output].shape[:2] != (1, 84):
            raise ValueError('Expected [1,84,N] output')
        if self.arrays[self.input].dtype not in (np.dtype('float16'), np.dtype('float32')):
            raise ValueError('Only FP16/FP32 input tensors supported')
        self.height, self.width = shape[2:]

    @staticmethod
    def check(status):
        if status:
            raise RuntimeError(f'CUDA runtime status {status}')

    def close(self):
        if getattr(self, 'stream', None):
            self.cuda.cudaStreamSynchronize(self.stream)
        for pointer in getattr(self, 'allocations', []):
            self.cuda.cudaFree(pointer)
        self.allocations = []
        if getattr(self, 'stream', None):
            self.cuda.cudaStreamDestroy(self.stream)
            self.stream = None

    def predict(self, frame, confidence=.5):
        import cv2
        import numpy as np
        started = time.perf_counter()
        h, w = frame.shape[:2]
        scale = min(self.width/w, self.height/h)
        nw, nh = round(w*scale), round(h*scale)
        left, top = (self.width-nw)//2, (self.height-nh)//2
        resized = cv2.resize(frame, (nw, nh))
        padded = cv2.copyMakeBorder(resized, top, self.height-nh-top,
                                   left, self.width-nw-left, cv2.BORDER_CONSTANT, value=(114,114,114))
        array = self.arrays[self.input]
        array[...] = np.transpose(padded[:, :, ::-1], (2,0,1))[None] / 255.
        self.check(self.cuda.cudaMemcpy(self.pointers[self.input], C.c_void_p(array.ctypes.data), array.nbytes, 1))
        self.check(self.cuda.cudaStreamSynchronize(self.stream))
        inference_start = time.perf_counter()
        if not self.context.execute_async_v3(self.stream.value):
            raise RuntimeError('TensorRT enqueue failed')
        self.check(self.cuda.cudaStreamSynchronize(self.stream))
        inference_ms = (time.perf_counter()-inference_start)*1000
        output = self.arrays[self.output]
        self.check(self.cuda.cudaMemcpy(C.c_void_p(output.ctypes.data), self.pointers[self.output], output.nbytes, 2))
        people = decode_people(output, scale, (left,top), frame.shape, confidence)
        return dict(boxes=people, inference_ms=inference_ms,
                    worker_ms=(time.perf_counter()-started)*1000,
                    input_shape=list(array.shape))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True)
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    engine = Engine(args.engine)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = json.dumps({'ready': True, 'input_shape': list(engine.arrays[engine.input].shape)}).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(payload)

        def do_POST(self):
            import cv2
            import numpy as np
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16*1024*1024:
                    raise ValueError('JPEG body must be 1..16 MiB')
                frame = cv2.imdecode(np.frombuffer(self.rfile.read(length), dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    raise ValueError('Invalid JPEG')
                confidence = float(self.headers.get('X-Confidence', '.5'))
                if not 0 < confidence <= 1:
                    raise ValueError('Confidence must be in (0,1]')
                payload = json.dumps(engine.predict(frame, confidence)).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(payload)
            except Exception as error:
                self.send_error(500, str(error))
    try:
        # Serial requests bound GPU memory and avoid concurrent use of an execution context.
        with HTTPServer(('127.0.0.1', args.port), Handler) as server:
            server.serve_forever()
    finally:
        engine.close()


if __name__ == '__main__':
    main()

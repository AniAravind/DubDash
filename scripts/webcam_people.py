#!/usr/bin/env python3
"""Local webcam person detection; no ROS installation required."""
import argparse
import sys
from pathlib import Path
from webcam_distance import (estimate_distance, reference_focal, save_calibration,
                             load_calibration, positive)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=['webcam', 'iphone'], default='webcam')
    parser.add_argument('--host', default='0.0.0.0', help='iPhone receiver bind address')
    parser.add_argument('--port', type=int, default=8765, help='iPhone receiver port')
    parser.add_argument('--camera', type=int, default=0, help='Camera index (default: 0)')
    parser.add_argument('--model', default='yolo11n.pt', help='YOLO weights; downloaded on first run')
    parser.add_argument('--confidence', type=float, default=0.5)
    parser.add_argument('--device', default='cpu', help='cpu, mps (Apple Silicon), or 0 (CUDA)')
    parser.add_argument('--calibration', default='calibration/webcam.json')
    parser.add_argument('--reference-distance', type=float, default=2.0,
                        help='Measured camera-to-person distance in metres when pressing C')
    parser.add_argument('--person-height', type=float, default=1.7,
                        help='Standing height in metres assumed for people (default: 1.7)')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if args.camera < 0:
        parser.error('--camera must be nonnegative')
    if not 0 < args.confidence <= 1:
        parser.error('--confidence must be between 0 (exclusive) and 1')
    if not positive(args.person_height) or not positive(args.reference_distance):
        parser.error('Person height and reference distance must be finite and positive')
    return args


def run(args):
    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as error:
        raise RuntimeError('Install the webcam dependencies: pip install -r requirements-webcam.txt') from error

    model = YOLO(args.model)
    people = [class_id for class_id, name in model.names.items() if name == 'person']
    if not people:
        raise RuntimeError('This model has no person class. Use the default yolo11n.pt model.')
    if args.source == 'iphone':
        from iphone_view import run_iphone
        return run_iphone(args, model, people)
    camera = cv2.VideoCapture(args.camera)
    title = 'DubDash — people (Q or Esc to quit)'
    try:
        if not camera.isOpened():
            raise RuntimeError('Cannot open webcam. Allow camera access for your terminal, '
                               'close other camera apps, or try --camera 1.')
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)
        print('Webcam started. Press Q or Esc in the video window to stop.')
        calibration = None
        image_size = None
        maps = None
        notice = ''
        while True:
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError('Camera stopped returning frames. Check camera access and connection.')
            current_size = (frame.shape[1], frame.shape[0])
            if image_size != current_size:
                image_size = current_size
                calibration = None
                maps = None
                if Path(args.calibration).exists():
                    calibration = load_calibration(args.calibration, image_size, args.camera)
                    if calibration['mode'] == 'intrinsics':
                        import numpy as np
                        matrix = np.array(calibration['camera_matrix'], dtype=float)
                        distortion = np.array(calibration['distortion'], dtype=float)
                        if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
                            raise ValueError('Invalid camera matrix')
                        if distortion.size not in (4, 5, 8, 12, 14) or not np.isfinite(distortion).all():
                            raise ValueError('Invalid distortion coefficients')
                        maps = cv2.initUndistortRectifyMap(
                            matrix, distortion, None, matrix, image_size, cv2.CV_32FC1)
            if maps is not None:
                frame = cv2.remap(frame, maps[0], maps[1], cv2.INTER_LINEAR)
            result = model.predict(frame, classes=people, conf=args.confidence,
                                   device=args.device, verbose=False)[0]
            image = frame.copy()
            boxes = result.boxes.xyxy.cpu().tolist()
            scores = result.boxes.conf.cpu().tolist()
            for box, score in zip(boxes, scores):
                distance = None
                if calibration:
                    height = (calibration['person_height'] if calibration['mode'] == 'reference'
                              else args.person_height)
                    distance = estimate_distance(box, image_size, calibration['focal_y'], height)
                label = f'person {score:.0%}'
                if distance is not None:
                    label += f' | ~{distance:.1f} m'
                else:
                    label += ' | distance unavailable'
                x1, y1, x2, y2 = (int(v) for v in box)
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(image, label, (max(0, x1), max(85, y1 - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            count = len(result.boxes)
            cv2.putText(image, f'People: {count}', (16, 32), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 255, 0), 2)
            status = ('Approximate distance; full standing people only' if calibration else
                      f'Stand {args.reference_distance:g} m away; full body; press C to calibrate')
            cv2.putText(image, status, (16, 56), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 220, 255), 1)
            if notice:
                cv2.putText(image, notice, (16, image_size[1] - 18),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1)
            cv2.imshow(title, image)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord('q'), ord('Q')):
                break
            if key in (ord('c'), ord('C')):
                if calibration and calibration['mode'] == 'intrinsics':
                    notice = 'Lens calibration loaded; height assumption set by --person-height'
                elif len(boxes) != 1:
                    notice = 'Calibration needs exactly one full standing person'
                else:
                    try:
                        focal = reference_focal(boxes[0], image_size,
                                                args.reference_distance, args.person_height)
                        calibration = {'mode': 'reference', 'focal_y': focal,
                                       'person_height': args.person_height,
                                       'reference_distance': args.reference_distance,
                                       'image_size': list(image_size), 'camera': args.camera}
                        save_calibration(args.calibration, calibration)
                        notice = 'Reference saved; estimates assume the same standing height'
                    except ValueError as error:
                        notice = str(error)
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


def main():
    args = parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f'DubDash: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

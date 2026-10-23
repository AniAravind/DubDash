#!/usr/bin/env python3
"""Local webcam person detection; no ROS installation required."""
import argparse
import sys


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int, default=0, help='Camera index (default: 0)')
    parser.add_argument('--model', default='yolo11n.pt', help='YOLO weights; downloaded on first run')
    parser.add_argument('--confidence', type=float, default=0.5)
    parser.add_argument('--device', default='cpu', help='cpu, mps (Apple Silicon), or 0 (CUDA)')
    args = parser.parse_args(argv)
    if args.camera < 0:
        parser.error('--camera must be nonnegative')
    if not 0 < args.confidence <= 1:
        parser.error('--confidence must be between 0 (exclusive) and 1')
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
    camera = cv2.VideoCapture(args.camera)
    title = 'DubDash — people (Q or Esc to quit)'
    try:
        if not camera.isOpened():
            raise RuntimeError('Cannot open webcam. Allow camera access for your terminal, '
                               'close other camera apps, or try --camera 1.')
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)
        print('Webcam started. Press Q or Esc in the video window to stop.')
        while True:
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError('Camera stopped returning frames. Check camera access and connection.')
            result = model.predict(frame, classes=people, conf=args.confidence,
                                   device=args.device, verbose=False)[0]
            image = result.plot()
            count = len(result.boxes)
            cv2.putText(image, f'People: {count}', (16, 32), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 255, 0), 2)
            cv2.imshow(title, image)
            if cv2.waitKey(1) & 0xFF in (27, ord('q'), ord('Q')):
                break
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

#!/usr/bin/env python3
"""Calibrate webcam intrinsics using varied views of a flat checkerboard."""
import argparse
import sys
from webcam_distance import save_calibration, positive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--columns', type=int, default=9, help='Inner corners, not squares')
    parser.add_argument('--rows', type=int, default=6, help='Inner corners, not squares')
    parser.add_argument('--square-size', type=float, default=0.025, help='Square side in metres')
    parser.add_argument('--output', default='calibration/webcam.json')
    args = parser.parse_args()
    if args.camera < 0 or min(args.columns, args.rows) < 3 or not positive(args.square_size):
        parser.error('Use a valid camera, at least 3x3 inner corners and positive square size')
    import cv2
    import numpy as np
    pattern = (args.columns, args.rows)
    grid = np.zeros((args.columns * args.rows, 3), np.float32)
    grid[:, :2] = np.mgrid[0:args.columns, 0:args.rows].T.reshape(-1, 2)
    grid *= args.square_size
    objects, images = [], []
    camera = cv2.VideoCapture(args.camera)
    title = 'Calibration: Space=capture, C=solve/save, Q=quit'
    size = None
    notice = 'Move and tilt the board between captures; cover the whole image'
    try:
        if not camera.isOpened():
            raise RuntimeError('Cannot open camera. Check camera permissions or --camera index.')
        while True:
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError('Camera stopped returning frames')
            current = (frame.shape[1], frame.shape[0])
            if size is not None and size != current:
                raise RuntimeError('Resolution changed during calibration; restart capture')
            size = current
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            found, corners = cv2.findChessboardCornersSB(gray, pattern)
            preview = frame.copy()
            if found:
                cv2.drawChessboardCorners(preview, pattern, corners, found)
            cv2.putText(preview, f'Views: {len(images)} (need 15+) | board: {found}',
                        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.putText(preview, notice, (10, 55), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (0, 220, 255), 1)
            cv2.imshow(title, preview)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord('q'), ord('Q')) or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == 32 and found:
                # Reject near-identical views instead of repeatedly sampling one pose.
                if images and min(np.sqrt(np.mean((corners - prior) ** 2)) for prior in images) < 10:
                    notice = 'Move/tilt the board more before capturing again'
                else:
                    objects.append(grid.copy())
                    images.append(corners.copy())
                    notice = 'Captured; change board angle, position and distance'
            if key in (ord('c'), ord('C')):
                if len(images) < 15:
                    notice = 'Capture at least 15 varied board views first'
                    continue
                rms, matrix, distortion, _, _ = cv2.calibrateCamera(objects, images, size, None, None)
                if (not np.isfinite(matrix).all() or not np.isfinite(distortion).all()
                        or not np.isfinite(rms) or rms > 1.0
                        or matrix[0, 0] <= 0 or matrix[1, 1] <= 0):
                    notice = 'Calibration rejected (RMS >1px or invalid). Restart with better views'
                    continue
                save_calibration(args.output, {
                    'mode': 'intrinsics', 'image_size': list(size), 'camera': args.camera,
                    'focal_y': float(matrix[1, 1]), 'camera_matrix': matrix.tolist(),
                    'distortion': distortion.ravel().tolist(), 'rms_pixels': float(rms),
                    'views': len(images), 'board_inner_corners': list(pattern),
                    'square_size_m': args.square_size,
                })
                print(f'Saved {args.output}; reprojection RMS {rms:.3f} pixels')
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f'DubDash calibration: {error}', file=sys.stderr)
        sys.exit(1)

import AVFoundation
import Combine
import CoreImage
import ImageIO
import UIKit

/// All capture/socket state lives on queue; published UI state lives on the main queue.
/// Sendable is unchecked because this NSObject owns AVFoundation objects confined to queue.
final class DepthCapture: NSObject, ObservableObject, AVCaptureDataOutputSynchronizerDelegate, @unchecked Sendable {
    @Published var preview: UIImage?
    @Published var status = "Start the Mac viewer, then enter its address and token."
    @Published var running = false

    private let queue = DispatchQueue(label: "DubDash.capture")
    private let context = CIContext()
    private var session: AVCaptureSession?
    private var videoOutput: AVCaptureVideoDataOutput?
    private var depthOutput: AVCaptureDepthDataOutput?
    private var synchronizer: AVCaptureDataOutputSynchronizer?
    private var socket: URLSessionWebSocketTask?
    private var networkSession: URLSession?
    private var watchdog: DispatchSourceTimer?
    private var observers: [NSObjectProtocol] = []
    private var connectionID = UUID()
    private var uiID = UUID() // main queue only
    private var authenticated = false
    private var awaitingSequence: Int?
    private var sentAt: TimeInterval = 0
    private var pending: (data: Data, sequence: Int, timestamp: TimeInterval)?
    private var sequence = 0
    private var lastEncoded: TimeInterval = 0

    func connect(address: String, token: String) {
        let address = address.trimmingCharacters(in: .whitespacesAndNewlines)
        let token = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: address), url.scheme == "ws", url.host != nil,
              url.user == nil, url.password == nil, url.query == nil, !token.isEmpty else {
            status = "Enter ws://<Mac Wi-Fi address>:8765 and its session token."
            return
        }
        let id = UUID()
        uiID = id
        running = true
        status = "Requesting camera access..."
        queue.async {
            self.tearDown()
            self.connectionID = id
            AVCaptureDevice.requestAccess(for: .video) { granted in
                self.queue.async {
                    guard self.connectionID == id else { return }
                    guard granted else {
                        self.fail("Camera permission denied. Enable it in Settings.", id: id)
                        return
                    }
                    do {
                        try self.configureCamera(id: id)
                        self.openSocket(url: url, token: token, id: id)
                    } catch {
                        self.fail(error.localizedDescription, id: id)
                    }
                }
            }
        }
    }

    func stop() {
        uiID = UUID()
        running = false
        status = "Stopped"
        preview = nil
        queue.async {
            self.connectionID = UUID()
            self.tearDown()
        }
    }

    private func publish(_ text: String, id: UUID) {
        DispatchQueue.main.async {
            guard self.uiID == id else { return }
            self.status = text
        }
    }

    private func fail(_ text: String, id: UUID) {
        guard connectionID == id else { return }
        tearDown()
        connectionID = UUID()
        DispatchQueue.main.async {
            guard self.uiID == id else { return }
            self.running = false
            self.preview = nil
            self.status = text
        }
    }

    private func tearDown() {
        watchdog?.cancel()
        watchdog = nil
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        networkSession?.invalidateAndCancel()
        networkSession = nil
        synchronizer?.setDelegate(nil, queue: nil)
        synchronizer = nil
        session?.stopRunning()
        session = nil
        videoOutput = nil
        depthOutput = nil
        observers.forEach { NotificationCenter.default.removeObserver($0) }
        observers.removeAll()
        authenticated = false
        awaitingSequence = nil
        pending = nil
        sequence = 0
        lastEncoded = 0
    }

    private func configureCamera(id: UUID) throws {
        guard let camera = AVCaptureDevice.default(.builtInTrueDepthCamera,
                                                   for: .video, position: .front) else {
            throw CaptureError.message("This device has no available front TrueDepth camera.")
        }
        // Choose a modest, depth-capable native format with the SAME full FOV.
        let candidates = camera.formats.filter { format in
            let size = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
            return size.width <= 1280 && size.height <= 960
                && !format.supportedDepthDataFormats.isEmpty
                && format.videoSupportedFrameRateRanges.contains { $0.minFrameRate <= 15 && $0.maxFrameRate >= 15 }
        }
        guard let format = candidates.min(by: {
            let a = CMVideoFormatDescriptionGetDimensions($0.formatDescription)
            let b = CMVideoFormatDescriptionGetDimensions($1.formatDescription)
            return abs(Int(a.width) - 640) < abs(Int(b.width) - 640)
        }), let depthFormat = format.supportedDepthDataFormats.filter({
            let subtype = CMFormatDescriptionGetMediaSubType($0.formatDescription)
            return subtype == kCVPixelFormatType_DepthFloat16 || subtype == kCVPixelFormatType_DepthFloat32
        }).max(by: {
            CMVideoFormatDescriptionGetDimensions($0.formatDescription).width <
                CMVideoFormatDescriptionGetDimensions($1.formatDescription).width
        }) else {
            throw CaptureError.message("No compatible video + metric depth format at 15 fps.")
        }
        let capture = AVCaptureSession()
        capture.beginConfiguration()
        capture.sessionPreset = .inputPriority
        let input = try AVCaptureDeviceInput(device: camera)
        guard capture.canAddInput(input) else { throw CaptureError.message("Cannot add TrueDepth input.") }
        capture.addInput(input)
        try camera.lockForConfiguration()
        camera.activeFormat = format
        camera.activeDepthDataFormat = depthFormat
        camera.activeVideoMinFrameDuration = CMTime(value: 1, timescale: 15)
        camera.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: 15)
        camera.videoZoomFactor = 1
        camera.unlockForConfiguration()
        let video = AVCaptureVideoDataOutput()
        video.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        video.alwaysDiscardsLateVideoFrames = true
        let depth = AVCaptureDepthDataOutput()
        depth.isFilteringEnabled = false // don't fill holes or mix neighbouring frames
        guard capture.canAddOutput(video), capture.canAddOutput(depth) else {
            throw CaptureError.message("Cannot add synchronized video and depth outputs.")
        }
        capture.addOutput(video)
        capture.addOutput(depth)
        for output in [video as AVCaptureOutput, depth as AVCaptureOutput] {
            if let connection = output.connection(with: output === video ? .video : .depthData) {
                if connection.isVideoRotationAngleSupported(0) { connection.videoRotationAngle = 0 }
                if connection.isVideoMirroringSupported {
                    connection.automaticallyAdjustsVideoMirroring = false
                    connection.isVideoMirrored = false
                }
                if connection.isVideoStabilizationSupported { connection.preferredVideoStabilizationMode = .off }
            }
        }
        capture.commitConfiguration()
        self.session = capture
        self.videoOutput = video
        self.depthOutput = depth
        let sync = AVCaptureDataOutputSynchronizer(dataOutputs: [video, depth])
        sync.setDelegate(self, queue: queue)
        synchronizer = sync
        for name in [AVCaptureSession.runtimeErrorNotification, AVCaptureSession.wasInterruptedNotification] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: capture, queue: nil) { _ in
                self.queue.async { self.fail("Camera interrupted. Tap Connect to restart.", id: id) }
            })
        }
        capture.startRunning()
        publish("Camera ready; connecting to Mac...", id: id)
    }

    private func openSocket(url: URL, token: String, id: UUID) {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 10
        let network = URLSession(configuration: config)
        networkSession = network
        let task = network.webSocketTask(with: url)
        task.maximumMessageSize = 65536
        socket = task
        task.resume()
        let hello = String(data: try! JSONSerialization.data(withJSONObject: ["token": token]), encoding: .utf8)!
        Task {
            do {
                try await task.send(.string(hello))
                self.receive(task: task, id: id)
            } catch {
                self.queue.async { self.fail("Connection failed: \(error.localizedDescription)", id: id) }
            }
        }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + 0.25, repeating: 0.25)
        let started = ProcessInfo.processInfo.systemUptime
        timer.setEventHandler { [weak self] in
            guard let self, self.connectionID == id else { return }
            let now = ProcessInfo.processInfo.systemUptime
            if (!self.authenticated && now - started > 10) ||
                (self.awaitingSequence != nil && now - self.sentAt > 2) {
                self.fail("Mac stopped responding. Check Wi-Fi/token, then reconnect.", id: id)
            }
        }
        watchdog = timer
        timer.resume()
    }

    private func receive(task: URLSessionWebSocketTask, id: UUID) {
        Task {
            do {
                let message = try await task.receive()
                guard case .string(let text) = message,
                      let data = text.data(using: .utf8),
                      let reply = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    throw CaptureError.message("Invalid server reply")
                }
                self.queue.async {
                    guard self.connectionID == id else { return }
                    if reply["type"] as? String == "ready", reply["version"] as? Int == 1 {
                        self.authenticated = true
                        self.publish("Connected - streaming TrueDepth to Mac", id: id)
                    } else if reply["type"] as? String == "ack",
                              reply["sequence"] as? Int == self.awaitingSequence {
                        self.awaitingSequence = nil
                        if let next = self.pending {
                            self.pending = nil
                            if ProcessInfo.processInfo.systemUptime - next.timestamp < 0.5 {
                                self.send(next.data, sequence: next.sequence, task: task, id: id)
                            }
                        }
                    } else {
                        self.fail("Unexpected server acknowledgement", id: id)
                        return
                    }
                    self.receive(task: task, id: id)
                }
            } catch {
                self.queue.async { self.fail("Disconnected: \(error.localizedDescription)", id: id) }
            }
        }
    }

    private func send(_ data: Data, sequence: Int, task: URLSessionWebSocketTask, id: UUID) {
        awaitingSequence = sequence
        sentAt = ProcessInfo.processInfo.systemUptime
        Task {
            do { try await task.send(.data(data)) }
            catch { self.queue.async { self.fail("Send failed: \(error.localizedDescription)", id: id) } }
        }
    }

    func dataOutputSynchronizer(_ synchronizer: AVCaptureDataOutputSynchronizer,
                                didOutput collection: AVCaptureSynchronizedDataCollection) {
        guard let videoOutput, let depthOutput,
              let video = collection.synchronizedData(for: videoOutput) as? AVCaptureSynchronizedSampleBufferData,
              !video.sampleBufferWasDropped,
              let buffer = CMSampleBufferGetImageBuffer(video.sampleBuffer) else { return }
        let now = ProcessInfo.processInfo.systemUptime
        guard now - lastEncoded >= 0.1 else { return }
        lastEncoded = now
        let id = connectionID
        let ciImage = CIImage(cvPixelBuffer: buffer)
        // Native buffers stay unrotated/unmirrored on the wire. Both receivers use this same transform.
        if let cg = context.createCGImage(ciImage.oriented(.right).oriented(.upMirrored),
                                          from: ciImage.oriented(.right).extent) {
            let image = UIImage(cgImage: cg)
            DispatchQueue.main.async {
                if self.uiID == id && self.running { self.preview = image }
            }
        }
        guard authenticated, let socket else { return }
        do {
            guard let jpeg = context.jpegRepresentation(of: ciImage, colorSpace: CGColorSpaceCreateDeviceRGB(),
                                                         options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.65]) else { return }
            var metadata: [String: Any] = [
                "version": 1, "sequence": sequence,
                "timestamp": CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(video.sampleBuffer)),
                "video_size": [CVPixelBufferGetWidth(buffer), CVPixelBufferGetHeight(buffer)],
                "jpeg_bytes": jpeg.count, "rotation_degrees": 90, "mirrored": true,
                "geometry": "apple_video_aligned"
            ]
            var bytes = Data()
            if let depth = collection.synchronizedData(for: depthOutput) as? AVCaptureSynchronizedDepthData,
               !depth.depthDataWasDropped {
                let metric = depth.depthData.converting(toDepthDataType: kCVPixelFormatType_DepthFloat32)
                if let calibration = metric.cameraCalibrationData {
                    let depthMap = metric.depthDataMap
                    let dw = CVPixelBufferGetWidth(depthMap), dh = CVPixelBufferGetHeight(depthMap)
                    let vw = CVPixelBufferGetWidth(buffer), vh = CVPixelBufferGetHeight(buffer)
                    let reference = calibration.intrinsicMatrixReferenceDimensions
                    guard abs(Double(dw) / Double(dh) - Double(vw) / Double(vh)) < 0.01,
                          abs(reference.width / reference.height - Double(vw) / Double(vh)) < 0.01 else {
                        throw CaptureError.message("Video/depth crop mismatch. Unsupported camera format.")
                    }
                    CVPixelBufferLockBaseAddress(depthMap, .readOnly)
                    defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }
                    guard let base = CVPixelBufferGetBaseAddress(depthMap) else { return }
                    let stride = CVPixelBufferGetBytesPerRow(depthMap)
                    for row in 0..<dh { bytes.append(base.advanced(by: row * stride).assumingMemoryBound(to: UInt8.self), count: dw * 4) }
                    let k = calibration.intrinsicMatrix
                    metadata["depth_size"] = [dw, dh]
                    metadata["depth_format"] = "float32_le_m"
                    metadata["depth_absolute"] = metric.depthDataAccuracy == .absolute
                    metadata["calibration"] = [
                        "reference_size": [Int(reference.width), Int(reference.height)],
                        "intrinsic_matrix": (0..<3).map { row in (0..<3).map { column in Double(k[column][row]) } },
                        "lens_distortion_center": [calibration.lensDistortionCenter.x, calibration.lensDistortionCenter.y]
                    ]
                }
            }
            let header = try JSONSerialization.data(withJSONObject: metadata)
            var length = UInt32(header.count).bigEndian
            var packet = Data(bytes: &length, count: 4)
            packet.append(header)
            packet.append(jpeg)
            packet.append(bytes)
            let frameSequence = sequence
            sequence += 1
            if awaitingSequence == nil {
                send(packet, sequence: frameSequence, task: socket, id: id)
            } else {
                pending = (packet, frameSequence, now) // replace, never append
            }
        } catch {
            fail("Capture failed: \(error.localizedDescription)", id: id)
        }
    }
}

private enum CaptureError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

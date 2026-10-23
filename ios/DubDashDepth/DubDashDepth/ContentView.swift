import UIKit
import Combine

final class CameraViewController: UIViewController, UITextFieldDelegate, UIGestureRecognizerDelegate {
    private let capture = DepthCapture()
    private var subscriptions = Set<AnyCancellable>()
    private let preview = UIImageView()
    private let address = UITextField()
    private let token = UITextField()
    private let status = UILabel()
    private let connect = UIButton(type: .system)
    private let stop = UIButton(type: .system)
    private let scroll = UIScrollView()
    private var previousViewportHeight: CGFloat = 0

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        let title = UILabel()
        title.text = "DubDash TrueDepth"
        title.font = .preferredFont(forTextStyle: .title1)
        title.textAlignment = .center
        preview.contentMode = .scaleAspectFit
        preview.backgroundColor = .black
        preview.heightAnchor.constraint(equalToConstant: 300).isActive = true
        address.placeholder = "ws://192.168.1.20:8765"
        address.keyboardType = .URL
        token.placeholder = "Session token shown on Mac"
        token.isSecureTextEntry = true
        address.returnKeyType = .next
        token.returnKeyType = .done
        let keyboardToolbar = UIToolbar()
        keyboardToolbar.items = [
            UIBarButtonItem(systemItem: .flexibleSpace),
            UIBarButtonItem(barButtonSystemItem: .done, target: self,
                            action: #selector(dismissKeyboard))
        ]
        keyboardToolbar.sizeToFit()
        for field in [address, token] {
            field.delegate = self
            field.inputAccessoryView = keyboardToolbar
            field.borderStyle = .roundedRect
            field.autocapitalizationType = .none
            field.autocorrectionType = .no
            field.heightAnchor.constraint(equalToConstant: 44).isActive = true
        }
        connect.setTitle("Connect", for: .normal)
        connect.addTarget(self, action: #selector(connectCapture), for: .touchUpInside)
        stop.setTitle("Stop", for: .normal)
        stop.addTarget(self, action: #selector(stopCapture), for: .touchUpInside)
        let buttons = UIStackView(arrangedSubviews: [connect, stop])
        buttons.distribution = .fillEqually
        status.numberOfLines = 0
        status.accessibilityIdentifier = "connectionStatus"
        let detail = UILabel()
        detail.text = "Keep this app open and your phone upright. Front-camera video and depth stay on your local Wi-Fi and are not recorded. Depth may be unavailable outside the sensor's usable range."
        detail.numberOfLines = 0
        detail.font = .preferredFont(forTextStyle: .footnote)
        detail.textColor = .secondaryLabel
        let stack = UIStackView(arrangedSubviews: [title, preview, address, token, buttons, status, detail])
        stack.axis = .vertical
        stack.spacing = 16
        scroll.alwaysBounceVertical = true
        scroll.keyboardDismissMode = .interactive
        let backgroundTap = UITapGestureRecognizer(target: self, action: #selector(dismissKeyboard))
        backgroundTap.cancelsTouchesInView = false
        backgroundTap.delegate = self
        scroll.addGestureRecognizer(backgroundTap)
        scroll.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(scroll)
        stack.translatesAutoresizingMaskIntoConstraints = false
        scroll.addSubview(stack)
        NSLayoutConstraint.activate([
            scroll.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            scroll.bottomAnchor.constraint(equalTo: view.keyboardLayoutGuide.topAnchor),
            scroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            stack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor, constant: 20),
            stack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor, constant: -20),
            stack.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor, constant: -20),
            stack.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor, constant: -40)
        ])
        capture.$preview.receive(on: DispatchQueue.main).sink { [weak self] in self?.preview.image = $0 }
            .store(in: &subscriptions)
        capture.$status.receive(on: DispatchQueue.main).sink { [weak self] in self?.status.text = $0 }
            .store(in: &subscriptions)
        capture.$running.receive(on: DispatchQueue.main).sink { [weak self] running in
            self?.connect.isEnabled = !running
            self?.stop.isEnabled = running
            self?.address.isEnabled = !running
            self?.token.isEnabled = !running
            UIApplication.shared.isIdleTimerDisabled = running
        }.store(in: &subscriptions)
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        // The keyboard guide resizes the viewport; reveal the focused field after it changes.
        if scroll.bounds.height != previousViewportHeight {
            previousViewportHeight = scroll.bounds.height
            revealFocusedField(animated: false)
        }
    }

    private func revealFocusedField(animated: Bool) {
        guard let field = [address, token].first(where: { $0.isFirstResponder }) else { return }
        let rect = field.convert(field.bounds, to: scroll).insetBy(dx: 0, dy: -12)
        scroll.scrollRectToVisible(rect, animated: animated)
    }

    func textFieldDidBeginEditing(_ textField: UITextField) {
        view.layoutIfNeeded()
        revealFocusedField(animated: true)
    }

    func textFieldShouldReturn(_ textField: UITextField) -> Bool {
        if textField === address {
            token.becomeFirstResponder()
        } else {
            dismissKeyboard()
        }
        return true
    }

    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer,
                           shouldReceive touch: UITouch) -> Bool {
        // Tapping inputs/buttons must keep their normal behaviour.
        var touchedView = touch.view
        while let current = touchedView {
            if current is UIControl { return false }
            touchedView = current.superview
        }
        return true
    }

    @objc private func dismissKeyboard() { view.endEditing(true) }

    @objc private func connectCapture() {
        view.endEditing(true)
        capture.connect(address: address.text ?? "", token: token.text ?? "")
    }

    @objc func stopCapture() { capture.stop() }
}

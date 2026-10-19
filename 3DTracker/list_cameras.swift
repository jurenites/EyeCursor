import AVFoundation
import Foundation

// Match the order used by OpenCV's macOS AVFoundation backend: video and
// muxed capture devices, sorted by uniqueID before applying an integer index.
let devices = (AVCaptureDevice.devices(for: .video) + AVCaptureDevice.devices(for: .muxed))
    .sorted { $0.uniqueID < $1.uniqueID }

let cameras: [[String: Any]] = devices.enumerated().map { index, device in
    [
        "index": index,
        "name": device.localizedName,
        "id": device.uniqueID,
        "type": device.deviceType.rawValue,
        "has_torch": device.hasTorch,
        "torch_available": device.isTorchAvailable,
        "has_flash": device.hasFlash,
    ]
}

let data = try JSONSerialization.data(withJSONObject: cameras)
print(String(data: data, encoding: .utf8)!)

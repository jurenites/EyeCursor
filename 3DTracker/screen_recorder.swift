import Foundation
import ScreenCaptureKit
import CoreGraphics
import CoreMedia
import AVFoundation

func jsonLine(_ value: [String: Any]) -> String {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    return String(data: data, encoding: .utf8)! + "\n"
}

final class Recorder: NSObject, SCStreamOutput, SCStreamDelegate, SCRecordingOutputDelegate {
    private let display: SCDisplay
    private let frames: FileHandle
    private var firstPTS: CMTime?
    private var frameCount = 0
    private(set) var finished = false
    private(set) var failure: String?

    init(display: SCDisplay, framesURL: URL) throws {
        self.display = display
        FileManager.default.createFile(atPath: framesURL.path, contents: nil)
        self.frames = try FileHandle(forWritingTo: framesURL)
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of outputType: SCStreamOutputType) {
        guard outputType == .screen, sampleBuffer.isValid else { return }
        guard let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer,
                createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
              let statusValue = attachments.first?[.status] as? Int,
              SCFrameStatus(rawValue: statusValue) == .complete else { return }
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        if firstPTS == nil {
            firstPTS = pts
            let epoch = Int64(Date().timeIntervalSince1970 * 1_000_000_000)
            print(jsonLine(["type": "start", "epoch_ns": epoch,
                            "display_id": display.displayID, "width": display.width,
                            "height": display.height]), terminator: "")
            fflush(stdout)
        }
        let elapsed = CMTimeGetSeconds(CMTimeSubtract(pts, firstPTS!)) * 1000
        let cursor = CGEvent(source: nil)?.location ?? .zero
        let rect = display.frame
        let x = (cursor.x - rect.minX) / rect.width
        let y = (cursor.y - rect.minY) / rect.height
        let line = jsonLine(["frame": frameCount, "t_ms": elapsed,
                             "cursor_x": cursor.x, "cursor_y": cursor.y,
                             "cursor_nx": x, "cursor_ny": y,
                             "cursor_on_display": x >= 0 && x <= 1 && y >= 0 && y <= 1])
        if let data = line.data(using: .utf8) { try? frames.write(contentsOf: data) }
        frameCount += 1
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        failure = error.localizedDescription
        finished = true
    }

    func recordingOutputDidStartRecording(_ recordingOutput: SCRecordingOutput) {}
    func recordingOutputDidFinishRecording(_ recordingOutput: SCRecordingOutput) { finished = true }
    func recordingOutput(_ recordingOutput: SCRecordingOutput, didFailWithError error: Error) {
        failure = error.localizedDescription
        finished = true
    }

    func close() {
        try? frames.close()
    }
}

@main struct Main {
    static func main() async {
        do {
            let args = CommandLine.arguments
            guard args.count == 2 && args[1] == "--list" || args.count == 5 && args[1] == "--record" else {
                throw NSError(domain: "EyeCursor", code: 1, userInfo: [NSLocalizedDescriptionKey:
                    "Usage: screen_recorder --list | --record DISPLAY_ID VIDEO.mov FRAMES.jsonl"])
            }
            guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else {
                throw NSError(domain: "EyeCursor", code: 2, userInfo: [NSLocalizedDescriptionKey:
                    "Screen Recording permission is required. Allow it in System Settings, then retry."])
            }
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            if args[1] == "--list" {
                for display in content.displays {
                    print(jsonLine(["id": display.displayID, "width": display.width,
                                    "height": display.height, "x": display.frame.minX,
                                    "y": display.frame.minY, "point_width": display.frame.width,
                                    "point_height": display.frame.height]), terminator: "")
                }
                return
            }
            guard let id = UInt32(args[2]),
                  let display = content.displays.first(where: { $0.displayID == id }) else {
                throw NSError(domain: "EyeCursor", code: 3, userInfo: [NSLocalizedDescriptionKey:
                    "Selected display is unavailable"])
            }
            let recorder = try Recorder(display: display, framesURL: URL(fileURLWithPath: args[4]))
            let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
            let config = SCStreamConfiguration()
            config.width = display.width
            config.height = display.height
            config.minimumFrameInterval = CMTime(value: 1, timescale: 24)
            config.queueDepth = 5
            config.showsCursor = true
            config.capturesAudio = false
            let stream = SCStream(filter: filter, configuration: config, delegate: recorder)
            try stream.addStreamOutput(recorder, type: .screen,
                                      sampleHandlerQueue: DispatchQueue(label: "eyetracker.screen.frames"))
            let outputConfig = SCRecordingOutputConfiguration()
            outputConfig.outputURL = URL(fileURLWithPath: args[3])
            outputConfig.outputFileType = .mp4
            outputConfig.videoCodecType = .h264
            let output = SCRecordingOutput(configuration: outputConfig, delegate: recorder)
            try stream.addRecordingOutput(output)
            try await stream.startCapture()
            _ = readLine()
            try stream.removeRecordingOutput(output)
            for _ in 0..<100 where !recorder.finished {
                try await Task.sleep(for: .milliseconds(100))
            }
            try await stream.stopCapture()
            recorder.close()
            if let error = recorder.failure { throw NSError(domain: "EyeCursor", code: 4,
                    userInfo: [NSLocalizedDescriptionKey: error]) }
        } catch {
            fputs("screen recorder: \(error.localizedDescription)\n", stderr)
            exit(1)
        }
    }
}

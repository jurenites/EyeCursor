import AppKit
import WebKit
final class Renderer: NSObject, WKNavigationDelegate {
    let web: WKWebView
    let output: String
    init(source: String, output: String) throws {
        self.output = output
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        self.web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1024, height: 1024), configuration: configuration)
        super.init()
        web.navigationDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        let svg = try String(contentsOfFile: source, encoding: .utf8)
        web.loadHTMLString("<html><head><style>html,body{margin:0;width:1024px;height:1024px;background:transparent}svg{display:block}</style></head><body>\(svg)</body></html>", baseURL: nil)
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        let config = WKSnapshotConfiguration()
        config.rect = NSRect(x: 0, y: 0, width: 1024, height: 1024)
        config.snapshotWidth = 1024
        web.takeSnapshot(with: config) { image, error in
            guard let image = image, let data = image.tiffRepresentation,
                  let bitmap = NSBitmapImageRep(data: data),
                  let png = bitmap.representation(using: .png, properties: [:]) else {
                print("Render failed: \(String(describing: error))"); exit(1)
            }
            do { try png.write(to: URL(fileURLWithPath: self.output)); print("Rendered SVG through WebKit"); exit(0) }
            catch { print(error); exit(1) }
        }
    }
}
let app = NSApplication.shared
let renderer = try Renderer(source: CommandLine.arguments[1], output: CommandLine.arguments[2])
DispatchQueue.main.asyncAfter(deadline: .now() + 25) { print("Render timed out"); exit(1) }
app.run()

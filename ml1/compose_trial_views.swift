// One image represents one instant; context and crop are simultaneous panels.
import Foundation
import AppKit

do {
    let args = CommandLine.arguments
    guard args.count == 2 else { throw NSError(domain: "Usage", code: 1) }
    let folder = URL(fileURLWithPath: args[1], isDirectory: true)
    let data = try Data(contentsOf: folder.appendingPathComponent("frames.json"))
    guard let metadata = try JSONSerialization.jsonObject(with: data) as? [String: Any],
          let frames = metadata["frames"] as? [[String: Any]] else { throw NSError(domain: "Metadata", code: 2) }
    for frame in frames {
        guard let index = frame["index"] as? Int, let time = frame["timestamp_sec"] as? Double,
              let full = frame["context_file"] as? String, let detail = frame["file"] as? String,
              let scene = NSImage(contentsOf: folder.appendingPathComponent(full)),
              let crop = NSImage(contentsOf: folder.appendingPathComponent(detail)),
              let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 800, pixelsHigh: 540,
                bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
              let context = NSGraphicsContext(bitmapImageRep: bitmap) else { throw NSError(domain: "Image", code: 3) }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = context
        NSColor.white.setFill()
        NSBezierPath(rect: NSRect(x: 0, y: 0, width: 800, height: 540)).fill()
        func draw(_ image: NSImage, _ rect: NSRect) {
            let ratio = min(rect.width / image.size.width, rect.height / image.size.height)
            let size = NSSize(width: image.size.width * ratio, height: image.size.height * ratio)
            image.draw(in: NSRect(x: rect.midX-size.width/2, y: rect.midY-size.height/2,
                                 width: size.width, height: size.height))
        }
        draw(scene, NSRect(x: 10, y: 40, width: 260, height: 460))
        draw(crop, NSRect(x: 285, y: 40, width: 505, height: 460))
        let attributes: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 17), .foregroundColor: NSColor.black]
        (String(format: "%.3f s — SAME INSTANT: full scene + hand detail", time) as NSString)
            .draw(at: NSPoint(x: 10, y: 510), withAttributes: attributes)
        ("Full scene" as NSString).draw(at: NSPoint(x: 70, y: 10), withAttributes: attributes)
        ("Hand detail — same time" as NSString).draw(at: NSPoint(x: 380, y: 10), withAttributes: attributes)
        NSGraphicsContext.restoreGraphicsState()
        guard let jpeg = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.94]) else {
            throw NSError(domain: "JPEG", code: 4)
        }
        try jpeg.write(to: folder.appendingPathComponent(String(format: "combined-%02d.jpg", index)), options: .atomic)
    }
    print("Composed \(frames.count) simultaneous views")
} catch {
    let e = error as NSError
    fputs("Composition failed (\(e.domain), code \(e.code))\n", stderr)
    exit(1)
}

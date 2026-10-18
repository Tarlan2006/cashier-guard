// Native macOS extraction: no Python video dependencies or network access.
import Foundation
import AVFoundation
import AppKit

do {
    let args = CommandLine.arguments
    guard [5, 7, 8, 12].contains(args.count), let count = Int(args[3]), (2...32).contains(count),
          let size = Int(args[4]), (224...1280).contains(size) else {
        throw NSError(domain: "Usage", code: 1)
    }
    let asset = AVURLAsset(url: URL(fileURLWithPath: args[1]))
    let duration = CMTimeGetSeconds(asset.duration)
    guard duration.isFinite, duration > 0 else { throw NSError(domain: "Duration", code: 2) }
    let rangeStart = args.count >= 7 ? Double(args[5]) : 0
    let requestedEnd = args.count >= 7 && args[6] != "end" ? Double(args[6]) : max(0, duration - 0.1)
    let useTiles = args.count >= 8 && args[7] == "tiles"
    var roi: [Double]? = nil
    if args.count == 12 {
        let values = args[8...11].compactMap(Double.init)
        guard values.count == 4, values.allSatisfy({ $0.isFinite }),
              values[0] >= 0, values[1] >= 0, values[2] > 0, values[3] > 0,
              values[0] + values[2] <= 1, values[1] + values[3] <= 1 else {
            throw NSError(domain: "ROI", code: 6)
        }
        roi = values
    }
    guard let start = rangeStart, let end = requestedEnd,
          start.isFinite, end.isFinite, start >= 0, end <= duration,
          start < min(end, max(0, duration - 0.1)) else {
        throw NSError(domain: "TimeRange", code: 4)
    }
    let last = min(end, max(0, duration - 0.1))
    let folder = URL(fileURLWithPath: args[2], isDirectory: true)
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    let generator = AVAssetImageGenerator(asset: asset)
    generator.appliesPreferredTrackTransform = true
    generator.maximumSize = CGSize(width: size, height: size)
    generator.requestedTimeToleranceBefore = .zero
    generator.requestedTimeToleranceAfter = .zero
    var frames: [[String: Any]] = []
    for index in 0..<count {
        let target = start + (last - start) * Double(index) / Double(count - 1)
        var actual = CMTime.zero
        let sourceImage = try generator.copyCGImage(at: CMTime(seconds: target, preferredTimescale: 60000), actualTime: &actual)
        var cgImage = sourceImage
        var contextName: String? = nil
        if let region = roi {
            let rect = CGRect(x: floor(region[0] * Double(sourceImage.width)),
                              y: floor(region[1] * Double(sourceImage.height)),
                              width: floor(region[2] * Double(sourceImage.width)),
                              height: floor(region[3] * Double(sourceImage.height)))
            guard let cropped = sourceImage.cropping(to: rect),
                  let context = NSBitmapImageRep(cgImage: sourceImage).representation(using: .jpeg, properties: [.compressionFactor: 0.95]) else {
                throw NSError(domain: "ROI", code: 7)
            }
            cgImage = cropped
            let contextFile = String(format: "context-%02d.jpg", index)
            try context.write(to: folder.appendingPathComponent(contextFile), options: .atomic)
            contextName = contextFile
        }
        let bitmap = NSBitmapImageRep(cgImage: cgImage)
        guard let jpeg = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.9]) else {
            throw NSError(domain: "JPEG", code: 3)
        }
        let name = String(format: "frame-%02d.jpg", index)
        try jpeg.write(to: folder.appendingPathComponent(name), options: .atomic)
        var views: [[String: Any]] = []
        if useTiles {
            // Four overlapping windows cover the entire image, without selecting
            // a region based on the expected event or sending it to another service.
            let width = cgImage.width, height = cgImage.height
            let tileWidth = Int(ceil(Double(width) * 0.6))
            let tileHeight = Int(ceil(Double(height) * 0.6))
            for (row, y) in [0, height - tileHeight].enumerated() {
                for (column, x) in [0, width - tileWidth].enumerated() {
                    let rect = CGRect(x: x, y: y, width: tileWidth, height: tileHeight)
                    guard let crop = cgImage.cropping(to: rect),
                          let data = NSBitmapImageRep(cgImage: crop).representation(using: .jpeg, properties: [.compressionFactor: 0.95]) else {
                        throw NSError(domain: "Crop", code: 5)
                    }
                    let tileName = String(format: "frame-%02d-tile-%d%d.jpg", index, row, column)
                    try data.write(to: folder.appendingPathComponent(tileName), options: .atomic)
                    views.append(["file": tileName, "crop_xywh_px": [x, y, tileWidth, tileHeight]])
                }
            }
        }
        var entry: [String: Any] = ["index": index, "timestamp_sec": CMTimeGetSeconds(actual), "file": name,
                       "width_px": cgImage.width, "height_px": cgImage.height, "detail_views": views]
        if let context = contextName, let region = roi {
            entry["context_file"] = context
            entry["roi_normalized"] = region
        }
        frames.append(entry)
    }
    let metadata: [String: Any] = ["duration_sec": duration, "frames": frames,
                                  "sampled_range_sec": ["start": start, "end": last]]
    let data = try JSONSerialization.data(withJSONObject: metadata, options: [.prettyPrinted, .sortedKeys])
    try data.write(to: folder.appendingPathComponent("frames.json"), options: .atomic)
    print("Extracted \(frames.count) frames; duration \(duration) seconds")
} catch {
    // Keep error descriptions out of the shared terminal; caller captures stderr locally.
    let nativeError = error as NSError
    fputs("Frame extraction failed (\(nativeError.domain), code \(nativeError.code))\n", stderr)
    exit(1)
}

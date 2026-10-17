export const VIDEO_FORMATS = "MOV, MP4, AVI, MKV и WEBM";

// The browser's MIME value may be empty or generic. The server validates the
// container and video stream with ffprobe before converting or analyzing it.
export const VIDEO_ACCEPT = [
  ".mov",
  ".mp4",
  ".avi",
  ".mkv",
  ".webm",
  "video/quicktime",
  "video/mp4",
  "video/x-msvideo",
  "video/avi",
  "video/msvideo",
  "video/x-matroska",
  "video/webm",
].join(",");

export function isSupportedVideoFilename(name: string) {
  return /\.(mov|mp4|avi|mkv|webm)$/i.test(name);
}

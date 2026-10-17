"""Tiny synthetic H.264/yuv420p files, including VFR and leading edits."""

from fractions import Fraction
from pathlib import Path
import av
import numpy as np


def normalized_mp4(
    path: Path, times_ms=(0, 100, 200, 900, 1000, 1600), *, rotation=0
) -> None:
    with av.open(str(path), mode="w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width, stream.height = 64, 32
        stream.pix_fmt = "yuv420p"
        stream.time_base = stream.codec_context.time_base = Fraction(1, 1000)
        stream.options = {"preset": "veryfast", "crf": "18", "bf": "0"}
        if rotation:
            stream.set_display_rotation(rotation)
        for index, timestamp in enumerate(times_ms):
            pixels = np.zeros((32, 64, 3), np.uint8)
            pixels[:, :32] = (index * 20, 20, 230)
            pixels[:, 32:] = (30, 180, index * 20)
            frame = av.VideoFrame.from_ndarray(pixels, format="bgr24")
            frame.pts, frame.time_base = timestamp, Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)

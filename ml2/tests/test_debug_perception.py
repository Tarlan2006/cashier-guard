"""Check reflection debug marks without inference or private video fixtures."""

from __future__ import annotations

import unittest

from PIL import Image, ImageDraw

from scripts.debug_perception import _dashed_rectangle, _reflection_reason


class DebugReflectionTests(unittest.TestCase):
    def test_dashed_outline_has_visible_gaps(self) -> None:
        image = Image.new("RGB", (50, 50), (0, 0, 0))
        _dashed_rectangle(
            ImageDraw.Draw(image), (2, 2, 46, 46), (255, 255, 255), width=1, dash=5
        )
        self.assertEqual(image.getpixel((4, 2)), (255, 255, 255))
        self.assertEqual(image.getpixel((10, 2)), (0, 0, 0))
        self.assertEqual(image.getpixel((2, 4)), (255, 255, 255))
        self.assertEqual(image.getpixel((2, 10)), (0, 0, 0))

    def test_reason_accepts_string_and_list_contracts(self) -> None:
        self.assertEqual(
            _reflection_reason({"reflection_reason": "mirror_motion"}), "mirror_motion"
        )
        self.assertEqual(
            _reflection_reason({"reflection_reasons": ["small", "low_confidence"]}),
            "small; low_confidence",
        )


if __name__ == "__main__":
    unittest.main()

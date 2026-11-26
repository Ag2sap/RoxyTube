"""Regression tests for refresh-aware YouTube format selection.

The selector helpers are extracted from app/main.py so CI does not need PySide6.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
TREE = ast.parse(APP_SOURCE)


def load_selector_helpers():
    wanted = {"display_fps_buckets", "quality_format_selector"}
    nodes = [
        node for node in TREE.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    if {node.name for node in nodes} != wanted:
        raise AssertionError("Adaptive selector helpers are missing")
    namespace = {}
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(module, str(ROOT / "app" / "main.py"), "exec"), namespace)
    return namespace


HELPERS = load_selector_helpers()
display_fps_buckets = HELPERS["display_fps_buckets"]
quality_format_selector = HELPERS["quality_format_selector"]


class DisplayFpsBucketTests(unittest.TestCase):
    def test_pal_display_prefers_50_then_25(self):
        self.assertEqual(display_fps_buckets(50.0), (50, 25))
        self.assertEqual(display_fps_buckets(49.9), (50, 25))

    def test_ntsc_display_prefers_60_then_30(self):
        self.assertEqual(display_fps_buckets(60.0), (60, 30))
        self.assertEqual(display_fps_buckets(59.94), (60, 30))

    def test_unknown_refresh_rate_does_not_force_a_frame_rate(self):
        self.assertEqual(display_fps_buckets(0), ())
        self.assertEqual(display_fps_buckets(75), ())


class AdaptiveFormatSelectorTests(unittest.TestCase):
    def test_50hz_selector_orders_50fps_then_25fps_then_avc_fallback(self):
        selector = quality_format_selector("Auto", 50)
        self.assertLess(selector.index("[fps>=49][fps<=51]"),
                        selector.index("[fps>=24][fps<=26]"))
        self.assertTrue(selector.endswith("(bv*[vcodec^=avc1]+ba/b[vcodec^=avc1])"))

    def test_60hz_selector_orders_60fps_then_30fps_then_avc_fallback(self):
        selector = quality_format_selector("Auto", 60)
        self.assertLess(selector.index("[fps>=59][fps<=61]"),
                        selector.index("[fps>=29][fps<=31]"))

    def test_manual_quality_cap_is_preserved_for_all_fallbacks(self):
        selector = quality_format_selector("720p", 50)
        self.assertEqual(selector.count("[height<=720]"), 6)
        self.assertNotIn("[height<=1080]", selector)

    def test_auto_does_not_add_a_hard_resolution_cap(self):
        selector = quality_format_selector("Auto", 50)
        self.assertNotIn("[height<=", selector)

    def test_unknown_display_rate_keeps_the_avc_baseline(self):
        self.assertEqual(
            quality_format_selector("Auto", 0),
            "bv*[vcodec^=avc1]+ba/b[vcodec^=avc1]",
        )

    def test_app_defaults_to_auto_and_uses_detected_display_rate(self):
        self.assertIn('self.quality.setCurrentText("Auto")', APP_SOURCE)
        self.assertIn("display_refresh_rate = detect_display_refresh_rate()", APP_SOURCE)
        self.assertIn("quality_format_selector(self.quality.currentText(), display_refresh_rate)", APP_SOURCE)
        self.assertIn('os.environ.get("ROXY_DISPLAY_FPS")', APP_SOURCE)


if __name__ == "__main__":
    unittest.main()

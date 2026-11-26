"""Static regression tests for RoxyTube's windowed MPV contract.

These tests intentionally avoid importing PySide6 so they can run in lightweight CI.
They protect the application boundary; hardware decoding still requires device tests.
"""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
RUN_SOURCE = (ROOT / "scripts" / "run.sh").read_text(encoding="utf-8")


def method_source(source: str, method_name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
            segment = ast.get_source_segment(source, node)
            if segment:
                return segment
    raise AssertionError(f"Method {method_name!r} was not found")


class PlaybackContractTests(unittest.TestCase):
    def test_mpv_is_embedded_in_qt_child_window(self):
        launch = method_source(APP_SOURCE, "_launch_player")
        self.assertIn("--wid=", launch)
        self.assertIn("--vo={MPV_VO}", launch)
        self.assertIn("--gpu-context={MPV_GPU_CONTEXT}", launch)
        self.assertIn("--gpu-api={MPV_GPU_API}", launch)
        self.assertIn("--input-ipc-server=", launch)

    def test_mpv_does_not_take_over_fullscreen_or_remote_input(self):
        launch = method_source(APP_SOURCE, "_launch_player")
        self.assertNotIn("--vo=drm", launch)
        self.assertNotIn("--gpu-context=drm", launch)
        self.assertNotIn("--fullscreen", launch)
        self.assertNotIn("--fs", launch)
        self.assertIn("--input-vo-keyboard=no", launch)
        self.assertIn("--input-default-bindings=no", launch)

    def test_app_local_ytdlp_is_preferred_and_passed_to_mpv(self):
        resolver = method_source(APP_SOURCE, "resolve_ytdlp")
        environment = method_source(APP_SOURCE, "mpv_process_environment")
        self.assertIn("APP_YTDLP.is_file()", resolver)
        self.assertIn("shutil.which", resolver)
        self.assertIn("PATH", environment)
        self.assertIn("YTDLP", environment)

    def test_drmprime_runtime_remains_explicitly_opt_in(self):
        self.assertIn('ROXY_ENABLE_DRMPRIME:-0', RUN_SOURCE)
        self.assertIn('ROXY_MPV_HWDEC:-v4l2m2m', RUN_SOURCE)
        self.assertIn('ROXY_MPV_GPU_HWDEC_INTEROP:-drmprime', RUN_SOURCE)
        self.assertIn('ROXY_MPV_VO:-gpu', RUN_SOURCE)
        self.assertIn('ROXY_MPV_GPU_CONTEXT:-x11egl', RUN_SOURCE)
        self.assertIn('ROXY_MPV_GPU_API:-opengl', RUN_SOURCE)

    def test_safe_area_config_remains_owned_by_qt_window(self):
        margins = method_source(APP_SOURCE, "safe_area_margins")
        self.assertIn("SAFE_AREA_FILE", margins)
        self.assertIn("margin_left", margins)
        self.assertIn("margin_right", margins)


if __name__ == "__main__":
    unittest.main()

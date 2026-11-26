"""Static regression tests for RoxyTube's Channel and embedded playback contracts.

These tests intentionally avoid importing PySide6 so lightweight CI can run them.
Hardware decoding and YouTube extraction still require validation on the HG680P.
"""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
RUN_SOURCE = (ROOT / "scripts" / "run.sh").read_text(encoding="utf-8")


def function_source(source: str, function_name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            segment = ast.get_source_segment(source, node)
            if segment:
                return segment
    raise AssertionError(f"Function {function_name!r} was not found")


class ChannelRegressionTests(unittest.TestCase):
    def test_channel_metadata_helpers_are_preserved(self):
        for name in ("format_subscriber_count", "channel_avatar_url", "channel_page_url"):
            self.assertIn(f"def {name}(", APP_SOURCE)

    def test_channel_search_and_channel_page_remain_present(self):
        self.assertIn('("Channel", "channels"', APP_SOURCE)
        self.assertIn('self.search_kind = "channels"', APP_SOURCE)
        self.assertIn("def render_channel_page(", APP_SOURCE)
        self.assertIn("def open_current_channel(", APP_SOURCE)


class YtDlpIsolationTests(unittest.TestCase):
    def test_app_local_binary_is_preferred_after_explicit_override(self):
        resolver = function_source(APP_SOURCE, "resolve_ytdlp")
        self.assertIn('os.environ.get("ROXY_YT_DLP")', resolver)
        self.assertIn("APP_YTDLP.is_file()", resolver)
        self.assertIn("shutil.which", resolver)

    def test_direct_yt_dlp_calls_ignore_global_config(self):
        helper = function_source(APP_SOURCE, "ytdlp_arguments")
        self.assertIn('"--ignore-config"', helper)
        self.assertIn("APP_YTDLP_CONFIG", helper)
        self.assertIn("APP_DENO.is_file()", helper)
        self.assertIn("--js-runtimes", helper)
        self.assertEqual(APP_SOURCE.count("process.setProgram(YTDLP)"), 4)
        self.assertEqual(APP_SOURCE.count("process.setArguments(ytdlp_arguments("), 4)

    def test_mpv_ytdl_hook_uses_isolated_config_policy(self):
        raw_options = function_source(APP_SOURCE, "mpv_ytdl_raw_options")
        environment = function_source(APP_SOURCE, "mpv_process_environment")
        self.assertIn('"ignore-config="', raw_options)
        self.assertIn("APP_YTDLP_CONFIG", raw_options)
        self.assertIn("PATH", environment)
        self.assertIn("YTDLP", environment)
        self.assertIn("APP_DENO", environment)
        self.assertIn("DENO_DIR", environment)


class PlaybackContractTests(unittest.TestCase):
    def test_mpv_is_embedded_in_qt_child_window(self):
        launch = function_source(APP_SOURCE, "_launch_player")
        self.assertIn("--wid=", launch)
        self.assertIn("--vo={MPV_VO}", launch)
        self.assertIn("--gpu-context={MPV_GPU_CONTEXT}", launch)
        self.assertIn("--gpu-api={MPV_GPU_API}", launch)
        self.assertIn("--input-ipc-server=", launch)
        self.assertIn("setProcessEnvironment(mpv_process_environment())", launch)

    def test_mpv_does_not_take_over_fullscreen_or_remote_input(self):
        launch = function_source(APP_SOURCE, "_launch_player")
        self.assertNotIn("--vo=drm", launch)
        self.assertNotIn("--gpu-context=drm", launch)
        self.assertNotIn("--fullscreen", launch)
        self.assertNotIn('"--fs"', launch)
        self.assertIn("--input-vo-keyboard=no", launch)
        self.assertIn("--input-default-bindings=no", launch)

    def test_quality_options_include_1080p(self):
        self.assertIn('"1080p": "bv*[vcodec^=avc1][height<=1080]+ba/b[vcodec^=avc1][height<=1080]"', APP_SOURCE)
        fallback = function_source(APP_SOURCE, "quality_fallbacks")
        self.assertIn('if quality == "1080p"', fallback)

    def test_decoder_fallback_precedes_quality_fallback(self):
        retry = function_source(APP_SOURCE, "retry_lower_quality")
        self.assertLess(retry.index("if self.decoder_fallbacks"), retry.index("elif self.fallback_qualities"))
        self.assertIn("self.current_hwdec = next_decoder", retry)

    def test_drmprime_runtime_is_opt_in_and_has_copy_software_fallbacks(self):
        self.assertIn('ROXY_ENABLE_DRMPRIME:-0', RUN_SOURCE)
        self.assertIn('ROXY_MPV_HWDEC:-v4l2m2m', RUN_SOURCE)
        self.assertIn('ROXY_MPV_HWDEC_FALLBACKS:-v4l2m2m-copy,no', RUN_SOURCE)
        self.assertIn('ROXY_MPV_GPU_HWDEC_INTEROP:-drmprime', RUN_SOURCE)
        self.assertIn('ROXY_MPV_VO:-gpu', RUN_SOURCE)
        self.assertIn('ROXY_MPV_GPU_CONTEXT:-x11egl', RUN_SOURCE)
        self.assertIn('ROXY_MPV_GPU_API:-opengl', RUN_SOURCE)

    def test_safe_area_uses_resolution_specific_pixel_profiles(self):
        margins = function_source(APP_SOURCE, "safe_area_pixel_margins")
        self.assertIn("WINDOW_SAFE_AREA_FILE", margins)
        self.assertIn('"720x576"', margins)
        self.assertIn('"left": 45', margins)
        self.assertIn('"right": 45', margins)
        self.assertIn('"top": 10', margins)
        self.assertIn('"bottom": 10', margins)
        self.assertNotIn("safe_area_margins()", APP_SOURCE)

    def test_safe_area_changes_outer_window_geometry_not_inner_padding(self):
        geometry = function_source(APP_SOURCE, "apply_safe_window_geometry")
        apply = function_source(APP_SOURCE, "apply_safe_area")
        self.assertIn("self.setGeometry(self._safe_window_geometry)", geometry)
        self.assertIn("self.root_layout.setContentsMargins(0, 0, 0, 0)", apply)

    def test_playback_immersive_mode_does_not_request_os_fullscreen(self):
        enter = function_source(APP_SOURCE, "toggle_playback_fullscreen")
        leave = function_source(APP_SOURCE, "exit_playback_fullscreen")
        self.assertNotIn("showFullScreen", enter + leave)
        self.assertNotIn("setWindowState", enter + leave)
        self.assertNotIn("showMaximized", enter + leave)

    def test_safe_area_settings_save_resolution_specific_pixel_values(self):
        saver = function_source(APP_SOURCE, "save_safe_area_pixel_profile")
        apply = function_source(APP_SOURCE, "save_safe_area_settings")
        self.assertIn("WINDOW_SAFE_AREA_FILE", saver)
        self.assertIn("profiles[resolution] = values", saver)
        self.assertIn("temporary.replace(WINDOW_SAFE_AREA_FILE)", saver)
        self.assertIn("safe_area_spinboxes", apply)
        self.assertIn("apply_safe_window_geometry", apply)

    def test_application_no_longer_requests_os_fullscreen_or_maximize(self):
        self.assertNotIn("showFullScreen(", APP_SOURCE)
        self.assertNotIn("showMaximized(", APP_SOURCE)
        self.assertNotIn("WindowFullScreen", function_source(APP_SOURCE, "toggle_playback_fullscreen"))


if __name__ == "__main__":
    unittest.main()

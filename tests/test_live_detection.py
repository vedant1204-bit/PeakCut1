"""Live-creator checks using simulated platform responses, no internet required.

Run with: python -m unittest tests.test_live_detection
"""
import unittest
from unittest.mock import patch

from studio import profiles
from studio.live import normalize


class LiveDetectionTests(unittest.TestCase):
    def test_youtube_channel_normalization(self):
        self.assertEqual(normalize("https://www.youtube.com/@example/streams"),
                         "https://www.youtube.com/@example/live")
        self.assertEqual(normalize("https://www.youtube.com/@example/live"),
                         "https://www.youtube.com/@example/live")

    def test_youtube_falls_back_to_extractor(self):
        with patch.object(profiles, "_get", return_value=("text/html", b"<html>no old marker</html>")), \
             patch.object(profiles, "_ydl_info", return_value={
                 "live_status": "is_live", "id": "Abcdefghijk", "title": "Live gaming"
             }):
            out = profiles.live_now("YouTube", "https://www.youtube.com/@example")
        self.assertTrue(out["live"])
        self.assertEqual(out["embed"], "Abcdefghijk")

    def test_youtube_offline_is_not_live(self):
        with patch.object(profiles, "_get", return_value=("text/html", b"<html></html>")), \
             patch.object(profiles, "_ydl_info", return_value={"live_status": "not_live"}):
            self.assertFalse(profiles.live_now("YouTube", "https://www.youtube.com/@example")["live"])

    def test_youtube_whitespace_marker(self):
        html = b'<html>"isLiveNow" : true</html>'
        with patch.object(profiles, "_get", return_value=("text/html", html)), \
             patch.object(profiles, "_ydl_info", side_effect=RuntimeError("extractor blocked")):
            self.assertTrue(profiles.live_now("YouTube", "https://www.youtube.com/@example")["live"])

    def test_failed_lookups_are_not_reported_as_offline(self):
        profiles._live.clear()
        with patch.object(profiles, "live_now", side_effect=RuntimeError("blocked")):
            result = profiles.live_shared("YouTube", "https://www.youtube.com/@example")
        self.assertTrue(result.get("check_error"))
        self.assertFalse(result["live"])

    def test_kick_fallback_to_extractor(self):
        with patch.object(profiles, "_get", side_effect=OSError("blocked")), \
             patch.object(profiles, "_ydl_info", return_value={"is_live": True, "title": "Gaming"}):
            result = profiles.live_now("Kick", "https://kick.com/example")
        self.assertTrue(result["live"])
        self.assertEqual(result["embed"], "example")


if __name__ == "__main__":
    unittest.main()

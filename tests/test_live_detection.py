"""Live-creator checks using simulated platform responses, no internet required.

Run with: python -m unittest tests.test_live_detection
"""
import unittest
from unittest.mock import patch

from studio import profiles, live
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

    def test_twitch_failed_apis_are_unknown_not_offline(self):
        profiles._live.clear()
        with patch.object(profiles, "_twitch_live", side_effect=OSError("blocked")), \
             patch.object(profiles, "_ydl_info", side_effect=OSError("blocked")):
            result = profiles.live_shared("Twitch", "https://www.twitch.tv/example")
        self.assertTrue(result.get("check_error"))

    def test_auto_record_tries_resolving_uncertain_stream(self):
        creator = {"id": "example", "name": "Example", "channel": "https://www.twitch.tv/example",
                   "channels": {"twitch": "https://www.twitch.tv/example"}}
        with patch.object(live, "active_for", return_value=None), \
             patch.object(live, "active_mine", return_value=[]), \
             patch.object(live, "active", return_value=[]), \
             patch.object(profiles, "live_shared", return_value={"live": False, "check_error": True}), \
             patch.object(live, "resolve", return_value={"urls": ["https://example.com/live"]}) as resolve, \
             patch.object(live, "start_session") as start_session, \
             patch.object(live.creators, "log"), \
             patch.object(live.alerts, "notify"):
            live._watch_one(creator)
        resolve.assert_called_once()
        start_session.assert_called_once_with(creator, creator["channel"])

    def test_offline_creator_does_not_start(self):
        creator = {"id": "example", "name": "Example", "channel": "https://www.twitch.tv/example",
                   "channels": {"twitch": "https://www.twitch.tv/example"}}
        with patch.object(live, "active_for", return_value=None), \
             patch.object(live, "active_mine", return_value=[]), \
             patch.object(live, "active", return_value=[]), \
             patch.object(profiles, "live_shared", return_value={"live": False}), \
             patch.object(live, "resolve") as resolve, \
             patch.object(live, "start_session") as start_session:
            live._watch_one(creator)
        resolve.assert_not_called()
        start_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()

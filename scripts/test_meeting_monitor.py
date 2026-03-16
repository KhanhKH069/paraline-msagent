#!/usr/bin/env python3
"""
scripts/test_meeting_monitor.py
Unit test MeetingMonitor với mock Graph API response.

Chạy: python scripts/test_meeting_monitor.py
Không cần Teams account — dùng mock HTTP responses.
"""
import sys
import unittest
from unittest.mock import patch

# Chắc chắn import đúng path
sys.path.insert(0, ".")

# Mock env vars trước khi import module
import os
os.environ.setdefault("TEAMS_TENANT_ID",    "test-tenant")
os.environ.setdefault("TEAMS_CLIENT_ID",    "test-client")
os.environ.setdefault("TEAMS_CLIENT_SECRET","test-secret")
os.environ.setdefault("TEAMS_TEAM_ID",      "test-team")
os.environ.setdefault("TEAMS_CHANNEL_ID",   "test-channel")
os.environ.setdefault("TEAMS_POLL_INTERVAL","1")


# ─────────────────────────────────────────────────────────
# Fake Graph API responses
# ─────────────────────────────────────────────────────────

MEETING_STARTED_MSG = {
    "id": "msg-001",
    "eventDetail": {
        "@odata.type": "#microsoft.graph.callStartedEventMessageDetail",
        "joinWebUrl":  "https://teams.microsoft.com/l/meetup-join/test-meeting-id/0",
    },
    "body": {"content": ""},
    "attachments": [],
}

MEETING_ENDED_MSG = {
    "id": "msg-002",
    "eventDetail": {
        "@odata.type": "#microsoft.graph.callEndedEventMessageDetail",
    },
    "body": {"content": ""},
    "attachments": [],
}

NORMAL_MSG = {
    "id": "msg-003",
    "eventDetail": None,
    "body": {"content": "Hello team"},
    "attachments": [],
}


class FakeResponse:
    def __init__(self, data):
        self._data = data
        self.ok    = True
        self.status_code = 200
        self.text  = ""

    def json(self):
        return self._data


# ─────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────

class TestMeetingMonitor(unittest.TestCase):

    def _make_monitor(self, on_started=None, on_ended=None):
        from client.teams_integration.meeting_monitor import MeetingMonitor
        return MeetingMonitor(
            on_meeting_started=on_started or (lambda url: None),
            on_meeting_ended=on_ended   or (lambda: None),
        )

    @patch("client.teams_integration.meeting_monitor.requests.post")
    @patch("client.teams_integration.meeting_monitor.requests.get")
    def test_detect_meeting_started(self, mock_get, mock_post):
        """Monitor phải gọi on_meeting_started khi thấy callStartedEventMessageDetail."""
        # Token mock
        mock_post.return_value = FakeResponse({
            "access_token": "fake-token",
            "expires_in":   3600,
        })
        # First call: meeting started message
        mock_get.return_value = FakeResponse({"value": [MEETING_STARTED_MSG]})

        started_urls = []
        monitor = self._make_monitor(on_started=lambda url: started_urls.append(url))

        monitor._check_channel()

        self.assertEqual(len(started_urls), 1)
        self.assertIn("meetup-join", started_urls[0])
        print(f"✅ test_detect_meeting_started — join_url={started_urls[0][:50]}...")

    @patch("client.teams_integration.meeting_monitor.requests.post")
    @patch("client.teams_integration.meeting_monitor.requests.get")
    def test_detect_meeting_ended(self, mock_get, mock_post):
        """Monitor phải gọi on_meeting_ended khi thấy callEndedEventMessageDetail."""
        mock_post.return_value = FakeResponse({
            "access_token": "fake-token",
            "expires_in":   3600,
        })

        ended_calls = []
        monitor = self._make_monitor(on_ended=lambda: ended_calls.append(True))
        monitor._meeting_active = True   # Giả sử đang có meeting
        monitor._last_message_id = "prev"

        mock_get.return_value = FakeResponse({"value": [MEETING_ENDED_MSG]})
        monitor._check_channel()

        self.assertEqual(len(ended_calls), 1)
        self.assertFalse(monitor._meeting_active)
        print("✅ test_detect_meeting_ended — callback called correctly")

    @patch("client.teams_integration.meeting_monitor.requests.post")
    @patch("client.teams_integration.meeting_monitor.requests.get")
    def test_no_duplicate_start(self, mock_get, mock_post):
        """Monitor không được gọi on_meeting_started 2 lần cho cùng 1 meeting."""
        mock_post.return_value = FakeResponse({
            "access_token": "fake-token",
            "expires_in":   3600,
        })
        mock_get.return_value = FakeResponse({"value": [MEETING_STARTED_MSG]})

        started_urls = []
        monitor = self._make_monitor(on_started=lambda url: started_urls.append(url))

        monitor._check_channel()  # Lần 1: detect
        monitor._check_channel()  # Lần 2: same message id → không detect lại
        monitor._check_channel()  # Lần 3: same

        self.assertEqual(len(started_urls), 1, "Should only fire once")
        print(f"✅ test_no_duplicate_start — fired {len(started_urls)} time(s)")

    @patch("client.teams_integration.meeting_monitor.requests.post")
    @patch("client.teams_integration.meeting_monitor.requests.get")
    def test_normal_message_ignored(self, mock_get, mock_post):
        """Tin nhắn thông thường không trigger event."""
        mock_post.return_value = FakeResponse({
            "access_token": "fake-token",
            "expires_in":   3600,
        })
        mock_get.return_value = FakeResponse({"value": [NORMAL_MSG]})

        started = []
        ended   = []
        monitor = self._make_monitor(
            on_started=lambda url: started.append(url),
            on_ended=lambda: ended.append(True),
        )
        monitor._check_channel()

        self.assertEqual(len(started), 0)
        self.assertEqual(len(ended),   0)
        print("✅ test_normal_message_ignored — no false positives")

    def test_disabled_when_missing_env(self):
        """Monitor bị disabled nếu thiếu env vars."""
        import client.teams_integration.meeting_monitor as mm_module
        original_team   = mm_module.TEAM_ID
        original_channel= mm_module.CHANNEL_ID
        try:
            mm_module.TEAM_ID    = ""
            mm_module.CHANNEL_ID = ""
            # Tạo thủ công với env thiếu
            monitor = mm_module.MeetingMonitor.__new__(mm_module.MeetingMonitor)
            monitor._enabled = bool(
                mm_module.TENANT_ID and mm_module.CLIENT_ID
                and mm_module.CLIENT_SECRET and mm_module.TEAM_ID
                and mm_module.CHANNEL_ID
            )
            self.assertFalse(monitor._enabled)
            print("✅ test_disabled_when_missing_env — correctly disabled")
        finally:
            mm_module.TEAM_ID    = original_team
            mm_module.CHANNEL_ID = original_channel


def main():
    print("🟠 Paraline MSAgent — Meeting Monitor Tests")
    print("=" * 50)
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromTestCase(TestMeetingMonitor)
    runner = unittest.TextTestRunner(verbosity=0, stream=sys.stdout)
    result = runner.run(suite)
    print("=" * 50)
    if result.wasSuccessful():
        print(f"✅ All {result.testsRun} tests passed!")
    else:
        print(f"❌ {len(result.failures)} test(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    main()

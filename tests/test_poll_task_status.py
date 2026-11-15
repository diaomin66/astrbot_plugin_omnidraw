"""Issue #72 regressions: async_task polling must read the task status
inside the ``data`` object, as docs/async-video-tasks.md promises.

Previously ``_poll_task_result`` only read the top-level ``status`` /
``task_status``, so relays that nest the real status under ``data``
polled with an empty status until the timeout fired.
"""

import asyncio
import types
import unittest

import test_custom_endpoint as fixtures


VideoManager = fixtures.VideoManager
VideoTaskError = fixtures.VideoTaskError

REPORTER_PAYLOAD = {
    "code": "success",
    "data": {
        "status": "SUCCESS",
        "progress": "100%",
        "result_url": "https://cdn.example/v1/videos/task_1/content",
        "data": {"status": "completed", "url": "https://cdn.example/v1/media/abc.mp4"},
    },
}


def make_manager():
    return VideoManager(types.SimpleNamespace())


class ExtractTaskStatusTest(unittest.TestCase):
    def setUp(self):
        self.manager = make_manager()

    def status(self, payload):
        return self.manager._extract_task_status(payload)

    def test_reporter_payload_reads_data_object_status(self):
        self.assertEqual(self.status(REPORTER_PAYLOAD), "SUCCESS")

    def test_data_object_field_variants(self):
        self.assertEqual(self.status({"data": {"task_status": "running"}}), "RUNNING")
        self.assertEqual(self.status({"data": {"state": "queued"}}), "QUEUED")
        self.assertEqual(self.status({"data": {"status": " failed "}}), "FAILED")

    def test_data_object_wins_over_top_level(self):
        payload = {"status": "FAILED", "data": {"status": "SUCCESS"}}
        self.assertEqual(self.status(payload), "SUCCESS")

    def test_data_list_first_item(self):
        payload = {"data": [{"status": "submitted", "task_id": "t1"}]}
        self.assertEqual(self.status(payload), "SUBMITTED")

    def test_top_level_fallback_unchanged(self):
        self.assertEqual(self.status({"status": "SUCCESS"}), "SUCCESS")
        self.assertEqual(self.status({"task_status": "processing"}), "PROCESSING")
        self.assertEqual(self.status({"state": "completed"}), "COMPLETED")

    def test_top_level_envelope_values_are_not_statuses(self):
        for envelope in ("ok", "OK", "true", "True", "false", True, False):
            with self.subTest(envelope=envelope):
                self.assertEqual(self.status({"status": envelope}), "")

    def test_envelope_top_level_does_not_shadow_data_status(self):
        payload = {"status": "ok", "data": {"status": "RUNNING"}}
        self.assertEqual(self.status(payload), "RUNNING")
        payload = {"status": "success", "data": {"status": "FAILED"}}
        self.assertEqual(self.status(payload), "FAILED")

    def test_full_field_by_location_matrix(self):
        # docs/async-video-tasks.md promises status / task_status / state at
        # the top level, in a data object, or in a data list.
        for field in ("status", "task_status", "state"):
            for wrap in ("top", "data_dict", "data_list"):
                payload = {}
                inner = {field: "succeeded"}
                if wrap == "top":
                    payload = inner
                elif wrap == "data_dict":
                    payload = {"data": inner}
                else:
                    payload = {"data": [inner]}
                with self.subTest(field=field, wrap=wrap):
                    self.assertEqual(self.status(payload), "SUCCEEDED")

    def test_field_priority_within_one_object(self):
        payload = {"data": {"state": "queued", "task_status": "running", "status": "pending"}}
        self.assertEqual(self.status(payload), "PENDING")
        payload = {"data": {"state": "queued", "task_status": "running"}}
        self.assertEqual(self.status(payload), "RUNNING")

    def test_missing_or_malformed_status_is_empty(self):
        self.assertEqual(self.status({}), "")
        self.assertEqual(self.status({"data": {}}), "")
        self.assertEqual(self.status({"data": []}), "")
        self.assertEqual(self.status({"data": {"status": None}}), "")
        self.assertEqual(self.status({"data": {"status": {"x": 1}}}), "")
        self.assertEqual(self.status({"data": "SUCCESS"}), "")


class ExtractVideoUrlTest(unittest.TestCase):
    def setUp(self):
        self.manager = make_manager()

    def test_existing_shapes_still_work(self):
        self.assertEqual(
            self.manager._extract_video_url({"url": "https://a.example/v.mp4"}),
            "https://a.example/v.mp4",
        )
        self.assertEqual(
            self.manager._extract_video_url({"data": [{"url": "https://a.example/l.mp4"}]}),
            "https://a.example/l.mp4",
        )
        self.assertEqual(
            self.manager._extract_video_url({"data": {"output": "https://a.example/o.mp4"}}),
            "https://a.example/o.mp4",
        )

    def test_result_url_fallbacks(self):
        self.assertEqual(
            self.manager._extract_video_url(REPORTER_PAYLOAD),
            "https://cdn.example/v1/videos/task_1/content",
        )
        self.assertEqual(
            self.manager._extract_video_url({"result_url": "https://a.example/r.mp4"}),
            "https://a.example/r.mp4",
        )
        # Existing keys keep priority over result_url.
        payload = {"data": {"url": "https://a.example/u.mp4", "result_url": "https://a.example/r.mp4"}}
        self.assertEqual(self.manager._extract_video_url(payload), "https://a.example/u.mp4")


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, payload):
        self._payload = payload

    def get(self, url, headers=None, timeout=None):
        return FakeResponse(self._payload)


class PollTaskResultTest(unittest.TestCase):
    def poll(self, payload, timeout=1):
        manager = make_manager()
        provider = types.SimpleNamespace(
            base_url="https://relay.example", timeout=timeout, id="video-1"
        )
        return asyncio.run(
            manager._poll_task_result(provider, "task_1", FakeSession(payload), api_key="k")
        )

    def test_reporter_payload_completes_with_result_url(self):
        self.assertEqual(
            self.poll(REPORTER_PAYLOAD),
            "https://cdn.example/v1/videos/task_1/content",
        )

    def test_top_level_success_still_completes(self):
        payload = {"status": "COMPLETED", "url": "https://a.example/v.mp4"}
        self.assertEqual(self.poll(payload), "https://a.example/v.mp4")

    def test_data_object_failure_raises_platform_error(self):
        payload = {"status": "success", "data": {"status": "FAILED"}}
        with self.assertRaises(VideoTaskError):
            self.poll(payload)

    def test_running_status_in_data_object_times_out(self):
        payload = {"data": {"status": "RUNNING"}}
        with self.assertRaises(VideoTaskError) as ctx:
            self.poll(payload, timeout=1)
        self.assertIn("轮询超时", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

import time
import unittest
from backend.pipeline.resident import ResidentRuntime
from backend.pipeline.perception import PerceptionConfig


def fixture_worker(config, incoming, outgoing):
    outgoing.put(("ready", None, dict(detector_loads=1, vision_encoder_loads=1)))
    count = 0
    while request := incoming.get():
        identifier, path, started = request
        if path == "hang":
            time.sleep(30)
        count += 1
        outgoing.put(
            (
                "done",
                identifier,
                dict(
                    perception_complete=True,
                    error_type=None,
                    warnings=[],
                    timing=dict(request_number=count),
                ),
            )
        )


class ResidentTests(unittest.TestCase):
    def test_two_requests_share_one_loaded_worker(self):
        runtime = ResidentRuntime(PerceptionConfig(), worker=fixture_worker)
        runtime.start()
        self.addCleanup(runtime.close)
        pid = runtime.process.pid
        first, second = runtime.analyze("first"), runtime.analyze("second")
        self.assertEqual(first["timing"]["request_number"], 1)
        self.assertEqual(second["timing"]["request_number"], 2)
        self.assertEqual(runtime.model_loads["detector_loads"], 1)
        self.assertEqual(runtime.process.pid, pid)

    def test_unresponsive_request_returns_error_within_outer_budget(self):
        runtime = ResidentRuntime(
            PerceptionConfig(adaptive_after_sec=1, stop_after_sec=3, api_timeout_sec=4),
            worker=fixture_worker,
        )
        runtime.start()
        self.addCleanup(runtime.close)
        started = time.perf_counter()
        result = runtime.analyze("hang")
        self.assertLess(time.perf_counter() - started, 4)
        self.assertFalse(result["perception_complete"])
        self.assertEqual(result["error_type"], "TimeoutError")
        self.assertFalse(runtime.ready)

"""端到端 HTTP 测试：真实起服务线程，走 socket 打请求。"""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app.components import registry
from app.server import AuditHandler, build_server


def _wait_closed(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


class ApiTest(unittest.TestCase):
    def setUp(self):
        registry.start_all()
        self.server = build_server("127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        _wait_closed(self.server)
        self.thread.join(timeout=5)

    def _request(self, method: str, path: str, body=None, raw=None, headers=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = None
        hdrs = headers or {}
        if raw is not None:
            data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs = {"Content-Type": "application/json", **hdrs}
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_acceptance_area10_perimeter14(self):
        status, payload = self._request(
            "POST",
            "/api/audit",
            [
                {"id": "a", "x1": 0, "y1": 0, "x2": 3, "y2": 2},
                {"id": "b", "x1": 1, "y1": 1, "x2": 4, "y2": 3},
            ],
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"area": "10", "perimeter": "14"})

    def test_adjacent_and_geometric_duplicate(self):
        status, payload = self._request(
            "POST",
            "/api/audit",
            [
                {"id": "a", "x1": 0, "y1": 0, "x2": 2, "y2": 3},
                {"id": "b", "x1": 2, "y1": 0, "x2": 4, "y2": 3},
            ],
        )
        self.assertEqual((status, payload), (200, {"area": "12", "perimeter": "14"}))

        status, payload = self._request(
            "POST",
            "/api/audit",
            [
                {"id": "a", "x1": 0, "y1": 0, "x2": 2, "y2": 3},
                {"id": "b", "x1": 0, "y1": 0, "x2": 2, "y2": 3},
            ],
        )
        self.assertEqual((status, payload), (200, {"area": "6", "perimeter": "10"}))

    def test_duplicate_id_rejected_with_location(self):
        status, payload = self._request(
            "POST",
            "/api/audit",
            [
                {"id": "x", "x1": 0, "y1": 0, "x2": 1, "y2": 1},
                {"id": "x", "x1": 2, "y1": 2, "x2": 3, "y2": 3},
            ],
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_rectangle")
        self.assertEqual(payload["error"]["location"], {"index": 1, "id": "x"})
        self.assertNotIn("area", payload)
        self.assertNotIn("perimeter", payload)

    def test_invalid_rectangle_400_no_partial_result(self):
        status, payload = self._request(
            "POST",
            "/api/audit",
            [
                {"id": "a", "x1": 0, "y1": 0, "x2": 4, "y2": 4},
                {"id": "b", "x1": 9, "y1": 9, "x2": 9, "y2": 9},
            ],
        )
        self.assertEqual(status, 400)
        self.assertNotIn("area", payload)
        self.assertEqual(payload["error"]["location"]["index"], 1)

    def test_invalid_json(self):
        status, payload = self._request("POST", "/api/audit", raw="{not json")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_json")

    def test_wrapped_payload_supported(self):
        status, payload = self._request(
            "POST",
            "/api/audit",
            {"rectangles": [{"id": "a", "x1": 0, "y1": 0, "x2": 1, "y2": 1}]},
        )
        self.assertEqual((status, payload), (200, {"area": "1", "perimeter": "4"}))

    def test_health_ok_when_components_ready(self):
        status, payload = self._request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(all(c["ready"] for c in payload["components"].values()))

    def test_health_reflects_component_failure(self):
        # 模拟一个组件自检失败：健康检查必须 503。
        from app.components import Component

        saved = registry.scan_engine
        try:
            def boom():
                raise RuntimeError("simulated engine failure")

            registry.scan_engine = Component("scan-engine", boom)
            registry.scan_engine.start()
            status, payload = self._request("GET", "/healthz")
            self.assertEqual(status, 503)
            self.assertEqual(payload["status"], "not_ready")
            self.assertFalse(
                payload["components"]["scan-engine"]["ready"]
            )
        finally:
            registry.scan_engine = saved

    def test_audit_503_when_not_ready(self):
        from app.components import Component

        saved = registry.validator
        try:
            def boom():
                raise RuntimeError("simulated validator failure")

            registry.validator = Component("request-validator", boom)
            registry.validator.start()
            status, payload = self._request(
                "POST",
                "/api/audit",
                [{"id": "a", "x1": 0, "y1": 0, "x2": 1, "y2": 1}],
            )
            self.assertEqual(status, 503)
            self.assertEqual(payload["error"]["code"], "not_ready")
        finally:
            registry.validator = saved

    def test_unknown_route_404(self):
        status, _ = self._request("GET", "/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()

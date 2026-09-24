"""请求校验测试：非法矩形给出带输入位置的稳定错误，且无部分结果。"""

import unittest

from app.geometry import GeometryError, audit_raw


def must_fail(records):
    try:
        audit_raw(records)
    except GeometryError as exc:
        return exc
    raise AssertionError("expected GeometryError")


class ValidationTest(unittest.TestCase):
    def test_accepts_valid_and_returns_decimal_strings(self):
        area, perimeter = audit_raw(
            [{"id": "a", "x1": 0, "y1": 0, "x2": 3, "y2": 2}]
        )
        self.assertIsInstance(area, str)
        self.assertIsInstance(perimeter, str)
        self.assertEqual((area, perimeter), ("6", "10"))

    def test_rejects_duplicate_id_with_position(self):
        exc = must_fail(
            [
                {"id": "x", "x1": 0, "y1": 0, "x2": 1, "y2": 1},
                {"id": "x", "x1": 2, "y1": 2, "x2": 3, "y2": 3},
            ]
        )
        self.assertEqual(exc.location, {"index": 1, "id": "x"})
        self.assertIn("duplicate id", str(exc))

    def test_geometric_duplicates_with_distinct_ids_allowed(self):
        area, perimeter = audit_raw(
            [
                {"id": "a", "x1": 0, "y1": 0, "x2": 2, "y2": 3},
                {"id": "b", "x1": 0, "y1": 0, "x2": 2, "y2": 3},
            ]
        )
        self.assertEqual((area, perimeter), ("6", "10"))

    def test_rejects_non_strict_increasing_x(self):
        exc = must_fail(
            [
                {"id": "ok", "x1": 0, "y1": 0, "x2": 1, "y2": 1},
                {"id": "bad", "x1": 5, "y1": 0, "x2": 1, "y2": 1},
            ]
        )
        self.assertEqual(exc.location, {"index": 1, "id": "bad"})
        self.assertIn("x1 < x2", str(exc))

    def test_rejects_equal_bounds(self):
        exc = must_fail([{"id": "z", "x1": 1, "y1": 0, "x2": 1, "y2": 2}])
        self.assertEqual(exc.location["index"], 0)
        self.assertIn("x1 < x2", str(exc))

    def test_rejects_non_integer_and_bool(self):
        for bad in (1.5, "2", None, True):
            exc = must_fail(
                [{"id": "z", "x1": bad, "y1": 0, "x2": 1, "y2": 1}]
            )
            self.assertEqual(exc.location, {"index": 0, "id": "z"})
            self.assertIn("'x1' must be an integer", str(exc))

    def test_rejects_out_of_range(self):
        exc = must_fail(
            [{"id": "z", "x1": 0, "y1": 0, "x2": 10**9 + 1, "y2": 1}]
        )
        self.assertIn("out of range", str(exc))
        self.assertEqual(exc.location, {"index": 0, "id": "z"})

    def test_boundary_values_allowed(self):
        audit_raw(
            [{"id": "z", "x1": -(10**9), "y1": -(10**9), "x2": 10**9, "y2": 10**9}]
        )

    def test_rejects_bad_id(self):
        exc = must_fail([{"id": "", "x1": 0, "y1": 0, "x2": 1, "y2": 1}])
        self.assertEqual(exc.location, {"index": 0})
        exc = must_fail([{"id": 7, "x1": 0, "y1": 0, "x2": 1, "y2": 1}])
        self.assertEqual(exc.location, {"index": 0})

    def test_rejects_wrong_shape(self):
        exc = must_fail([1, 2, 3])
        self.assertEqual(exc.location, {"index": 0})

    def test_empty_and_count_limits(self):
        must_fail([])
        # 50001 条：全量校验先于计算，不产生部分结果。
        records = [
            {"id": f"r{i}", "x1": 0, "y1": 0, "x2": 1, "y2": 1}
            for i in range(50001)
        ]
        exc = must_fail(records)
        self.assertIn("1 and 50000", str(exc))

    def test_error_message_is_stable(self):
        msg1 = str(
            must_fail(
                [
                    {"id": "x", "x1": 0, "y1": 0, "x2": 1, "y2": 1},
                    {"id": "x", "x1": 0, "y1": 0, "x2": 1, "y2": 1},
                ]
            )
        )
        msg2 = str(
            must_fail(
                [
                    {"id": "x", "x1": 0, "y1": 0, "x2": 1, "y2": 1},
                    {"id": "x", "x1": 0, "y1": 0, "x2": 1, "y2": 1},
                ]
            )
        )
        self.assertEqual(msg1, msg2)


if __name__ == "__main__":
    unittest.main()

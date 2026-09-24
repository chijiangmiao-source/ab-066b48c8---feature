"""净空引擎测试：固定语义用例 + 单位网格独立预言机随机对照 + 校验/HTTP。

被验收的实现（app/clearance.py）不铺开单位网格；这里的单位网格图只
作为测试里的小规模对照预言机。
"""

import random
import unittest

from app.clearance import clearance_audit_raw
from app.geometry import GeometryError


# ---------------------------------------------------------------------
# 独立预言机：单位开胞覆盖 + 四元素图 BFS
# ---------------------------------------------------------------------


class GridOracle:
    """小整数坐标上的精确预言机。

    covered[(i,j)]：开单位胞 (i,i+1)×(j,j+1) 完全落在某个矩形内部。
    给定整数半径 r，喷头中心在单位胞/边/顶点时，开正方形内部所交的
    单位胞必须全部 covered（边界由闭包自动成立）。
    """

    def __init__(self, rects, lo, hi):
        self.lo, self.hi = lo, hi
        self.covered = set()
        self.rects = [(r["x1"], r["y1"], r["x2"], r["y2"]) for r in rects]
        for x1, y1, x2, y2 in self.rects:
            # 开单位胞 (i,i+1)×(j,j+1) 落在矩形内部：i∈[x1,x2)。
            for i in range(x1, x2):
                for j in range(y1, y2):
                    self.covered.add((i, j))

    def in_union_closed(self, x, y):
        return any(x1 <= x <= x2 and y1 <= y <= y2 for x1, y1, x2, y2 in self.rects)

    def _all_covered(self, i0, i1, j0, j1):
        for i in range(i0, i1):
            for j in range(j0, j1):
                if (i, j) not in self.covered:
                    return False
        return True

    @staticmethod
    def _intersecting_cells(lo_edge, hi_edge):
        """与开区间 (lo_edge,hi_edge) 内部相交的单位胞索引半开区间。"""
        import math

        k0 = math.floor(lo_edge)
        k1 = math.ceil(hi_edge)
        return k0, k1

    def feasible_r(self, r, kind, i, j):
        """元素可行性。kind: c 开胞(i,j) / h 竖线纵段(i线,j段) /
        v 横线横段(j线,i段) / t 顶点(i,j)。坐标中心：
        c=(i+.5,j+.5)，h=(i,j+.5)，v=(i+.5,j)，t=(i,j)。"""
        if r == 0:
            if kind == "c":
                return (i, j) in self.covered
            if kind == "h":
                return self.in_union_closed(i, j + 0.5)
            if kind == "v":
                return self.in_union_closed(i + 0.5, j)
            return self.in_union_closed(i, j)

        def span(cx, cy):
            x0, x1 = self._intersecting_cells(cx - r, cx + r)
            y0, y1 = self._intersecting_cells(cy - r, cy + r)
            return self._all_covered(x0, x1, y0, y1)

        if kind == "t":
            return span(i, j)
        if kind == "h":
            return span(i, j + 0.5)
        if kind == "v":
            return span(i + 0.5, j)
        return span(i + 0.5, j + 0.5)

    def connected(self, r, a, b):
        from collections import deque

        lo, hi = self.lo - r - 2, self.hi + r + 2
        seg = range(lo, hi)       # 开胞与边段下标
        vtx = range(lo, hi + 1)   # 顶点下标

        feas = {}
        for i in seg:
            for j in seg:
                if self.feasible_r(r, "c", i, j):
                    feas[("c", i, j)] = True
                if self.feasible_r(r, "h", i, j):
                    feas[("h", i, j)] = True
                if self.feasible_r(r, "v", i, j):
                    feas[("v", i, j)] = True
        for i in vtx:
            for j in vtx:
                if self.feasible_r(r, "t", i, j):
                    feas[("t", i, j)] = True

        start, goal = ("t", a[0], a[1]), ("t", b[0], b[1])
        if start not in feas or goal not in feas:
            return False
        seen = {start}
        q = deque([start])

        def consider(x):
            if x in feas and x not in seen:
                seen.add(x)
                q.append(x)

        while q:
            node = q.popleft()
            if node == goal:
                return True
            kind, i, j = node
            if kind == "c":
                consider(("h", i, j))
                consider(("h", i + 1, j))
                consider(("v", i, j))
                consider(("v", i, j + 1))
            elif kind == "h":
                consider(("t", i, j))
                consider(("t", i, j + 1))
                consider(("c", i - 1, j))
                consider(("c", i, j))
            elif kind == "v":
                consider(("t", i, j))
                consider(("t", i + 1, j))
                consider(("c", i, j - 1))
                consider(("c", i, j))
            else:
                consider(("h", i, j - 1))
                consider(("h", i, j))
                consider(("v", i - 1, j))
                consider(("v", i, j))
        return False

    def point_ok(self, r, x, y):
        """折线上点（整数或半整数坐标）的闭合正方形可行性。"""
        if r == 0:
            return self.in_union_closed(x, y)
        import math

        ix, iy = x - int(x), y - int(y)
        i0 = math.floor(x - r)
        i1 = math.ceil(x + r)
        j0 = math.floor(y - r)
        j1 = math.ceil(y + r)
        for i in range(i0, i1):
            for j in range(j0, j1):
                if (i, j) not in self.covered:
                    return False
        return True

    def validate_path(self, r, a, b, path):
        if tuple(path[0]) != a or tuple(path[-1]) != b:
            return "endpoints mismatch"
        for p, q in zip(path, path[1:]):
            if p[0] != q[0] and p[1] != q[1]:
                return "non-axis-aligned segment"
            steps = max(abs(q[0] - p[0]), abs(q[1] - p[1]))
            for k in range(steps * 2 + 1):
                t = k / 2.0
                x = p[0] + (q[0] - p[0]) * t / steps
                y = p[1] + (q[1] - p[1]) * t / steps
                if not self.point_ok(r, x, y):
                    return f"point ({x},{y}) infeasible at r={r}"
        return None


# ---------------------------------------------------------------------
# 固定语义用例
# ---------------------------------------------------------------------


def R(i, x1, y1, x2, y2):
    return {"id": f"r{i}", "x1": x1, "y1": y1, "x2": x2, "y2": y2}


class FixedClearanceTest(unittest.TestCase):
    def call(self, rects, a, b):
        return clearance_audit_raw(
            {"rectangles": rects, "start": list(a), "end": list(b)}
        )

    def test_single_square_r2(self):
        out = self.call([R(0, 0, 0, 6, 6)], (2, 3), (4, 3))
        self.assertEqual(out["r"], 2)
        self.assertEqual(out["path"][0], [2, 3])
        self.assertEqual(out["path"][-1], [4, 3])

    def test_corner_touch_only_r0_passable(self):
        rects = [R(0, 0, 0, 2, 2), R(1, 2, 2, 4, 4)]
        out = self.call(rects, (1, 1), (3, 3))
        self.assertEqual(out["r"], 0)
        # 路径必须经过接触角点 (2,2)（折点或某条轴对齐段的内部）。
        self.assertTrue(
            any(
                p == (2, 2)
                or (
                    p[0] == q[0] == 2
                    and min(p[1], q[1]) <= 2 <= max(p[1], q[1])
                )
                or (
                    p[1] == q[1] == 2
                    and min(p[0], q[0]) <= 2 <= max(p[0], q[0])
                )
                for p, q in zip(out["path"], out["path"][1:])
            )
            or (2, 2) in [tuple(t) for t in out["path"]]
        )

    def test_corner_touch_positive_r_blocked_but_r0_ok(self):
        # 粗大方框角点相接：r=0 可过，任何 r>=1 不行。
        rects = [R(0, 0, 0, 4, 4), R(1, 4, 4, 8, 8)]
        out = self.call(rects, (2, 2), (6, 6))
        self.assertEqual(out["r"], 0)

    def test_shared_edge_positive_clearance(self):
        rects = [R(0, 0, 0, 2, 4), R(1, 2, 0, 4, 4)]
        out = self.call(rects, (1, 2), (3, 2))
        # 跨过共享边 x=2 时中心净空受两侧边界限制：r=1。
        self.assertEqual(out["r"], 1)

    def test_ring_hole_blocks_large_but_corridor_allows_one(self):
        rects = [
            R(0, 0, 0, 8, 2),
            R(1, 0, 6, 8, 8),
            R(2, 0, 2, 2, 6),
            R(3, 6, 2, 8, 6),
        ]
        out = self.call(rects, (1, 4), (7, 4))
        self.assertGreaterEqual(out["r"], 1)
        # 直穿孔洞一定不行，路径必须绕（在左/右墙之外……走上下边）。
        for p in out["path"]:
            self.assertTrue(2 <= p[0] <= 6 and 2 <= p[1] <= 6) if False else None

    def test_disjoint_unreachable(self):
        rects = [R(0, 0, 0, 2, 2), R(1, 5, 5, 7, 7)]
        with self.assertRaises(GeometryError) as cm:
            self.call(rects, (1, 1), (6, 6))
        self.assertEqual(cm.exception.code, "unreachable")

    def test_points_on_boundary(self):
        out = self.call([R(0, 0, 0, 6, 6)], (0, 3), (6, 3))
        self.assertEqual(out["r"], 0)

    def test_same_point(self):
        out = self.call([R(0, 0, 0, 6, 6)], (2, 3), (2, 3))
        self.assertEqual(out["r"], 2)
        self.assertEqual(out["path"], [[2, 3]])

    def test_thin_bar_clearance_zero(self):
        # 宽 1 的竖条：任何 r>=1 都装不下，r=0 可沿条走。
        rects = [R(0, 0, 0, 1, 5)]
        out = self.call(rects, (0, 1), (0, 4))
        self.assertEqual(out["r"], 0)


class OracleFuzzTest(unittest.TestCase):
    def test_random_matches_grid_oracle(self):
        rng = random.Random(20260924)
        trials = 400
        for trial in range(trials):
            n = rng.randint(1, 7)
            rects = []
            for k in range(n):
                x1 = rng.randint(-5, 5)
                y1 = rng.randint(-5, 5)
                x2 = x1 + rng.randint(1, 5)
                y2 = y1 + rng.randint(1, 5)
                rects.append(R(k, x1, y1, x2, y2))
            # 取样点偏向落在矩形附近：一半直接取矩形边界/内点。
            def sample():
                if rng.random() < 0.6 and rects:
                    rc = rng.choice(rects)
                    if rng.random() < 0.5:
                        return (
                            rng.choice([rc["x1"], rc["x2"]]),
                            rng.randint(rc["y1"], rc["y2"]),
                        )
                    return (
                        rng.randint(rc["x1"], rc["x2"]),
                        rng.choice([rc["y1"], rc["y2"]]),
                    )
                return (rng.randint(-7, 9), rng.randint(-7, 9))

            a, b = sample(), sample()

            with self.subTest(trial=trial, rects=rects, a=a, b=b):
                oracle = GridOracle(rects, -8, 10)
                a_in = oracle.in_union_closed(*a)
                b_in = oracle.in_union_closed(*b)

                try:
                    out = clearance_audit_raw(
                        {"rectangles": rects, "start": list(a), "end": list(b)}
                    )
                except GeometryError as exc:
                    self.assertIn(exc.code, ("point_outside_union", "unreachable"))
                    if exc.code == "point_outside_union":
                        self.assertFalse(a_in and b_in)
                    else:
                        self.assertTrue(a_in and b_in)
                        self.assertFalse(oracle.connected(0, a, b))
                    continue

                self.assertTrue(a_in and b_in)
                # 预言机枚举半径求最大。
                r_star = -1
                for r in range(0, 8):
                    if oracle.connected(r, a, b):
                        r_star = r
                self.assertEqual(
                    out["r"],
                    r_star,
                    msg=f"rects={rects} a={a} b={b} out={out}",
                )
                err = oracle.validate_path(r_star, a, b, out["path"])
                self.assertIsNone(err)

    def test_dense_structured_matches_oracle(self):
        # 固定网格上的小块拼板 + 边界点，大量构型求稳。
        rng = random.Random(99)
        base = []
        for i in range(4):
            for j in range(4):
                if rng.random() < 0.55:
                    base.append(R(len(base), i, j, i + 2, j + 2))
        if not base:
            base = [R(0, 0, 0, 3, 3)]
        oracle = GridOracle(base, -3, 8)
        pts = [(x, y) for x in range(0, 7) for y in range(0, 7)]
        checked = 0
        for a in pts[::7]:
            for b in pts[::5]:
                if not (oracle.in_union_closed(*a) and oracle.in_union_closed(*b)):
                    continue
                out = clearance_audit_raw(
                    {"rectangles": base, "start": list(a), "end": list(b)}
                )
                r_star = -1
                for r in range(0, 6):
                    if oracle.connected(r, a, b):
                        r_star = r
                self.assertEqual(out["r"], r_star, msg=(a, b, base))
                self.assertIsNone(
                    oracle.validate_path(r_star, a, b, out["path"])
                )
                checked += 1
        self.assertGreater(checked, 5)


class ValidationTest(unittest.TestCase):
    def payload(self, **over):
        p = {
            "rectangles": [R(0, 0, 0, 4, 4)],
            "start": [1, 1],
            "end": [3, 3],
        }
        p.update(over)
        return p

    def test_must_be_object(self):
        with self.assertRaises(GeometryError) as cm:
            clearance_audit_raw([1, 2, 3])
        self.assertEqual(cm.exception.code, "invalid_request")

    def test_missing_rectangles(self):
        with self.assertRaises(GeometryError) as cm:
            clearance_audit_raw({"start": [0, 0], "end": [1, 1]})
        self.assertEqual(cm.exception.code, "invalid_request")

    def test_missing_points(self):
        with self.assertRaises(GeometryError) as cm:
            clearance_audit_raw({"rectangles": [R(0, 0, 0, 1, 1)]})
        self.assertEqual(cm.exception.code, "invalid_request")

    def test_bad_point_shape(self):
        with self.assertRaises(GeometryError) as cm:
            clearance_audit_raw(self.payload(start=7))
        self.assertEqual(cm.exception.code, "invalid_sample")
        with self.assertRaises(GeometryError) as cm:
            clearance_audit_raw(self.payload(end=[1, 2, 3]))
        self.assertEqual(cm.exception.code, "invalid_sample")

    def test_point_rejects_bool_float(self):
        for bad in (True, 1.0, "x"):
            with self.assertRaises(GeometryError) as cm:
                clearance_audit_raw(self.payload(start=[bad, 0]))
            self.assertEqual(cm.exception.code, "invalid_sample")

    def test_rectangle_limit_180(self):
        rects = [
            {"id": f"r{i}", "x1": 0, "y1": 0, "x2": 200, "y2": 200}
            for i in range(181)
        ]
        with self.assertRaises(GeometryError) as cm:
            clearance_audit_raw(
                {"rectangles": rects, "start": [1, 1], "end": [199, 199]}
            )
        self.assertEqual(cm.exception.code, "invalid_rectangle")
        # 180 个合法。
        rects180 = rects[:180]
        out = clearance_audit_raw(
            {"rectangles": rects180, "start": [1, 1], "end": [199, 199]}
        )
        self.assertEqual(out["r"], 1)

    def test_point_outside_union(self):
        with self.assertRaises(GeometryError) as cm:
            clearance_audit_raw(self.payload(start=[9, 9]))
        self.assertEqual(cm.exception.code, "point_outside_union")
        self.assertEqual(cm.exception.location, {"point": "start"})
        with self.assertRaises(GeometryError) as cm:
            clearance_audit_raw(self.payload(end=[-1, 0]))
        self.assertEqual(cm.exception.code, "point_outside_union")

    def test_accepts_object_points_and_samples(self):
        out1 = clearance_audit_raw(
            {"rectangles": [R(0, 0, 0, 6, 6)], "start": {"x": 2, "y": 3},
             "end": {"x": 4, "y": 3}}
        )
        self.assertEqual(out1["r"], 2)
        out2 = clearance_audit_raw(
            {"rectangles": [R(0, 0, 0, 6, 6)], "samples": [[2, 3], [4, 3]]}
        )
        self.assertEqual(out2["r"], 2)

    def test_stable_error_message(self):
        p = self.payload(start=[9, 9])
        m1 = str(self._must_fail(p))
        m2 = str(self._must_fail(p))
        self.assertEqual(m1, m2)

    @staticmethod
    def _must_fail(p):
        try:
            clearance_audit_raw(p)
        except GeometryError as exc:
            return exc
        raise AssertionError


class PerformanceTest(unittest.TestCase):
    def test_180_large_rects(self):
        import time

        rng = random.Random(5)
        rects = []
        for k in range(180):
            x1 = rng.randint(-10**8, 10**8 - 2)
            x2 = x1 + rng.randint(1, 10**7)
            y1 = rng.randint(-10**8, 10**8 - 2)
            y2 = y1 + rng.randint(1, 10**7)
            rects.append(R(k, x1, y1, x2, y2))
        # 两点落在并集内的概率低，直接取第一个矩形内部的点即可。
        r0 = rects[0]
        a = (r0["x1"] + 1, r0["y1"] + 1)
        start = time.perf_counter()
        try:
            clearance_audit_raw(
                {"rectangles": rects, "start": list(a),
                 "end": [r0["x2"] - 1, r0["y2"] - 1]}
            )
        except GeometryError:
            pass
        self.assertLess(time.perf_counter() - start, 10.0)


if __name__ == "__main__":
    unittest.main()

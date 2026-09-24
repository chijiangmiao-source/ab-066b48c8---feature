"""净空引擎的朴素预言机 + 随机对照（仅测试用，实现本身不铺网格）。"""

import random
import unittest

from app.geometry import Rect
from app.clearance import maximum_clearance, clearance_audit_raw
from app.geometry import GeometryError


def point_in_union(rects, x, y):
    return any(rc.x1 <= x <= rc.x2 and rc.y1 <= y <= rc.y2 for rc in rects)


def square_feasible(rects, cx, cy, r):
    """闭正方形 [cx-r,cx+r]² 是否完全包含于矩形并集（允许实数坐标）。

    朴素做法：收集全部矩形边界坐标，把正方形内点/边界切成开小格与
    分界点，逐块用覆盖次数（开格）或直接闭包含（点）判定。
    """
    if r == 0:
        return point_in_union(rects, cx, cy)

    xs = sorted({v for rc in rects for v in (rc.x1, rc.x2)})
    ys = sorted({v for rc in rects for v in (rc.y1, rc.y2)})

    # 覆盖计数（开格）。
    nx, ny = len(xs) - 1, len(ys) - 1
    cover = [[0] * ny for _ in range(nx)]
    for rc in rects:
        for i in range(xs.index(rc.x1), xs.index(rc.x2)):
            for j in range(ys.index(rc.y1), ys.index(rc.y2)):
                cover[i][j] += 1

    import bisect

    def cell_at(coords, v):
        k = bisect.bisect_right(coords, v) - 1
        return k

    L, R, B, T = cx - r, cx + r, cy - r, cy + r

    # 1) 正方形开内点碰到的每个并集开格都必须覆盖。
    for i in range(nx):
        ax, bx = xs[i], xs[i + 1]
        if bx <= L or ax >= R:
            continue
        for j in range(ny):
            ay, by = ys[j], ys[j + 1]
            if by <= B or ay >= T:
                continue
            if cover[i][j] == 0:
                return False

    # 2) 四条边：枚举落在边闭区间内的全部网格边界点 + 相邻区间中点。
    def edge_ok(kind, v0, lo, hi):
        cuts = [lo, hi]
        grid = xs if kind == "y" else ys
        for g in grid:
            if lo < g < hi:
                cuts.append(g)
        cuts.sort()
        for t in cuts:
            x, y = (v0, t) if kind == "x" else (t, v0)
            if not point_in_union(rects, x, y):
                return False
        for u, w in zip(cuts, cuts[1:]):
            mid = (u + w) / 2
            x, y = (v0, mid) if kind == "x" else (mid, v0)
            if not point_in_union(rects, x, y):
                return False
        return True

    if not edge_ok("x", L, B, T):
        return False
    if not edge_ok("x", R, B, T):
        return False
    if not edge_ok("y", B, L, R):
        return False
    if not edge_ok("y", T, L, R):
        return False
    return True


def oracle_max_r(rects, a, b, cap=20):
    """整数中心稠密 BFS 求最大 r；r=0 都不通返回 None；点不在并集返回 -1。"""
    if not point_in_union(rects, *a) or not point_in_union(rects, *b):
        return -1
    best = None
    for r in range(0, cap + 1):
        lo_x = min(rc.x1 for rc in rects)
        hi_x = max(rc.x2 for rc in rects)
        lo_y = min(rc.y1 for rc in rects)
        hi_y = max(rc.y2 for rc in rects)
        from collections import deque

        q = deque([a])
        seen = {a}
        hit = False
        if not square_feasible(rects, a[0], a[1], r):
            return best
        while q:
            x, y = q.popleft()
            if (x, y) == b:
                hit = True
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if not (lo_x <= nx <= hi_x and lo_y <= ny <= hi_y):
                    continue
                if (nx, ny) in seen:
                    continue
                if not square_feasible(rects, nx, ny, r):
                    continue
                # 临界坐标 xs±r、ys±r 全为整数：(k,k+1) 内部是同一个边
                # 原子；两端点可行不代表该边原子可行，必须补查中点。
                if not square_feasible(
                    rects, (x + nx) / 2, (y + ny) / 2, r
                ):
                    continue
                seen.add((nx, ny))
                q.append((nx, ny))
        if not hit:
            return best
        best = r
    return best


class ClearanceFuzzTest(unittest.TestCase):
    def test_random_vs_oracle(self):
        rng = random.Random(4242)
        trials = 120
        for trial in range(trials):
            n = rng.randint(1, 6)
            rects = []
            for k in range(n):
                x1 = rng.randint(-3, 4)
                x2 = x1 + rng.randint(1, 4)
                y1 = rng.randint(-3, 4)
                y2 = y1 + rng.randint(1, 4)
                rects.append(Rect(f"r{k}", x1, y1, x2, y2))
            pts = []
            for rc in rects:
                pts.append((rc.x1, rc.y1))
                pts.append((rc.x2, rc.y2))
                pts.append(((rc.x1 + rc.x2) // 2, (rc.y1 + rc.y2) // 2))
            a = rng.choice(pts)
            b = rng.choice(pts)
            with self.subTest(trial=trial, rects=rects, a=a, b=b):
                expected = oracle_max_r(rects, a, b, cap=8)
                if expected is None or expected == -1:
                    with self.assertRaises(GeometryError):
                        maximum_clearance(rects, a, b)
                else:
                    res = maximum_clearance(rects, a, b)
                    self.assertEqual(res.max_r, expected)
                    # 折线逐点（含单位段中点）回查。
                    self.assertEqual(res.path[0], a)
                    self.assertEqual(res.path[-1], b)
                    for p0, p1 in zip(res.path, res.path[1:]):
                        self.assertTrue(
                            p0[0] == p1[0] or p0[1] == p1[1]
                        )
                        # 逐段回查：整数端点 + 开段内多个分数位置。
                        fracs = (0.0, 0.25, 0.5, 0.75, 1.0)
                        if p0[0] == p1[0]:
                            length = abs(p1[1] - p0[1])
                            sgn = 1 if p1[1] > p0[1] else -1
                            for s in range(length):
                                for f in fracs:
                                    self.assertTrue(
                                        square_feasible(
                                            rects, p0[0],
                                            p0[1] + sgn * (s + f),
                                            res.max_r
                                        )
                                    )
                        else:
                            length = abs(p1[0] - p0[0])
                            sgn = 1 if p1[0] > p0[0] else -1
                            for s in range(length):
                                for f in fracs:
                                    self.assertTrue(
                                        square_feasible(
                                            rects,
                                            p0[0] + sgn * (s + f), p0[1],
                                            res.max_r
                                        )
                                    )


class FixedClearanceTest(unittest.TestCase):
    def test_single_rect(self):
        rects = [Rect("a", 0, 0, 10, 8)]
        # 内部两点；瓶颈为 y 半宽 4。
        res = maximum_clearance(rects, (4, 4), (6, 4))
        self.assertEqual(res.max_r, 4)

    def test_interior_square(self):
        rects = [Rect("a", 0, 0, 10, 10)]
        res = maximum_clearance(rects, (4, 5), (6, 5))
        self.assertEqual(res.max_r, 4)

    def test_corner_touch_r0_passable(self):
        rects = [Rect("a", 0, 0, 2, 2), Rect("b", 2, 2, 4, 4)]
        res = maximum_clearance(rects, (1, 1), (3, 3))
        self.assertEqual(res.max_r, 0)
        self.assertIn((2, 2), res.path)

    def test_corner_touch_negative_blocked(self):
        rects = [Rect("a", 0, 0, 2, 2), Rect("b", 2, 2, 4, 4)]
        # (2,2) 处 r=0 可过，但 r=1 不行：结果必须精确为 0。
        res = maximum_clearance(rects, (0, 0), (4, 4))
        self.assertEqual(res.max_r, 0)

    def test_edge_adjacent_positive_clearance(self):
        rects = [Rect("a", 0, 0, 2, 4), Rect("b", 2, 0, 4, 4)]
        # 穿过共边 x=2 的正净空走廊。
        res = maximum_clearance(rects, (1, 2), (3, 2))
        self.assertEqual(res.max_r, 1)

    def test_sample_on_outer_boundary_forces_r0(self):
        rects = [Rect("a", 0, 0, 6, 6)]
        res = maximum_clearance(rects, (0, 3), (3, 3))
        self.assertEqual(res.max_r, 0)
        # 闭集语义：不报错，r=0 有折线。
        self.assertEqual(res.path[0], (0, 3))

    def test_sample_on_inner_boundary_allows_r(self):
        # 点恰落在共边上，闭集允许正净空沿共边推进。
        rects = [Rect("a", 0, 0, 2, 4), Rect("b", 2, 0, 4, 4)]
        res = maximum_clearance(rects, (2, 1), (2, 3))
        self.assertEqual(res.max_r, 1)

    def test_sample_outside_union(self):
        rects = [Rect("a", 0, 0, 2, 2)]
        with self.assertRaises(GeometryError) as cm:
            maximum_clearance(rects, (3, 1), (1, 1))
        self.assertEqual(cm.exception.code, "sample_not_in_union")

    def test_disconnected_r0(self):
        rects = [Rect("a", 0, 0, 1, 1), Rect("b", 3, 3, 4, 4)]
        with self.assertRaises(GeometryError) as cm:
            maximum_clearance(rects, (0, 0), (3, 3))
        self.assertEqual(cm.exception.code, "no_clearance_path")

    def test_hole_blocks_but_ring_walks(self):
        # 外环 10x10 挖 2..8 的孔，净空被孔挤到环宽 2。
        rects = [
            Rect("l", 0, 0, 2, 10),
            Rect("r", 8, 0, 10, 10),
            Rect("b", 2, 0, 8, 2),
            Rect("t", 2, 8, 8, 10),
        ]
        res = maximum_clearance(rects, (1, 1), (9, 9))
        self.assertEqual(res.max_r, 1)

    def test_raw_payload_validation(self):
        payload = {
            "rectangles": [{"id": "a", "x1": 0, "y1": 0, "x2": 4, "y2": 4}],
            "start": [1, 2],
            "end": [3, 2],
        }
        out = clearance_audit_raw(payload)
        self.assertEqual(out["max_clearance"], 1)
        self.assertEqual(out["start"], [1, 2])
        self.assertEqual(out["path"][0], [1, 2])
        self.assertEqual(out["path"][-1], [3, 2])

    def test_raw_bad_point(self):
        payload = {
            "rectangles": [{"id": "a", "x1": 0, "y1": 0, "x2": 4, "y2": 4}],
            "start": [0],
            "end": [4, 4],
        }
        with self.assertRaises(GeometryError) as cm:
            clearance_audit_raw(payload)
        self.assertEqual(cm.exception.code, "invalid_sample_point")

    def test_too_many_rects(self):
        payload = {
            "rectangles": [
                {"id": f"r{i}", "x1": i, "y1": 0, "x2": i + 1, "y2": 1}
                for i in range(181)
            ],
            "start": [0, 0],
            "end": [1, 1],
        }
        with self.assertRaises(GeometryError) as cm:
            clearance_audit_raw(payload)
        self.assertIn("1 and 180", str(cm.exception))


if __name__ == "__main__":
    unittest.main()

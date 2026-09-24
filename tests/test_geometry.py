"""几何引擎测试：固定验收用例 + 随机用例对照单位网格暴力预言机。

注意：被验收的实现不铺开单位网格；网格法只作为测试里的小规模对照预言机。
"""

import random
import unittest

from app.geometry import Rect, audit_rectangles


def brute_force(rects):
    """单位网格并集 + 逐格外露边计数（仅用于小坐标测试对照）。"""
    cells = set()
    for r in rects:
        for x in range(r.x1, r.x2):
            for y in range(r.y1, r.y2):
                cells.add((x, y))
    area = len(cells)
    perimeter = 0
    for x, y in cells:
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) not in cells:
                perimeter += 1
    return area, perimeter


class FixedCasesTest(unittest.TestCase):
    def test_overlapping_area10_perimeter14(self):
        # 验收构型：重叠面积 2。
        rects = [Rect("a", 0, 0, 3, 2), Rect("b", 1, 1, 4, 3)]
        self.assertEqual(audit_rectangles(rects), (10, 14))

    def test_adjacent_boxes_exclude_shared_edge(self):
        # 两个 2x3 方框并排：面积 12，周长 14（公共边 3 不计，两框各 10）。
        rects = [Rect("a", 0, 0, 2, 3), Rect("b", 2, 0, 4, 3)]
        self.assertEqual(audit_rectangles(rects), (12, 14))

    def test_adjacent_vertical_stack(self):
        rects = [Rect("a", 0, 0, 3, 2), Rect("b", 0, 2, 3, 4)]
        self.assertEqual(audit_rectangles(rects), (12, 14))

    def test_geometric_duplicate_no_increment(self):
        single = audit_rectangles([Rect("a", 0, 0, 2, 3)])
        dup = audit_rectangles([Rect("a", 0, 0, 2, 3), Rect("b", 0, 0, 2, 3)])
        self.assertEqual(single, (6, 10))
        self.assertEqual(dup, (6, 10))

    def test_triple_overlap_common_edge(self):
        rects = [
            Rect("a", 0, 0, 2, 2),
            Rect("b", 2, 0, 4, 2),
            Rect("c", 4, 0, 6, 2),
        ]
        self.assertEqual(audit_rectangles(rects), (12, 16))

    def test_nested_box_adds_nothing(self):
        rects = [Rect("o", 0, 0, 10, 10), Rect("i", 2, 2, 4, 4)]
        self.assertEqual(audit_rectangles(rects), (100, 40))

    def test_corner_touch_keeps_both_perimeters(self):
        # 仅角点接触：既不重面积，也不共边，周长 = 两框周长之和。
        self.assertEqual(
            audit_rectangles([Rect("a", 0, 0, 2, 2), Rect("b", 2, 2, 4, 4)]),
            (8, 16),
        )
        self.assertEqual(
            audit_rectangles([Rect("a", 2, 0, 4, 2), Rect("b", 0, 2, 2, 4)]),
            (8, 16),
        )

    def test_cross_shape(self):
        rects = [Rect("v", 1, 0, 3, 4), Rect("h", 0, 1, 4, 3)]
        self.assertEqual(audit_rectangles(rects), (12, 16))

    def test_negative_coordinates(self):
        rects = [Rect("s", -5, -5, 5, 5)]
        self.assertEqual(audit_rectangles(rects), (100, 40))

    def test_large_coordinates_exact_decimal(self):
        rects = [
            Rect("a", 0, 0, 10**9, 10**9),
            Rect("b", 10**9 - 1, 10**9 - 1, 10**9, 10**9),
        ]
        self.assertEqual(audit_rectangles(rects), (10**18, 4 * 10**9))

    def test_empty(self):
        self.assertEqual(audit_rectangles([]), (0, 0))

    def test_single_unit_rect(self):
        self.assertEqual(audit_rectangles([Rect("q", 0, 0, 1, 1)]), (1, 4))


class BruteForceFuzzTest(unittest.TestCase):
    def test_random_sets_match_grid_oracle(self):
        rng = random.Random(20260924)
        for trial in range(300):
            n = rng.randint(1, 10)
            rects = []
            for k in range(n):
                x1 = rng.randint(-4, 3)
                x2 = rng.randint(x1 + 1, x1 + 4)
                y1 = rng.randint(-4, 3)
                y2 = rng.randint(y1 + 1, y1 + 4)
                rects.append(Rect(f"r{k}", x1, y1, x2, y2))
            with self.subTest(trial=trial, rects=rects):
                self.assertEqual(
                    audit_rectangles(rects),
                    brute_force(rects),
                )


class PerformanceTest(unittest.TestCase):
    def test_fifty_thousand_rects(self):
        import time

        rng = random.Random(7)
        rects = []
        for k in range(50000):
            x1 = rng.randint(-10**9, 10**9 - 2)
            x2 = x1 + rng.randint(1, 10**6)
            y1 = rng.randint(-10**9, 10**9 - 2)
            y2 = y1 + rng.randint(1, 10**6)
            rects.append(Rect(f"id-{k}", x1, y1, x2, y2))
        start = time.perf_counter()
        area, perimeter = audit_rectangles(rects)
        elapsed = time.perf_counter() - start
        self.assertGreater(area, 0)
        self.assertGreater(perimeter, 0)
        self.assertLess(elapsed, 15.0, f"sweep too slow: {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()

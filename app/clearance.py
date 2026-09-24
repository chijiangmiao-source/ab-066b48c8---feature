"""方形喷头净空审计：在矩形污染并集内求两点间最大可通行半边长。

问题
----
喷头中心 c=(x,y)，半边长 r（非负整数），要求以 c 为中心的**闭合**
正方形 [x-r, x+r] × [y-r, y+r] 完全包含于矩形污染并集 U；中心只沿
水平/竖直的连续折线移动。求 A、B 两点间最大的 r，并给出可复查的折线。

闭集语义
--------
U 是闭矩形的有限并，仍为闭集：

* r=0 时正方形退化为点，点落在任一边界/角点上即算在并集内；两个仅
  角点相接的矩形可在该角点处通行；
* r>0 时仅角点相接不可通行——接触点任意邻域的正方形内部都探出并集；
* 取样点或路径恰落在边界上一律按闭集裁决：净空按 ``d >= r``，等号
  允许（正方形边与污染边界重合时仍完全包含）。

算法（不铺单位网格、不逐对切割、不调用几何库）
----------------------------------------------
关键事实：中心点 c 处闭合正方形成立，当且仅当**开正方形内部**
``(x-r,x+r) × (y-r,y+r)`` 被并集内部覆盖（边界取闭包极限自动成立）。

覆盖谓词只在喷头边越过某条矩形原边界时翻转，即中心线穿过
``xs_i ± r``（xs_i 为矩形原边界横坐标，纵轴同理）时。于是在压缩坐标

    FX = 去重排序后的 {xs_i - r, xs_i + r}（纵轴同理）

上，谓词在每个细网格开胞、细网格边上恒定。用原边界网格的“未覆盖
开胞”二维前缀和，任一边元素的查询化为“补集矩阵矩形区域是否全零”，
O(1)（bisect 定位）。外接框外四个开半平面显式判否，孔洞（未覆盖开
胞）由前缀和命中。

可行开胞的整条闭包（边、角）都可行（开正方形范围只缩不胀，闭包取
极限），因此连通性只需在**细网格顶点**上 BFS：两相邻顶点连通当且仅
当连接它们的细网格边可行。这样 r=0 时角点相接天然可通行（两条指向
接触角点的边分别来自两个矩形的覆盖胞），而 r>0 时该顶点没有任何入
边，不可借此穿越。r>0 时恰在整数半径出现的零宽走廊（共享边、点接
触极限）也由细网格边/顶点精确表达。

最大半径：先用所有未覆盖开胞（孔洞）与外接框外半平面算出 A、B 两点
净空上界，再在 [0, 上界] 上二分（F_r 随 r 单调收缩）。折线折点全部
取整数细网格顶点；取样点若在开胞内，用同一可行胞闭包内的直角引线
接到其左下角顶点。

为剔除无关连通块（远处孤立矩形只会白白膨胀压缩网格），先在 r=0 的
粗网格上 BFS 出 A 所在闭连通块，仅保留与该块内部相交的矩形。
"""

from __future__ import annotations

from array import array
from bisect import bisect_left, bisect_right
from collections import deque

from .geometry import COORD_BOUND, GeometryError, Rect, parse_rectangle_records

MAX_RECTANGLES = 180


# ---------------------------------------------------------------------
# 原边界压缩网格：未覆盖开胞矩阵 + 二维前缀和
# ---------------------------------------------------------------------


class CoverGrid:
    """矩形边界压缩网格上的“未覆盖开胞”矩阵及二维前缀和。

    ``miss[i][j]`` 为 1 表示开胞
    ``(xs[i],xs[i+1]) × (ys[j],ys[j+1])`` 不被任何矩形内部覆盖。
    ``pref[a][b]`` 是 miss 在行 [0,a)、列 [0,b) 上的矩形和。
    """

    __slots__ = ("xs", "ys", "miss", "pref", "m", "n")

    def __init__(self, rects: list[Rect]) -> None:
        xs_set: set[int] = set()
        ys_set: set[int] = set()
        for rc in rects:
            xs_set.add(rc.x1)
            xs_set.add(rc.x2)
            ys_set.add(rc.y1)
            ys_set.add(rc.y2)
        self.xs = sorted(xs_set)
        self.ys = sorted(ys_set)
        self.m = len(self.xs) - 1
        self.n = len(self.ys) - 1

        xpos = {x: i for i, x in enumerate(self.xs)}
        ypos = {y: j for j, y in enumerate(self.ys)}

        # 二维差分；同一点叠加数 <= 矩形数（<=180），有符号 short 足够。
        diff = [array("h", [0]) * (self.n + 1) for _ in range(self.m + 1)]
        for rc in rects:
            i1, i2 = xpos[rc.x1], xpos[rc.x2]
            j1, j2 = ypos[rc.y1], ypos[rc.y2]
            diff[i1][j1] += 1
            diff[i2][j1] -= 1
            diff[i1][j2] -= 1
            diff[i2][j2] += 1

        miss = [bytearray(self.n) for _ in range(self.m)]
        col = [0] * self.n
        for i in range(self.m):
            run = 0
            drow = diff[i]
            mrow = miss[i]
            for j in range(self.n):
                run += drow[j]
                col[j] += run
                if col[j] == 0:
                    mrow[j] = 1
        self.miss = miss

        pref = [[0] * (self.n + 1) for _ in range(self.m + 1)]
        for i in range(self.m):
            src = miss[i]
            dst = pref[i + 1]
            up = pref[i]
            run = 0
            for j in range(self.n):
                run += src[j]
                dst[j + 1] = up[j + 1] + run
        self.pref = pref

    def misses(self, i0: int, i1: int, j0: int, j1: int) -> int:
        """开胞索引矩形 [i0,i1) × [j0,j1) 内未覆盖胞的数量。"""
        if i0 >= i1 or j0 >= j1:
            return 0
        p = self.pref
        return p[i1][j1] - p[i0][j1] - p[i1][j0] + p[i0][j0]


# ---------------------------------------------------------------------
# 给定半径的细网格与可行边
# ---------------------------------------------------------------------


class FineLayout:
    """半径 r 下的压缩细网格及其可行细网格边。

    细顶点 (u,v) 坐标为 (fx[u], fy[v])，均为整数。

    * ``ve[id_ve(v,u)]``：水平细边，连接 (u,v)-(u+1,v)
      （中心线 y=fy[v]，x 扫过开段 (fx[u],fx[u+1])）；
    * ``he[id_he(u,v)]``：竖直细边，连接 (u,v)-(u,v+1)
      （中心线 x=fx[u]，y 扫过开段 (fy[v],fy[v+1])）。

    可行开胞的闭包必可行，故顶点无需单独标记；r=0 时边按闭集语义
    由相邻覆盖胞裁决。
    """

    __slots__ = ("fx", "fy", "U", "V", "ve", "he", "r")

    def __init__(self, grid: CoverGrid, r: int) -> None:
        self.r = r
        xs, ys = grid.xs, grid.ys
        if r == 0:
            self.fx = xs
            self.fy = ys
        else:
            self.fx = sorted({x - r for x in xs} | {x + r for x in xs})
            self.fy = sorted({y - r for y in ys} | {y + r for y in ys})
        self.U = len(self.fx) - 1
        self.V = len(self.fy) - 1
        self.ve = bytearray((self.V + 1) * self.U)
        self.he = bytearray((self.U + 1) * self.V)
        if r == 0:
            self._build_rzero(grid)
        else:
            self._build_rpositive(grid, xs, ys)

    # -- r=0：闭集语义 ---------------------------------------------------

    def _build_rzero(self, grid: CoverGrid) -> None:
        m, n = grid.m, grid.n
        miss = grid.miss
        U, V = self.U, self.V
        for i in range(U + 1):
            base = i * V
            for j in range(V):
                # 竖直线 xs[i] 上的开纵段：左右任一覆盖胞即在闭并集内。
                if (i > 0 and not miss[i - 1][j]) or (i < m and not miss[i][j]):
                    self.he[base + j] = 1
        for j in range(V + 1):
            base = j * U
            for i in range(U):
                # 水平线 ys[j] 上的开横段：上下任一覆盖胞即可。
                if (j > 0 and not miss[i][j - 1]) or (j < n and not miss[i][j]):
                    self.ve[base + i] = 1

    # -- r>0：开正方形内部必须被并集内部全覆盖 ---------------------------

    def _build_rpositive(self, grid: CoverGrid, xs: list[int], ys: list[int]) -> None:
        r = self.r
        fx, fy = self.fx, self.fy
        U, V = self.U, self.V
        xmin, xmax = xs[0], xs[-1]
        ymin, ymax = ys[0], ys[-1]

        # 细坐标处喷头内部投影到原开胞索引区间。开区间 (lo,hi) 与开胞
        # 内部 (xs[i],xs[i+1]) 相交的 i 范围为
        # [bisect_right(xs,lo)-1, bisect_left(xs,hi))：
        # lo 恰压线时不包含左胞，lo 落在两线之间时包含左胞——闭集裁决
        # 的关键细节。精确点 fx[u] 用 [lx[u],hx[u])；开段 (fx[u],fx[u+1])
        # 的包络用 [lx[u],hx[u+1])。
        lx = [max(0, bisect_right(xs, fx[u] - r) - 1) for u in range(U + 1)]
        hx = [bisect_left(xs, fx[u] + r) for u in range(U + 1)]
        ly = [max(0, bisect_right(ys, fy[v] - r) - 1) for v in range(V + 1)]
        hy = [bisect_left(ys, fy[v] + r) for v in range(V + 1)]
        misses = grid.misses

        # 竖直细边 he(u,v)：x 精确 fx[u]，y 扫过开段 (fy[v],fy[v+1])。
        for u in range(U + 1):
            i0, i1 = lx[u], hx[u]
            if i0 >= i1:
                continue
            # 外接框外开半平面：投影越过原边界即漏（等号恰好压边允许）。
            if fx[u] - r < xmin or fx[u] + r > xmax:
                continue
            base = u * V
            for v in range(V):
                if fy[v] - r < ymin or fy[v + 1] + r > ymax:
                    continue
                j0, j1 = ly[v], hy[v + 1]
                if j0 < j1 and not misses(i0, i1, j0, j1):
                    self.he[base + v] = 1

        # 水平细边 ve(v,u)：y 精确 fy[v]，x 扫过开段 (fx[u],fx[u+1])。
        for v in range(V + 1):
            j0, j1 = ly[v], hy[v]
            if j0 >= j1:
                continue
            if fy[v] - r < ymin or fy[v] + r > ymax:
                continue
            base = v * U
            for u in range(U):
                if fx[u] - r < xmin or fx[u + 1] + r > xmax:
                    continue
                i0, i1 = lx[u], hx[u + 1]
                if i0 < i1 and not misses(i0, i1, j0, j1):
                    self.ve[base + u] = 1

    # -- 顶点 BFS --------------------------------------------------------

    def id_ve(self, v: int, u: int) -> int:
        return v * self.U + u

    def id_he(self, u: int, v: int) -> int:
        return u * self.V + v

    def id_vtx(self, u: int, v: int) -> int:
        return u * (self.V + 1) + v

    def anchor(self, x: int, y: int) -> tuple[int, int, int]:
        """整数点所在细元素的“左下”细顶点索引 (u,v,顶点id)。

        点在开胞内时 u/v 为该胞下标；点恰好落在细线上时取该线自身
        下标（bisect_right-1 对两种情形一致）。引线全程在同一可行元素
        的闭包内。
        """
        u = bisect_left(self.fx, x)
        if u == len(self.fx) or self.fx[u] != x:
            u -= 1
        v = bisect_left(self.fy, y)
        if v == len(self.fy) or self.fy[v] != y:
            v -= 1
        return u, v, self.id_vtx(u, v)

    def bfs(self, start: int, goal: int) -> array | None:
        """细顶点连通性；返回 parent 数组或 None。"""
        if start == goal:
            parent = array("i", [-1]) * ((self.U + 1) * (self.V + 1))
            parent[start] = start
            return parent
        parent = array("i", [-1]) * ((self.U + 1) * (self.V + 1))
        seen = bytearray((self.U + 1) * (self.V + 1))
        parent[start] = start
        seen[start] = 1
        q = deque([start])
        U, V = self.U, self.V
        ve, he = self.ve, self.he
        while q:
            node = q.popleft()
            u, v = divmod(node, V + 1)
            # 左：水平细边 ve(v,u-1)，u 减 1，顶点步长 V+1。
            if u > 0:
                e = v * U + (u - 1)
                nb = node - (V + 1)
                if ve[e] and not seen[nb]:
                    seen[nb] = 1
                    parent[nb] = node
                    if nb == goal:
                        return parent
                    q.append(nb)
            # 右：ve(v,u)
            if u < U:
                e = v * U + u
                nb = node + (V + 1)
                if ve[e] and not seen[nb]:
                    seen[nb] = 1
                    parent[nb] = node
                    if nb == goal:
                        return parent
                    q.append(nb)
            # 下：he(u,v-1)，v 减 1，顶点步长 1。
            if v > 0:
                e = u * V + (v - 1)
                nb = node - 1
                if he[e] and not seen[nb]:
                    seen[nb] = 1
                    parent[nb] = node
                    if nb == goal:
                        return parent
                    q.append(nb)
            # 上：he(u,v)
            if v < V:
                e = u * V + v
                nb = node + 1
                if he[e] and not seen[nb]:
                    seen[nb] = 1
                    parent[nb] = node
                    if nb == goal:
                        return parent
                    q.append(nb)
        return None


# ---------------------------------------------------------------------
# 点位裁决与净空上界
# ---------------------------------------------------------------------


def _point_in_rects(rects: list[Rect], x: int, y: int) -> bool:
    return any(rc.x1 <= x <= rc.x2 and rc.y1 <= y <= rc.y2 for rc in rects)


def point_clearance(grid: CoverGrid, x: int, y: int) -> int:
    """点到并集补集（开集）的 Chebyshev 净空整数上界。

    逐“未覆盖开胞”取 max(横向间隙, 纵向间隙) 的最小值，再并入外接框
    外四个开半平面。点贴着污染边界时该方向间隙为 0；间隙允许取等号
    （闭合正方形边压边界仍完全包含）。
    """
    xs, ys = grid.xs, grid.ys
    best = min(x - xs[0], xs[-1] - x, y - ys[0], ys[-1] - y)
    if best <= 0:
        return 0
    miss = grid.miss
    for i, row in enumerate(miss):
        if x <= xs[i]:
            gx = xs[i] - x
        elif x >= xs[i + 1]:
            gx = x - xs[i + 1]
        else:
            gx = 0
        if gx >= best:
            continue
        for j in range(grid.n):
            if not row[j]:
                continue
            if y <= ys[j]:
                gy = ys[j] - y
            elif y >= ys[j + 1]:
                gy = y - ys[j + 1]
            else:
                gy = 0
            d = gx if gx > gy else gy
            if d < best:
                best = d
                if best == 0:
                    return 0
    return best


# ---------------------------------------------------------------------
# r=0 连通块筛选：剔除与 A、B 所在闭连通块无关的矩形
# ---------------------------------------------------------------------


def component_rects(
    rects: list[Rect], grid: CoverGrid, a: tuple[int, int], b: tuple[int, int]
) -> list[Rect]:
    layout = FineLayout(grid, 0)
    _, _, na = layout.anchor(*a)
    _, _, nb = layout.anchor(*b)
    parent = layout.bfs(na, nb)
    if parent is None:
        raise GeometryError(
            "sample points are not connected in the union even at r=0",
            None,
            "unreachable",
        )

    # 全量标记 A 可达的细顶点（bfs 找到 B 即返回，未必遍历完）。
    V1 = layout.V + 1
    reached = bytearray((layout.U + 1) * V1)
    q = deque([na])
    reached[na] = 1
    U, V = layout.U, layout.V
    ve, he = layout.ve, layout.he
    while q:
        node = q.popleft()
        u, v = divmod(node, V1)
        if u > 0 and ve[v * U + (u - 1)]:
            t = node - V1
            if not reached[t]:
                reached[t] = 1
                q.append(t)
        if u < U and ve[v * U + u]:
            t = node + V1
            if not reached[t]:
                reached[t] = 1
                q.append(t)
        if v > 0 and he[u * V + (v - 1)]:
            t = node - 1
            if not reached[t]:
                reached[t] = 1
                q.append(t)
        if v < V and he[u * V + v]:
            t = node + 1
            if not reached[t]:
                reached[t] = 1
                q.append(t)

    # 覆盖开胞只要任一角点可达，即属于该闭连通块。
    in_component = bytearray(grid.m * grid.n)
    for i in range(grid.m):
        base = i * grid.n
        for j in range(grid.n):
            if grid.miss[i][j]:
                continue
            if (
                reached[i * V1 + j]
                or reached[(i + 1) * V1 + j]
                or reached[i * V1 + (j + 1)]
                or reached[(i + 1) * V1 + (j + 1)]
            ):
                in_component[base + j] = 1

    xpos = {x: i for i, x in enumerate(grid.xs)}
    ypos = {y: j for j, y in enumerate(grid.ys)}
    kept: list[Rect] = []
    for rc in rects:
        i1, i2 = xpos[rc.x1], xpos[rc.x2]
        j1, j2 = ypos[rc.y1], ypos[rc.y2]
        hit = False
        for i in range(i1, i2):
            base = i * grid.n
            for j in range(j1, j2):
                if in_component[base + j]:
                    hit = True
                    break
            if hit:
                break
        if hit:
            kept.append(rc)
    return kept


# ---------------------------------------------------------------------
# 折线复原
# ---------------------------------------------------------------------


def _simplify(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """删除重复点与共线折点；保留每段严格水平或竖直。"""
    out: list[tuple[int, int]] = []
    for p in points:
        if out and out[-1] == p:
            continue
        while len(out) >= 2:
            ax, ay = out[-2]
            bx, by = out[-1]
            cx, cy = p
            if (ax == bx == cx) or (ay == by == cy):
                out.pop()
            else:
                break
        out.append(p)
    return out


def _polyline(
    layout: FineLayout,
    parent: array,
    goal: int,
    a: tuple[int, int],
    b: tuple[int, int],
) -> list[tuple[int, int]]:
    fx, fy = layout.fx, layout.fy
    # BFS 顶点链（细顶点，全为整数）。
    chain = [goal]
    node = goal
    while parent[node] != node:
        node = parent[node]
        chain.append(node)
    chain.reverse()

    def xy(nid: int) -> tuple[int, int]:
        u, v = divmod(nid, layout.V + 1)
        return fx[u], fy[v]

    ua, va, anchor_a = layout.anchor(*a)
    ub, vb, anchor_b = layout.anchor(*b)
    ax, ay = fx[ua], fy[va]  # a 所在元素（可行）闭包的左下角细顶点
    bx, by = fx[ub], fy[vb]

    # a 位于可行元素闭包内（ax<=a0<=fx[ua+1] 等），直角引线到锚点：
    # 至多一个拐点，拐点仍在同一闭包内。
    pts: list[tuple[int, int]] = [a]
    if (ax, ay) != a:
        if a[0] != ax and a[1] != ay:
            pts.append((ax, a[1]))
        pts.append((ax, ay))
    pts.extend(xy(nid) for nid in chain[1:])
    if (bx, by) != b:
        if pts[-1] != (bx, by):
            pts.append((bx, by))
        if b[0] != bx and b[1] != by:
            pts.append((bx, b[1]))
        pts.append(b)
    return _simplify(pts)


# ---------------------------------------------------------------------
# 载荷校验与入口
# ---------------------------------------------------------------------


def _parse_point(value: object, field: str) -> tuple[int, int]:
    if isinstance(value, dict):
        x, y = value.get("x"), value.get("y")
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        x, y = value
    else:
        raise GeometryError(
            f"'{field}' must be a [x, y] array or an {{x, y}} object",
            {"field": field},
            "invalid_sample",
        )
    if isinstance(x, bool) or not isinstance(x, int):
        raise GeometryError(
            f"'{field}': 'x' must be an integer", {"field": field}, "invalid_sample"
        )
    if isinstance(y, bool) or not isinstance(y, int):
        raise GeometryError(
            f"'{field}': 'y' must be an integer", {"field": field}, "invalid_sample"
        )
    if abs(x) > COORD_BOUND or abs(y) > COORD_BOUND:
        raise GeometryError(
            f"'{field}': coordinates out of range [-1e9, 1e9]",
            {"field": field},
            "invalid_sample",
        )
    return x, y


def _connected(grid: CoverGrid, r: int, a: tuple[int, int], b: tuple[int, int]):
    layout = FineLayout(grid, r)
    _, _, na = layout.anchor(*a)
    _, _, nb = layout.anchor(*b)
    return layout, layout.bfs(na, nb)


def clearance_audit_raw(payload: object) -> dict:
    """校验载荷并求最大净空 r 与可复查折线。

    接受::

        {"rectangles": [...], "start": [x, y], "end": [x, y]}

    点也接受 ``{"x", "y"}``；或用 ``"samples": [p1, p2]`` 代替
    start/end。返回
    ``{"r": int, "start": [x,y], "end": [x,y], "path": [[x,y], ...]}``。
    """
    if not isinstance(payload, dict):
        raise GeometryError(
            "request body must be an object with 'rectangles' and two sample points",
            None,
            "invalid_request",
        )
    if "rectangles" not in payload:
        raise GeometryError("missing 'rectangles'", None, "invalid_request")
    rects = parse_rectangle_records(
        payload["rectangles"], MAX_RECTANGLES, code="invalid_rectangle"
    )

    if "samples" in payload and "start" not in payload and "end" not in payload:
        samples = payload["samples"]
        if not isinstance(samples, list) or len(samples) != 2:
            raise GeometryError(
                "'samples' must be an array of exactly two points",
                {"field": "samples"},
                "invalid_sample",
            )
        a = _parse_point(samples[0], "samples[0]")
        b = _parse_point(samples[1], "samples[1]")
    else:
        if "start" not in payload or "end" not in payload:
            raise GeometryError(
                "missing 'start' and 'end' sample points", None, "invalid_request"
            )
        a = _parse_point(payload["start"], "start")
        b = _parse_point(payload["end"], "end")

    # r=0 闭集成员资格：直接查矩形（边界、角点一律算内）。
    if not _point_in_rects(rects, *a):
        raise GeometryError(
            "start point is not contained in the union",
            {"point": "start"},
            "point_outside_union",
        )
    if not _point_in_rects(rects, *b):
        raise GeometryError(
            "end point is not contained in the union",
            {"point": "end"},
            "point_outside_union",
        )

    grid0 = CoverGrid(rects)
    # 连通性（r=0）失败在此抛出；同时裁掉无关矩形，压缩后续网格规模。
    kept = component_rects(rects, grid0, a, b)
    grid = CoverGrid(kept) if len(kept) != len(rects) else grid0

    cap = min(point_clearance(grid, *a), point_clearance(grid, *b))

    # 同点：最大 r 即该点自身净空，折线退化为单点（可行元素闭包保证
    # 锚点顶点同样可行，无需 BFS）。
    if a == b:
        return {
            "r": cap,
            "start": [a[0], a[1]],
            "end": [b[0], b[1]],
            "path": [[a[0], a[1]]],
        }

    # 二分最大可行整数 r（F_r 随 r 单调收缩）。
    lo, hi = 0, cap + 1
    r_star = 0
    while lo < hi:
        mid = (lo + hi) >> 1
        _, parent = _connected(grid, mid, a, b)
        if parent is not None:
            r_star = mid
            lo = mid + 1
        else:
            hi = mid

    layout, parent = _connected(grid, r_star, a, b)
    if parent is None:  # 防御性：二分不变量保证不会发生
        raise GeometryError("internal clearance search failure")
    _, _, nb = layout.anchor(*b)
    path = _polyline(layout, parent, nb, a, b)
    return {
        "r": r_star,
        "start": [a[0], a[1]],
        "end": [b[0], b[1]],
        "path": [[x, y] for x, y in path],
    }

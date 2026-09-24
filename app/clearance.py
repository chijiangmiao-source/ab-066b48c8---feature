"""方形喷头净空复核引擎。

问题
----
给定轴对齐矩形的并集（污染域，闭集）与两个整数取样点 A、B，求最大的
非负整数半边长 ``r``，使得一只轴对齐、边长 ``2r``（``r=0`` 时退化为点）
的方形喷头，其中心可沿**水平/竖直折线**从 A 连续移动到 B，且路径上任一
位置以中心展开的闭正方形 ``[cx-r, cx+r] × [cy-r, cy+r]`` 都完全包含于
污染并集；并返回一条可复查的整数折线路径。

语义
----
* 矩形边界、并集内孔洞壁、取样点恰落在边界上——全部按**同一闭集**处理：
  正方形与污染域共边、共点合法（闭包含 ``⊆``）。
* ``r=0`` 时仅角点相接的两个矩形可在接触角点通行（点属于两边的闭包）；
  任何 ``r>0`` 都不能借角点穿越（正方形内点必须落在被覆盖的开格内）。

算法（不铺开单位网格、不逐对切割矩形、不调用几何库，纯标准库）
----------------------------------------------------------------
1. 矩形并集只在其边界坐标排列 ``xs × ys`` 上发生变化；用二维差分 + 前缀和
   得到每个开格 ``(xs[i],xs[i+1]) × (ys[j],ys[j+1])`` 的覆盖次数，O(n²)。
2. 半边长 r 下，正方形边界扫过矩形边界的临界中心位置是
   ``{xs[k]±r} × {ys[k]±r}``。再做一次坐标压缩，可行性在每个原子
   （开格 / 边 / 顶点）上恒定——这同时精确处理了"零宽走廊"（可行中心只
   能贴着边界线段行走）的情形。
3. 每个原子的可行性化约为五个覆盖位掩码的包含判定（正方形内点 + 四条
   边，端点用闭邻接格的并集掩码），按位掩码行批量计算；开格取遍内点所
   在的每个并集格，因此角点漏洞在任何 r>0 都判否。
4. 在"开格—边—顶点"的关联图上洪泛：两点连通当且仅当同属一个可行原子
   的关联连通块。r 的可行集关于 r 单调，二分最大整数 r，再用父链重建
   只走水平/竖直段的整数折线，并逐段枚举途经原子回查。
"""

from __future__ import annotations

from array import array
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .geometry import GeometryError, Rect, validate_rectangles

MAX_RECTS = 180
COORD_BOUNDS = 1_000_000_000


# --------------------------------------------------------------------------
# 并集拓扑：边界坐标排列 + 每个开格的覆盖次数
# --------------------------------------------------------------------------


class UnionLayout:
    """矩形并集在压缩坐标排列上的覆盖矩阵。"""

    __slots__ = ("xs", "ys", "cover", "nx", "ny", "full_x", "full_y",
                 "_range_levels", "_y_levels")

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
        self.nx = len(self.xs) - 1
        self.ny = len(self.ys) - 1

        # 二维差分（矩形在压缩索引上的投影范围）+ 标准二维前缀和。
        diff = [[0] * (self.ny + 1) for _ in range(self.nx + 1)]
        for rc in rects:
            ix1 = bisect_left(self.xs, rc.x1)
            ix2 = bisect_left(self.xs, rc.x2)
            iy1 = bisect_left(self.ys, rc.y1)
            iy2 = bisect_left(self.ys, rc.y2)
            diff[ix1][iy1] += 1
            diff[ix1][iy2] -= 1
            diff[ix2][iy1] -= 1
            diff[ix2][iy2] += 1

        cover: list[array] = []
        pref_up = [0] * (self.ny + 1)
        for i in range(self.nx):
            row = array("i", [0]) * self.ny
            run = 0
            drow = diff[i]
            for j in range(self.ny):
                run += drow[j]
                pref_up[j] += run
                row[j] = 1 if pref_up[j] > 0 else 0
            cover.append(row)
        self.cover = cover

        # 覆盖位掩码：full_x[i] 的第 iy 位 = 开格 (i,iy) 被覆盖；
        # full_y[iy] 的第 i 位 = 开格 (i,iy) 被覆盖。
        full_x = [0] * self.nx
        full_y = [0] * self.ny
        for i in range(self.nx):
            mx = 0
            row = cover[i]
            for j in range(self.ny):
                if row[j]:
                    mx |= 1 << j
                    full_y[j] |= 1 << i
            full_x[i] = mx
        self.full_x = full_x
        self.full_y = full_y

        # 区间 AND 的稀疏表（内点要求相交的**每个**开格都被覆盖）。
        levels = [full_x]
        span = 2
        while span <= self.nx:
            prev = levels[-1]
            step = span >> 1
            levels.append(
                [prev[k] & prev[k + step] for k in range(self.nx - span + 1)]
            )
            span <<= 1
        self._range_levels = levels

        # full_y 的区间 AND 稀疏表（四条边方向对称使用）。
        y_levels = [full_y]
        span = 2
        while span <= self.ny:
            prev = y_levels[-1]
            step = span >> 1
            y_levels.append(
                [prev[k] & prev[k + step] for k in range(self.ny - span + 1)]
            )
            span <<= 1
        self._y_levels = y_levels

    def range_and_x(self, lo: int, hi: int) -> int:
        """full_x 在闭格索引区间 [lo,hi] 上的 AND；空区间返回 0。"""
        if lo > hi:
            return 0
        length = hi - lo + 1
        lv = length.bit_length() - 1
        step = 1 << lv
        tab = self._range_levels[lv]
        return tab[lo] & tab[hi - step + 1]

    def range_and_y(self, lo: int, hi: int) -> int:
        if lo > hi:
            return 0
        length = hi - lo + 1
        lv = length.bit_length() - 1
        step = 1 << lv
        tab = self._y_levels[lv]
        return tab[lo] & tab[hi - step + 1]

    # -- 闭集点归属 -------------------------------------------------------

    def contains(self, x: int, y: int) -> bool:
        """闭集语义下点是否属于并集（恰在边界也算）。"""
        for i in _closed_adjacent(self.xs, x, self.nx):
            for j in _closed_adjacent(self.ys, y, self.ny):
                if self.cover[i][j]:
                    return True
        return False


# --------------------------------------------------------------------------
# 坐标区间 → 压缩格索引位掩码
# --------------------------------------------------------------------------


def _bit_range(lo: int, hi: int) -> int:
    if lo > hi:
        return 0
    return ((1 << (hi - lo + 1)) - 1) << lo


def strict_cells(coords: list[int], lo: int, hi: int, n: int) -> int:
    """开区间 (lo,hi) 与排列开格**内部**相交的格索引位掩码。

    仅在端点相切的格不计（``coords[k+1]==lo`` 或 ``coords[k]==hi``）。
    """
    if hi <= lo:
        return 0
    first = bisect_right(coords, lo) - 1
    last = bisect_left(coords, hi) - 1
    if first < 0:
        first = 0
    if last >= n:
        last = n - 1
    return _bit_range(first, last) if first <= last else 0


def _closed_adjacent(coords: list[int], v: int, n: int) -> tuple[int, ...]:
    """固定坐标 v 处闭相邻的开格索引（v 恰在边界上时为左右两个）。"""
    p = bisect_left(coords, v)
    if p < len(coords) and coords[p] == v:
        return tuple(k for k in (p - 1, p) if 0 <= k < n)
    k = bisect_right(coords, v) - 1
    return (k,) if 0 <= k < n else ()


def _closed_adjacent_bits(coords: list[int], v: int, n: int) -> int:
    """``_closed_adjacent`` 的位掩码形式（用于固定角点 2×2 邻接查询）。"""
    m = 0
    for k in _closed_adjacent(coords, v, n):
        m |= 1 << k
    return m


def _and_of_bitset(layout_range_and, bits: int) -> int:
    """位掩码给出的（必为连续）格区间上的覆盖 AND。"""
    if not bits:
        return 0
    lo = (bits & -bits).bit_length() - 1
    hi = bits.bit_length() - 1
    return layout_range_and(lo, hi)


def _or_adjacent(full: list[int], coords: list[int], v: int, n: int) -> int:
    m = 0
    for k in _closed_adjacent(coords, v, n):
        m |= full[k]
    return m


# --------------------------------------------------------------------------
# 原子图：开格 + 边 + 顶点，位压行存储于一张扁平字节标志表
# --------------------------------------------------------------------------


@dataclass
class AtomGraph:
    xs: list[int]          # 偏移后的压缩 x 坐标（长度 nxr+1）
    ys: list[int]
    flags: bytearray       # 原子是否为可行中心位置（位寻址）
    nxr: int
    nyr: int
    c0: int                # 各层位基址
    v0: int
    h0: int
    p0: int
    sc: int                # 各行位步长（已按字节对齐）
    sh: int
    total: int             # 节点位空间大小

    def cell(self, i: int, j: int) -> int:
        return self.c0 + i * self.sc + j

    def vseg(self, i: int, j: int) -> int:
        return self.v0 + i * self.sc + j

    def hseg(self, i: int, j: int) -> int:
        return self.h0 + i * self.sh + j

    def vert(self, i: int, j: int) -> int:
        return self.p0 + i * self.sh + j

    def feasible(self, node: int) -> bool:
        return bool(self.flags[node >> 3] & (1 << (node & 7)))


def _zero_runs(m: int, n: int):
    """[0,n) 中 m 的连续零位段 (a,b)（闭区间）。"""
    z = ((1 << n) - 1) & ~m
    while z:
        bit = z & -z
        a = bit.bit_length() - 1
        b = a
        while z & (bit << 1):
            bit <<= 1
            b += 1
        yield a, b
        z ^= (((1 << (b - a + 1)) - 1) << a)


class _IntervalSubsetRows:
    """原子集合是连续区间 ``s_j=[lo_j,hi_j]``，lo/hi 关于 j 单调不减。

    ``subset_rows(keys)[i]`` 的第 j 位 ⇔ ``s_j ⊆ keys[i]``（key 任意）。
    对每个 key 的每个零段二分找出与之相交的区间段（lo/hi 单调），
    汇总剔除。空原子永不成立。结果按 key 值缓存。
    """

    __slots__ = ("lo", "hi", "valid", "_sub", "key_span", "jlo", "jhi")

    def __init__(self, bitsets: list[int], key_span: int) -> None:
        lo: list[int] = []
        hi: list[int] = []
        valid = 0
        first = -1
        last = -1
        prev_lo, prev_hi = 0, -1
        for j, m in enumerate(bitsets):
            if m:
                cur_lo = (m & -m).bit_length() - 1
                cur_hi = m.bit_length() - 1
                lo.append(cur_lo)
                hi.append(cur_hi)
                valid |= 1 << j
                if first < 0:
                    first = j
                last = j
                prev_lo, prev_hi = cur_lo, cur_hi
            else:
                # 继承前值以保持 lo/hi 单调；该位由 valid 过滤掉。
                lo.append(prev_lo)
                hi.append(prev_hi)
        self.lo = lo
        self.hi = hi
        self.valid = valid
        # 非空区间原子必为连续下标段（滑窗语义），二分只在该段内进行。
        self.jlo = max(first, 0)
        self.jhi = last
        self.key_span = key_span
        self._sub: dict[int, int] = {}

    def subset_rows(self, keys: list[int]) -> list[int]:
        cache = self._sub
        lo, hi, valid = self.lo, self.hi, self.valid
        span = self.key_span
        jlo, jhi = self.jlo, self.jhi
        out: list[int] = []
        for m in keys:
            row = cache.get(m)
            if row is None:
                bad = 0
                for a, b in _zero_runs(m, span):
                    k_hi = bisect_right(lo, b, jlo, jhi + 1) - 1
                    k_lo = bisect_left(hi, a, jlo, jhi + 1)
                    if k_lo <= k_hi:
                        bad |= _bit_range(k_lo, k_hi)
                row = valid & ~bad
                cache[m] = row
            out.append(row)
        return out


def _transpose8(x: list[int]) -> list[int]:
    """8×8 位矩阵转置，内部用单字 64 位蝴蝶交换（Hacker's Delight）。

    输入 x[r] 的第 c 位为矩阵元 (r,c)；输出 y[c] 的第 r 位为 (r,c)。
    """
    w = sum((v & 0xFF) << (8 * r) for r, v in enumerate(x))
    t = (w ^ (w >> 7)) & 0x00AA00AA00AA00AA
    w = w ^ t ^ (t << 7)
    t = (w ^ (w >> 14)) & 0x0000CCCC0000CCCC
    w = w ^ t ^ (t << 14)
    t = (w ^ (w >> 28)) & 0x00000000F0F0F0F0
    w = w ^ t ^ (t << 28)
    return [(w >> (8 * c)) & 0xFF for c in range(8)]


def _transpose_masks(bitsets: list[int], ncols: int) -> list[int]:
    """把 ``nrows × ncols`` 位矩阵（每行一个大整数）按 8×8 分块转置。

    返回 ``good[k]``：第 k 列在各行的位掩码。8×8 小块用蝴蝶交换转置，
    避免 O(非零位) 的逐位 bit_length 循环。
    """
    nrows = len(bitsets)
    good = [0] * ncols
    for j0 in range(0, nrows, 8):
        block_rows = [
            (bitsets[j0 + r] if j0 + r < nrows else 0) for r in range(8)
        ]
        for k0 in range(0, ncols, 8):
            chunk = [(row >> k0) & 0xFF for row in block_rows]
            cols = _transpose8(chunk)
            for c in range(8):
                if k0 + c < ncols and cols[c]:
                    good[k0 + c] |= cols[c] << j0
    return good


class _CoveredRows:
    """原子集合 s_j 为任意掩码；查询键均为连续区间 ``[a,b]``。

    ``contains_rows(keys)[i]`` 的第 j 位 ⇔ ``keys[i] ⊆ s_j``。
    转置：``good[k]`` 的第 j 位 ⇔ s_j 覆盖坐标格 k；
    则 ``[a,b] ⊆ s_j`` ⇔ 第 j 位在 ``AND_{k=a..b} good[k]`` 中，
    用区间 AND 稀疏表 O(1) 回答。
    """

    __slots__ = ("levels", "_sup")

    def __init__(self, bitsets: list[int]) -> None:
        span = max((m.bit_length() for m in bitsets), default=0)
        good = _transpose_masks(bitsets, span) if span else []
        levels = [good]
        width = 2
        while width <= span:
            prev = levels[-1]
            half = width >> 1
            levels.append(
                [prev[k] & prev[k + half] for k in range(span - width + 1)]
            )
            width <<= 1
        self.levels = levels
        self._sup: dict[int, int] = {}

    def contains_rows(self, keys: list[int]) -> list[int]:
        cache = self._sup
        levels = self.levels
        out: list[int] = []
        for m in keys:
            row = cache.get(m)
            if row is None:
                if not m:
                    row = 0
                else:
                    a = (m & -m).bit_length() - 1
                    b = m.bit_length() - 1
                    length = b - a + 1
                    lv = length.bit_length() - 1
                    tab = levels[lv]
                    step = 1 << lv
                    row = tab[a] & tab[b - step + 1]
                cache[m] = row
            out.append(row)
        return out


def build_graph(layout: UnionLayout, r: int) -> AtomGraph:
    """构造半边长 r 下的可行性原子图。"""
    if r == 0:
        return _build_graph_r0(layout)

    xs, ys = layout.xs, layout.ys
    nx, ny = layout.nx, layout.ny
    full_x, full_y = layout.full_x, layout.full_y

    xr = sorted({v - r for v in xs} | {v + r for v in xs})
    yr = sorted({v - r for v in ys} | {v + r for v in ys})
    nxr, nyr = len(xr) - 1, len(yr) - 1

    # -- 原子 x 开格列（中心 cx ∈ (xr[i],xr[i+1])）-----------------------
    xm_list: list[int] = []   # 正方形内点扫到的并集 x 开格
    xl_list: list[int] = []   # 左边位置扫到的 x 开格
    xr_list: list[int] = []   # 右边
    x_and: list[int] = []
    xl_and: list[int] = []
    xr_and: list[int] = []
    for i in range(nxr):
        a, b = xr[i], xr[i + 1]
        xm = strict_cells(xs, a - r, b + r, nx)
        xm_list.append(xm)
        xl = strict_cells(xs, a - r, b - r, nx)
        xr_ = strict_cells(xs, a + r, b + r, nx)
        xl_list.append(xl)
        xr_list.append(xr_)
        x_and.append(_and_of_bitset(layout.range_and_x, xm))
        xl_and.append(_and_of_bitset(layout.range_and_x, xl))
        xr_and.append(_and_of_bitset(layout.range_and_x, xr_))

    # -- 固定 x 坐标（竖边原子 / 顶点）-----------------------------------
    xe_list: list[int] = []
    xe_and: list[int] = []
    xcl: list[int] = []
    xcr: list[int] = []
    for i in range(nxr + 1):
        a = xr[i]
        xe = strict_cells(xs, a - r, a + r, nx)
        xe_list.append(xe)
        xe_and.append(_and_of_bitset(layout.range_and_x, xe))
        xcl.append(_or_adjacent(full_x, xs, a - r, nx))
        xcr.append(_or_adjacent(full_x, xs, a + r, nx))

    # -- 原子 y 开格行 ----------------------------------------------------
    ym_list: list[int] = []
    yb_and: list[int] = []
    yt_and: list[int] = []
    for j in range(nyr):
        c, d = yr[j], yr[j + 1]
        ym_list.append(strict_cells(ys, c - r, d + r, ny))
        yb_and.append(
            _and_of_bitset(layout.range_and_y,
                           strict_cells(ys, c - r, d - r, ny))
        )
        yt_and.append(
            _and_of_bitset(layout.range_and_y,
                           strict_cells(ys, c + r, d + r, ny))
        )

    # -- 固定 y 坐标 ------------------------------------------------------
    ye_list: list[int] = []
    ycb: list[int] = []
    yct: list[int] = []
    for j in range(nyr + 1):
        b = yr[j]
        ye_list.append(strict_cells(ys, b - r, b + r, ny))
        ycb.append(_or_adjacent(full_y, ys, b - r, ny))
        yct.append(_or_adjacent(full_y, ys, b + r, ny))

    # 四种原子集合对应的批量包含判定。
    # 记号（对开格原子 (i,j)，cx∈A, cy∈D）：
    #   Xm/Ym 正方形内点扫过的并集开格；Xl/Xr 左/右边位置扫过的 x 开格；
    #   Yb/Yt 下/上边扫过的 y 开格（随 cy 或 cx 在原子内变化，均为严格区间）；
    #   L/Rv 固定 x 线处闭邻接 OR；B/T 固定 y 线处闭邻接 OR。
    # 各层包含判定按"原子集合是否连续"选两种实现：
    #   ym/ye 原子随 yr 单调滑动 —— 连续区间，用零段二分（键任意）；
    #   yb_and/yt_and（覆盖 AND）、ycb/yct（邻接 OR）是任意掩码，
    #   查询键 xm/xe/xl/xr 都是连续区间 —— 转置 + 区间 AND 稀疏表。
    map_ym = _IntervalSubsetRows(ym_list, ny)
    map_ye = _IntervalSubsetRows(ye_list, ny)
    map_yb = _CoveredRows(yb_and)
    map_yt = _CoveredRows(yt_and)
    map_ycb = _CoveredRows(ycb)
    map_yct = _CoveredRows(yct)

    # 开格层：角点轨迹是开矩形，已被内点/四条边的开段条件覆盖。
    cell_rows = [
        a & b & c & d & e
        for a, b, c, d, e in zip(
            map_ym.subset_rows(x_and),
            map_ym.subset_rows(xl_and),
            map_ym.subset_rows(xr_and),
            map_yb.contains_rows(xm_list),
            map_yt.contains_rows(xm_list),
        )
    ]
    # 竖边层：cx 固定。角点轨迹是竖开段，Ym⊆L/Rv 已含 Yb/Yt。
    v_rows = [
        a & b & c & d & e
        for a, b, c, d, e in zip(
            map_ym.subset_rows(xe_and),
            map_ym.subset_rows(xcl),
            map_ym.subset_rows(xcr),
            map_yb.contains_rows(xe_list),
            map_yt.contains_rows(xe_list),
        )
    ]
    # 横边层：cy 固定。除边开段外，角点轨迹是 Xl/Xr 上的横开段，
    # 必须 Xl⊆B,T 与 Xr⊆B,T（内点列 Xm 管不到边位的极端 x）。
    h_rows = [
        a & b & c & d & e & f & g & h & i
        for a, b, c, d, e, f, g, h, i in zip(
            map_ye.subset_rows(x_and),
            map_ye.subset_rows(xl_and),
            map_ye.subset_rows(xr_and),
            map_ycb.contains_rows(xm_list),
            map_yct.contains_rows(xm_list),
            map_ycb.contains_rows(xl_list),
            map_yct.contains_rows(xl_list),
            map_ycb.contains_rows(xr_list),
            map_yct.contains_rows(xr_list),
        )
    ]
    # 顶点层：四条边用严格掩码；四个角点是固定点，逐一做 2×2 闭邻接检查。
    p_rows = [
        a & b & c & d & e
        for a, b, c, d, e in zip(
            map_ye.subset_rows(xe_and),
            map_ye.subset_rows(xcl),
            map_ye.subset_rows(xcr),
            map_ycb.contains_rows(xe_list),
            map_yct.contains_rows(xe_list),
        )
    ]
    # 固定 y 处角点的 y 向闭邻接位只依赖 j，先预计算（勿在 i×j 内 bisect）。
    corner_yb = [_closed_adjacent_bits(ys, yr[j] - r, ny)
                 for j in range(nyr + 1)]
    corner_yt = [_closed_adjacent_bits(ys, yr[j] + r, ny)
                 for j in range(nyr + 1)]
    j_bits = [1 << j for j in range(nyr + 1)]
    corner_cache: dict[tuple[int, int], int] = {}
    for i in range(nxr + 1):
        row = p_rows[i]
        if not row:
            continue
        # xcl/xcr 是该固定 x 处闭邻接开格覆盖的 OR（y 掩码）。
        key = (xcl[i], xcr[i])
        good = corner_cache.get(key)
        if good is None:
            cov_l, cov_r = key
            good = 0
            for j in range(nyr + 1):
                if (
                    (cov_l & corner_yb[j])
                    and (cov_l & corner_yt[j])
                    and (cov_r & corner_yb[j])
                    and (cov_r & corner_yt[j])
                ):
                    good |= j_bits[j]
            corner_cache[key] = good
        p_rows[i] = row & good

    return _assemble_graph(xr, yr, cell_rows, v_rows, h_rows, p_rows)


def _assemble_graph(
    xr: list[int],
    yr: list[int],
    cell_rows: list[int],
    v_rows: list[int],
    h_rows: list[int],
    p_rows: list[int],
) -> AtomGraph:
    nxr, nyr = len(xr) - 1, len(yr) - 1
    sc = ((nyr + 7) // 8) * 8
    sh = ((nyr + 1 + 7) // 8) * 8
    cb, hb = sc // 8, sh // 8
    c0 = 0
    v0 = c0 + nxr * cb
    h0 = v0 + (nxr + 1) * cb
    p0 = h0 + nxr * hb
    total = (p0 + (nxr + 1) * hb) * 8
    flags = bytearray(total // 8)

    def fill(base_bytes: int, row_bytes: int, rows: list[int]) -> None:
        for i, mask in enumerate(rows):
            flags[base_bytes + i * row_bytes:
                  base_bytes + (i + 1) * row_bytes] = mask.to_bytes(
                row_bytes, "little"
            )

    fill(c0, cb, cell_rows)
    fill(v0, cb, v_rows)
    fill(h0, hb, h_rows)
    fill(p0, hb, p_rows)

    return AtomGraph(xr, yr, flags, nxr, nyr, c0 * 8, v0 * 8, h0 * 8,
                     p0 * 8, sc, sh, total)


def _build_graph_r0(layout: UnionLayout) -> AtomGraph:
    """r=0：正方形退化为点，可行性即闭集归属；角点相接可通行。"""
    xs, ys = layout.xs, layout.ys
    nx, ny = layout.nx, layout.ny
    cover = layout.cover
    graph = _assemble_graph(list(xs), list(ys),
                            [0] * nx, [0] * (nx + 1),
                            [0] * nx, [0] * (nx + 1))

    def mark(node: int) -> None:
        graph.flags[node >> 3] |= 1 << (node & 7)

    for i in range(nx):
        for j in range(ny):
            if cover[i][j]:
                mark(graph.cell(i, j))
    for i in range(nx + 1):
        for j in range(ny):
            if (i > 0 and cover[i - 1][j]) or (i < nx and cover[i][j]):
                mark(graph.vseg(i, j))
    for i in range(nx):
        for j in range(ny + 1):
            if (j > 0 and cover[i][j - 1]) or (j < ny and cover[i][j]):
                mark(graph.hseg(i, j))
    for i in range(nx + 1):
        for j in range(ny + 1):
            if (
                (i > 0 and j > 0 and cover[i - 1][j - 1])
                or (i < nx and j > 0 and cover[i][j - 1])
                or (i > 0 and j < ny and cover[i - 1][j])
                or (i < nx and j < ny and cover[i][j])
            ):
                mark(graph.vert(i, j))
    return graph


# --------------------------------------------------------------------------
# 原子定位、洪泛连通与折线重建
# --------------------------------------------------------------------------


def locate_atom(graph: AtomGraph, x: int, y: int) -> int:
    """返回整数点 (x,y) 所在原子节点编号；点在图域外抛 LookupError。"""
    xr, yr = graph.xs, graph.ys
    px = bisect_left(xr, x)
    on_x = px < len(xr) and xr[px] == x
    if not on_x:
        px -= 1  # 严格落在开格 px 内：coords[px] < x < coords[px+1]
        if not (0 <= px < graph.nxr):
            raise LookupError("x out of atom grid")
    py = bisect_left(yr, y)
    on_y = py < len(yr) and yr[py] == y
    if not on_y:
        py -= 1
        if not (0 <= py < graph.nyr):
            raise LookupError("y out of atom grid")

    if on_x and on_y:
        return graph.vert(px, py)
    if on_x:
        return graph.vseg(px, py)
    if on_y:
        return graph.hseg(px, py)
    return graph.cell(px, py)


def _expand_into(graph: AtomGraph, node: int, parent: "array",
                 queue: "array", flags: bytearray) -> None:
    """洪泛热路径：按原子层内联计算邻居并入队（避免逐边生成器开销）。"""
    nxr, nyr = graph.nxr, graph.nyr
    sc, sh = graph.sc, graph.sh
    c0, v0, h0, p0 = graph.c0, graph.v0, graph.h0, graph.p0

    def push(n: int) -> None:
        if flags[n >> 3] & (1 << (n & 7)) and parent[n] == -1:
            parent[n] = node
            queue.append(n)

    if node < v0:
        k = node - c0
        i, j = divmod(k, sc)
        push(v0 + i * sc + j)
        push(v0 + (i + 1) * sc + j)
        push(h0 + i * sh + j)
        push(h0 + i * sh + (j + 1))
    elif node < h0:
        k = node - v0
        i, j = divmod(k, sc)
        if i > 0:
            push(c0 + (i - 1) * sc + j)
        if i < nxr:
            push(c0 + i * sc + j)
        push(p0 + i * sh + j)
        push(p0 + i * sh + (j + 1))
    elif node < p0:
        k = node - h0
        i, j = divmod(k, sh)
        if j > 0:
            push(c0 + i * sc + (j - 1))
        if j < nyr:
            push(c0 + i * sc + j)
        push(p0 + i * sh + j)
        push(p0 + (i + 1) * sh + j)
    else:
        k = node - p0
        i, j = divmod(k, sh)
        if j > 0:
            push(v0 + i * sc + (j - 1))
        if j < nyr:
            push(v0 + i * sc + j)
        if i > 0:
            push(h0 + (i - 1) * sh + j)
        if i < nxr:
            push(h0 + i * sh + j)


def bfs_path(graph: AtomGraph, start: int, goal: int):
    """可行原子关联图洪泛；返回自 goal 至 start 的父链，不通返回 None。"""
    flags = graph.flags
    if not (flags[start >> 3] & (1 << (start & 7))):
        return None
    if not (flags[goal >> 3] & (1 << (goal & 7))):
        return None
    if start == goal:
        return [start]
    parent = array("i", [-1]) * graph.total
    parent[start] = start
    queue = array("i", [start])
    head = 0
    while head < len(queue):
        node = queue[head]
        head += 1
        _expand_into(graph, node, parent, queue, flags)
        if parent[goal] != -1:
            chain = [goal]
            while chain[-1] != start:
                chain.append(parent[chain[-1]])
            return chain
    return None


def _row_masks(graph: AtomGraph):
    """从扁平标志字节还原四层"每行一个大整数位掩码"。"""
    nxr, nyr = graph.nxr, graph.nyr
    sc, sh = graph.sc // 8, graph.sh // 8
    c0, v0, h0, p0 = graph.c0 // 8, graph.v0 // 8, graph.h0 // 8, graph.p0 // 8
    flags = graph.flags

    def read(base: int, row_bytes: int, i: int) -> int:
        a = base + i * row_bytes
        return int.from_bytes(flags[a:a + row_bytes], "little")

    fc = [read(c0, sc, i) for i in range(nxr)]
    fv = [read(v0, sc, i) for i in range(nxr + 1)]
    fh = [read(h0, sh, i) for i in range(nxr)]
    fp = [read(p0, sh, i) for i in range(nxr + 1)]
    return fc, fv, fh, fp


def _spread32(chunk: int) -> int:
    """把 32 位输入展开到 64 位的偶数位（Morton expand）。"""
    chunk &= 0xFFFFFFFF
    chunk = (chunk | chunk << 16) & 0x0000FFFF0000FFFF
    chunk = (chunk | chunk << 8) & 0x00FF00FF00FF00FF
    chunk = (chunk | chunk << 4) & 0x0F0F0F0F0F0F0F0F
    chunk = (chunk | chunk << 2) & 0x3333333333333333
    chunk = (chunk | chunk << 1) & 0x5555555555555555
    return chunk


def _interleave(lo_mask: int, hi_mask: int, n: int) -> int:
    """交错成 ``a0,b0,a1,b1,...`` 位序列（a 有 n+1 位、b 有 n 位）。

    每 32 个输入位一块做 64 位 Morton 展开，块间偏移 64 位，支持任意长度。
    """
    out = 0
    shift = 0
    while lo_mask or hi_mask:
        out |= _spread32(lo_mask) << shift
        out |= _spread32(hi_mask) << (shift + 1)
        lo_mask >>= 32
        hi_mask >>= 32
        shift += 64
    return out


def _axis_closure(w: int, feasible: int, length: int) -> int:
    """种子 w 沿交错位序列上的可行连续段做闭包（无预计算表）。

    位 k 所在连续段 [lo,hi]：
      lo = 低于 k 的最高零位 + 1（无则 0）；
      hi = 高于 k 的最低零位 - 1（无则 length-1）。
    每次只展开 w 实际落入的少数几个段，复杂度与种子段数成正比。
    """
    w &= feasible
    zeros = ~feasible
    top_mask = (1 << length) - 1
    out = 0
    while w:
        k = (w & -w).bit_length() - 1
        below = zeros & ((1 << k) - 1)
        lo = below.bit_length()
        above = zeros & top_mask & ~((1 << (k + 1)) - 1)
        hi = (above & -above).bit_length() - 2 if above else length - 1
        run = ((1 << (hi - lo + 1)) - 1) << lo
        out |= run
        w &= ~run
    return out


def flood_connected(graph: AtomGraph, start: int, goal: int) -> bool:
    """只判连通：交错位序列 + 倍增闭包 + 行间扫描洪泛。

    同一 i 列上的相邻关系沿 j 形成一条链：
      竖边链 ``p(i,0)-v(i,0)-p(i,1)-v(i,1)-…``（交错成大整数 P_i）；
      开格链 ``h(i,0)-c(i,0)-h(i,1)-c(i,1)-…``（交错成 Q_i）。
    行内链用倍增位移做无向连通闭包（O(log nyr) 次大整数运算）；
    行间关系在交错位上是**同位**耦合：
      P_i 与 Q_i、Q_{i-1} 同位相连；Q_i 与 P_i、P_{i+1} 同位相连。
    行间做正/反向扫描到不动点；异常慢情形回退逐节点 BFS。
    """
    flags = graph.flags
    if not (flags[start >> 3] & (1 << (start & 7))):
        return False
    if not (flags[goal >> 3] & (1 << (goal & 7))):
        return False
    if start == goal:
        return True

    nxr, nyr = graph.nxr, graph.nyr
    fc, fv, fh, fp = _row_masks(graph)
    plen = 2 * nyr + 1

    P = [_interleave(fp[i], fv[i], nyr) for i in range(nxr + 1)]
    Q = [_interleave(fh[i], fc[i], nyr) for i in range(nxr)]
    reached_P = [0] * (nxr + 1)
    reached_Q = [0] * nxr

    c0, v0, h0, p0 = graph.c0, graph.v0, graph.h0, graph.p0
    sc, sh = graph.sc, graph.sh
    if start < v0:
        i, j = divmod(start - c0, sc)
        reached_Q[i] |= 1 << (2 * j + 1)          # c(i,j) 在奇位
    elif start < h0:
        i, j = divmod(start - v0, sc)
        reached_P[i] |= 1 << (2 * j + 1)          # v(i,j) 在奇位
    elif start < p0:
        i, j = divmod(start - h0, sh)
        reached_Q[i] |= 1 << (2 * j)              # h(i,j) 在偶位
    else:
        i, j = divmod(start - p0, sh)
        reached_P[i] |= 1 << (2 * j)              # p(i,j) 在偶位

    def close_all() -> None:
        for i in range(nxr + 1):
            reached_P[i] = _axis_closure(reached_P[i], P[i], plen)
        for i in range(nxr):
            reached_Q[i] = _axis_closure(reached_Q[i], Q[i], plen)

    def forward() -> bool:
        changed = False
        for i in range(nxr + 1):
            w = reached_P[i]
            w |= reached_Q[i] if i < nxr else 0
            w |= reached_Q[i - 1] if i > 0 else 0
            w = _axis_closure(w, P[i], plen)
            if w != reached_P[i]:
                reached_P[i] = w
                changed = True
            if i < nxr:
                w = reached_Q[i] | reached_P[i]
                if i + 1 <= nxr:
                    w |= reached_P[i + 1]
                w = _axis_closure(w, Q[i], plen)
                if w != reached_Q[i]:
                    reached_Q[i] = w
                    changed = True
        return changed

    def backward() -> bool:
        changed = False
        for i in range(nxr, -1, -1):
            w = reached_P[i]
            w |= reached_Q[i] if i < nxr else 0
            w |= reached_Q[i - 1] if i > 0 else 0
            w = _axis_closure(w, P[i], plen)
            if w != reached_P[i]:
                reached_P[i] = w
                changed = True
            if i < nxr:
                w = reached_Q[i] | reached_P[i]
                if i + 1 <= nxr:
                    w |= reached_P[i + 1]
                w = _axis_closure(w, Q[i], plen)
                if w != reached_Q[i]:
                    reached_Q[i] = w
                    changed = True
        return changed

    close_all()
    max_sweeps = 2 * (nxr + 1) + 2
    sweeps = 0
    while sweeps < max_sweeps:
        f = forward()
        b = backward()
        sweeps += 1
        if not f and not b:
            break
    else:
        return bfs_path(graph, start, goal) is not None

    if goal < v0:
        i, j = divmod(goal - c0, sc)
        return bool(reached_Q[i] & (1 << (2 * j + 1)))
    if goal < h0:
        i, j = divmod(goal - v0, sc)
        return bool(reached_P[i] & (1 << (2 * j + 1)))
    if goal < p0:
        i, j = divmod(goal - h0, sh)
        return bool(reached_Q[i] & (1 << (2 * j)))
    i, j = divmod(goal - p0, sh)
    return bool(reached_P[i] & (1 << (2 * j)))



def _anchor(graph: AtomGraph, node: int, cur: tuple[int, int]) -> tuple[int, int]:
    """进入原子后取的整数代表点（在上一点基础上夹到该原子闭包内）。"""
    x, y = cur
    v0, h0, p0 = graph.v0, graph.h0, graph.p0
    if node < v0:
        return x, y
    if node < h0:
        i, j = divmod(node - v0, graph.sc)
        ylo, yhi = graph.ys[j], graph.ys[j + 1]
        y = min(max(y, ylo), yhi)
        return graph.xs[i], y
    if node < p0:
        i, j = divmod(node - h0, graph.sh)
        xlo, xhi = graph.xs[i], graph.xs[i + 1]
        x = min(max(x, xlo), xhi)
        return x, graph.ys[j]
    i, j = divmod(node - p0, graph.sh)
    return graph.xs[i], graph.ys[j]


def reconstruct_polyline(
    graph: AtomGraph,
    chain: list[int],
    start_xy: tuple[int, int],
    end_xy: tuple[int, int],
) -> list[tuple[int, int]]:
    """把 BFS 节点链转成水平/竖直整数折线（相邻点共享 x 或 y）。"""
    points: list[tuple[int, int]] = [start_xy]
    cur = start_xy
    for node in reversed(chain[1:-1]):
        nxt = _anchor(graph, node, cur)
        if nxt[0] != cur[0] and nxt[1] != cur[1]:
            bend = (nxt[0], cur[1])
            points.append(bend)
            cur = bend
        if nxt != cur:
            points.append(nxt)
            cur = nxt
    if end_xy != cur:
        if end_xy[0] != cur[0] and end_xy[1] != cur[1]:
            bend = (end_xy[0], cur[1])
            points.append(bend)
            cur = bend
        points.append(end_xy)
    return points


def _segment_atoms(graph: AtomGraph, p0: tuple[int, int], p1: tuple[int, int]):
    """枚举闭折线段经过的全部原子（端点原子、内部开格、跨越的边界原子）。"""
    xr, yr = graph.xs, graph.ys
    nxr, nyr = graph.nxr, graph.nyr
    x0, y0 = p0
    x1, y1 = p1

    if y0 == y1:
        lo, hi = sorted((x0, x1))
        py = bisect_left(yr, y0)
        on_y = py < len(yr) and yr[py] == y0
        if not on_y:
            jy = bisect_right(yr, y0) - 1
            if not 0 <= jy < nyr:
                return
        # 内部与 (lo,hi) 相交的原子 x 开格列（同 strict 语义）。
        i_first = max(bisect_right(xr, lo) - 1, 0)
        i_last = min(bisect_left(xr, hi) - 1, nxr - 1)
        k_lo = bisect_left(xr, lo)
        if k_lo < len(xr) and xr[k_lo] == lo:
            yield graph.vert(k_lo, py) if on_y else graph.vseg(k_lo, jy)
        if i_first <= i_last:
            for i in range(i_first, i_last + 1):
                yield graph.hseg(i, py) if on_y else graph.cell(i, jy)
            for t in range(i_first + 1, i_last + 1):
                yield graph.vert(t, py) if on_y else graph.vseg(t, jy)
        k_hi = bisect_left(xr, hi)
        if hi != lo and k_hi < len(xr) and xr[k_hi] == hi:
            yield graph.vert(k_hi, py) if on_y else graph.vseg(k_hi, jy)

    elif x0 == x1:
        lo, hi = sorted((y0, y1))
        px = bisect_left(xr, x0)
        on_x = px < len(xr) and xr[px] == x0
        if not on_x:
            ix = bisect_right(xr, x0) - 1
            if not 0 <= ix < nxr:
                return
        j_first = max(bisect_right(yr, lo) - 1, 0)
        j_last = min(bisect_left(yr, hi) - 1, nyr - 1)
        k_lo = bisect_left(yr, lo)
        if k_lo < len(yr) and yr[k_lo] == lo:
            yield graph.vert(px, k_lo) if on_x else graph.hseg(ix, k_lo)
        if j_first <= j_last:
            for j in range(j_first, j_last + 1):
                yield graph.vseg(px, j) if on_x else graph.cell(ix, j)
            for t in range(j_first + 1, j_last + 1):
                yield graph.vert(px, t) if on_x else graph.hseg(ix, t)
        k_hi = bisect_left(yr, hi)
        if hi != lo and k_hi < len(yr) and yr[k_hi] == hi:
            yield graph.vert(px, k_hi) if on_x else graph.hseg(ix, k_hi)


def verify_polyline(
    graph: AtomGraph,
    points: list[tuple[int, int]],
    start_xy: tuple[int, int],
    end_xy: tuple[int, int],
) -> bool:
    """内部复查：每段水平/竖直、非退化，途经原子全部标记可行。"""
    if not points or points[0] != start_xy or points[-1] != end_xy:
        return False
    if len(points) == 1:
        return start_xy == end_xy
    for p0, p1 in zip(points, points[1:]):
        if p0 == p1:
            return False
        if p0[0] != p1[0] and p0[1] != p1[1]:
            return False
        touched = list(_segment_atoms(graph, p0, p1))
        if not touched or any(not graph.feasible(n) for n in touched):
            return False
    return True


# --------------------------------------------------------------------------
# 单点净空（用于压缩二分上界）
# --------------------------------------------------------------------------


def point_feasible(layout: UnionLayout, x: int, y: int, r: int) -> bool:
    """固定整数中心 (x,y) 处闭正方形是否完全包含于并集。

    与顶点原子同一判据：内点开格全覆盖 + 四条边开段闭邻接 OR 覆盖 +
    四个角点的 2×2 闭邻接块各有覆盖。r=0 退化为闭集点归属。
    """
    if r == 0:
        return layout.contains(x, y)
    xs, ys, nx, ny = layout.xs, layout.ys, layout.nx, layout.ny
    full_x, full_y = layout.full_x, layout.full_y

    xm = strict_cells(xs, x - r, x + r, nx)
    ym = strict_cells(ys, y - r, y + r, ny)
    if not xm or not ym:
        return False
    if ym & ~_and_of_bitset(layout.range_and_x, xm):
        return False
    left = _or_adjacent(full_x, xs, x - r, nx)
    right = _or_adjacent(full_x, xs, x + r, nx)
    bot = _or_adjacent(full_y, ys, y - r, ny)
    top = _or_adjacent(full_y, ys, y + r, ny)
    if ym & ~left or ym & ~right:
        return False
    if xm & ~bot or xm & ~top:
        return False
    ybb = _closed_adjacent_bits(ys, y - r, ny)
    ytb = _closed_adjacent_bits(ys, y + r, ny)
    # 四个角点：x 侧邻接格覆盖 OR（left/right）与 y 侧相邻格位相交。
    return bool(
        (left & ybb) and (left & ytb) and (right & ybb) and (right & ytb)
    )


def point_max_r(layout: UnionLayout, x: int, y: int, cap: int) -> int:
    """单点（中心）允许的最大 r；可行性关于 r 单调，直接二分。"""
    lo, hi = 0, cap
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if point_feasible(layout, x, y, mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


# --------------------------------------------------------------------------
# 顶层求解
# --------------------------------------------------------------------------


@dataclass
class ClearanceResult:
    max_r: int
    path: list[tuple[int, int]]


def maximum_clearance(
    rects: list[Rect], a: tuple[int, int], b: tuple[int, int]
) -> ClearanceResult:
    """求最大半边长 r 与可复查折线；取样点不在并集 / r=0 不可达即失败。"""
    layout = UnionLayout(rects)
    if not layout.contains(*a):
        raise GeometryError(
            f"start sample point {a} is not inside the rectangle union "
            "(boundary included)",
            {"point": "start", "x": a[0], "y": a[1]},
            code="sample_not_in_union",
        )
    if not layout.contains(*b):
        raise GeometryError(
            f"end sample point {b} is not inside the rectangle union "
            "(boundary included)",
            {"point": "end", "x": b[0], "y": b[1]},
            code="sample_not_in_union",
        )

    def try_r(r: int):
        graph = build_graph(layout, r)
        try:
            na = locate_atom(graph, *a)
            nb = locate_atom(graph, *b)
        except LookupError:
            return None
        return graph if flood_connected(graph, na, nb) else None

    if try_r(0) is None:
        raise GeometryError(
            "sample points are not connected in the union even for r=0 "
            "(corner contact is passable only at the touching point itself)",
            None,
            code="no_clearance_path",
        )

    bbox_cap = min(
        (layout.xs[-1] - layout.xs[0]) // 2,
        (layout.ys[-1] - layout.ys[0]) // 2,
    )
    cap = min(
        bbox_cap,
        point_max_r(layout, a[0], a[1], bbox_cap),
        point_max_r(layout, b[0], b[1], bbox_cap),
    )

    lo, hi = 0, cap
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if try_r(mid) is not None:
            lo = mid
        else:
            hi = mid - 1
    r = lo

    graph = build_graph(layout, r)
    na = locate_atom(graph, *a)
    nb = locate_atom(graph, *b)
    chain = bfs_path(graph, na, nb)
    assert chain is not None
    path = reconstruct_polyline(graph, chain, a, b)
    if not verify_polyline(graph, path, a, b):
        raise GeometryError(
            "internal path verification failed", None, code="internal_error"
        )
    return ClearanceResult(r, path)


# --------------------------------------------------------------------------
# 请求校验 / 入口适配
# --------------------------------------------------------------------------


def _parse_point(value, name: str) -> tuple[int, int]:
    loc = {"point": name}
    if not isinstance(value, list) or len(value) != 2:
        raise GeometryError(
            f"'{name}' must be a [x, y] array of two integers",
            loc,
            code="invalid_sample_point",
        )
    coords = []
    for axis, v in zip(("x", "y"), value):
        if isinstance(v, bool) or not isinstance(v, int):
            raise GeometryError(
                f"'{name}[{axis}]' must be an integer",
                {**loc, "axis": axis},
                code="invalid_sample_point",
            )
        if abs(v) > COORD_BOUNDS:
            raise GeometryError(
                f"'{name}[{axis}]'={v} out of range [-1e9, 1e9]",
                {**loc, "axis": axis},
                code="invalid_sample_point",
            )
        coords.append(v)
    return coords[0], coords[1]


def clearance_audit_raw(payload: object) -> dict:
    """校验并执行净空复核，返回可序列化结果。

    请求体::

        {"rectangles": [ ... 与 /api/audit 同构，至多 180 条 ... ],
         "start": [x, y], "end": [x, y]}
    """
    if not isinstance(payload, dict):
        raise GeometryError(
            "request body must be an object with 'rectangles', 'start' and 'end'",
            None,
            code="bad_request",
        )
    if "rectangles" not in payload:
        raise GeometryError(
            "missing 'rectangles' array", None, code="bad_request"
        )
    if "start" not in payload or "end" not in payload:
        raise GeometryError(
            "missing 'start' and 'end' sample points",
            None,
            code="bad_request",
        )

    rects = validate_rectangles(
        payload["rectangles"], min_count=1, max_count=MAX_RECTS
    )
    start = _parse_point(payload["start"], "start")
    end = _parse_point(payload["end"], "end")

    result = maximum_clearance(rects, start, end)
    return {
        "max_clearance": result.max_r,
        "start": [start[0], start[1]],
        "end": [end[0], end[1]],
        "path": [[x, y] for x, y in result.path],
    }

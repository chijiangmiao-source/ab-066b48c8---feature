# 光刻版缺陷复核服务（photomask-defect-audit）

对轴对齐污染框集合计算**并集面积**与**外露周长**。重叠、相切、完全包围
都只计一次；内部接缝（含覆盖 2→1 的缝）不计入清洗边界。

## 接口

### `POST /api/audit`

请求体为 1–50000 个矩形的 JSON 数组（也接受 `{"rectangles": [...]}`）：

```json
[
  {"id": "a", "x1": 0, "y1": 0, "x2": 3, "y2": 2},
  {"id": "b", "x1": 1, "y1": 1, "x2": 4, "y2": 3}
]
```

约束：`id` 为非空字符串且**全局唯一**（几何重复允许、标识重复拒绝）；
四个坐标为 `|v| ≤ 1e9` 的整数，且 `x1 < x2`、`y1 < y2`。

成功 `200`（结果以十进制字符串返回，任意精度）：

```json
{"area": "10", "perimeter": "14"}
```

失败 `400`：带输入位置的稳定错误，**不夹带任何部分结果**：

```json
{
  "error": {
    "code": "invalid_rectangle",
    "message": "rectangles[1]: duplicate id 'x' (id must be unique)",
    "location": {"index": 1, "id": "x"}
  }
}
```

### `POST /api/clearance-audit`

在原审计流程旁新增的**净空复核**入口：请求体为对象，矩形载荷与
`/api/audit` 同构，但**至多 180 个**，并给出两个整数取样点：

```json
{
  "rectangles": [
    {"id": "a", "x1": 0, "y1": 0, "x2": 6, "y2": 6}
  ],
  "start": [2, 3],
  "end": [4, 3]
}
```

求最大的非负整数半边长 `r`：轴对齐、边长 `2r`（`r=0` 退化为点）的方形
喷头，中心沿**水平/竖直连续折线**从 `start` 移到 `end`，路径上任一位置
的闭正方形 `[cx-r,cx+r] × [cy-r,cy+r]` 都必须**完全包含于矩形并集**。

矩形边界、并集内孔洞壁、取样点恰落在边界上全部按**同一闭集**语义处理；
`r=0` 时仅角点相接的两个矩形可在接触点通行，任何 `r>0` 都不能借角点
穿越。成功 `200`：

```json
{
  "max_clearance": 2,
  "start": [2, 3],
  "end": [4, 3],
  "path": [[2, 3], [4, 3]]
}
```

`path` 为可复查的整数折线：相邻点共享 x 或 y，服务端已逐段枚举途经原子
回查全部可行。失败 `400`（稳定错误码，不夹带部分结果）：

| code | 含义 |
| --- | --- |
| `invalid_rectangle` | 矩形载荷非法（带 `location`，同 `/api/audit`；含超过 180 个） |
| `invalid_sample_point` | 取样点不是两个整数（或越界） |
| `sample_not_in_union` | 取样点不在并集内（闭集，边界算在内），`location.point` 指明 start/end |
| `no_clearance_path` | 两点在 `r=0` 下也不可达 |

### `GET /healthz`

仅当**请求校验器**与**扫描引擎**两个组件都完成启动自检并就绪时返回
`200 {"status":"ok", ...}`，否则 `503`。Docker 健康检查即探测此端点。

## 算法

横坐标归并进入/离开事件；纵坐标压缩后用线段树同步维护**覆盖计数、
覆盖总长、连续覆盖段数**（O(n log n)，5 万矩形 < 1s）。同一横坐标的
混合事件整体裁决：进入边在整组应用前的树上、离开边在整组应用后的
树上，查询该边 y 区间内"外侧未覆盖长度"作为外露竖直边——共边与内部
接缝自然计 0，仅角点接触的边也不会被吞掉。面积 = Σ 覆盖总长 × 板宽；
水平边 = Σ 2 × 连续段数 × 板宽。不铺开单位网格、不逐对切割矩形、
不调用几何求解库（纯标准库，零第三方依赖）。

### 净空复核（clearance）

正方形可行性只在中心平面的**原子划分**（开格/边/顶点）上恒定：用
`{xs[k]±r} × {ys[k]±r}` 再做一次坐标压缩，把"正方形内点 + 四条边 +
四个角点"化约为覆盖位掩码的包含判定（开格全覆盖；边内点查闭邻接 OR；
固定角点查 2×2 邻接块）。`r>0` 时开格内点必须全覆盖，因此角点漏洞无法
穿越；`r=0` 单独按闭集归属构图，角点接触点自然可通。连通性在原子关联
图上用交错位序列（Morton 展开）+ 连续段闭包 + 行间扫描做洪泛；对 r
二分求最大整数，最终再用逐节点 BFS 父链**重建并回查**水平/竖直整数折线。
全程坐标压缩，没有单位网格、逐对切割或几何库。

## 运行

```bash
# Docker（宿主机端口可配置，默认 8080）
AUDIT_HOST_PORT=9090 docker compose up --build audit

# 一次性验证：跑完即退出，退出码即结果（0 通过 / 1 失败）
docker compose up --build --exit-code-from verify verify

# 本地（无需 Docker，Python ≥ 3.11）
python3 -m app.server                 # AUDIT_PORT 可改端口
python3 -m unittest discover -s tests # 代码测试
python3 verify/run_verifier.py        # 完整验证（需服务已启动）
```

verify 服务依次执行：代码测试（unittest 全量）→ 构建检查（compileall）
→ 等待审计服务健康 → API/HTTP 冒烟（重叠框面积 10 周长 14、相邻方框
不计公共边、重复框不增量、重复标识/非法矩形带位置拒绝且无部分结果），
随后退出并以退出码报告结果。

## 目录

```
app/geometry.py     扫描线引擎 + 请求校验（核心，纯标准库）
app/components.py   组件注册表与启动自检（健康检查依据）
app/server.py       HTTP 服务（ThreadingHTTPServer）
tests/              单元 / 随机对照（网格预言机）/ 端到端 HTTP 测试
verify/             一次性验证服务
Dockerfile          审计接口镜像（含 HEALTHCHECK）
docker-compose.yaml audit + verify 编排
```

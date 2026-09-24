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

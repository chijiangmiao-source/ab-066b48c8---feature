"""服务组件与就绪状态。

健康检查只有在"请求校验器"和"扫描引擎"两个组件都完成启动自检后
才报告就绪。自检用极小的确定性样本，失败则该组件保持未就绪。
"""

from __future__ import annotations

import threading
from typing import Callable

from .geometry import GeometryError, Rect, audit_raw, audit_rectangles


class Component:
    def __init__(self, name: str, selftest: Callable[[], None]) -> None:
        self.name = name
        self._selftest = selftest
        self._ready = False
        self._error: str | None = None

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def error(self) -> str | None:
        return self._error

    def start(self) -> None:
        try:
            self._selftest()
        except Exception as exc:  # 自检失败保持未就绪
            self._error = repr(exc)
            self._ready = False
        else:
            self._ready = True


def _validator_selftest() -> None:
    # 合法样本必须通过；非法样本必须被带位置拒绝。
    area, perimeter = audit_raw(
        [{"id": "self", "x1": 0, "y1": 0, "x2": 1, "y2": 1}]
    )
    if (area, perimeter) != ("1", "4"):
        raise AssertionError("validator selftest mismatch")
    try:
        audit_raw([{"id": "x", "x1": 1, "y1": 0, "x2": 1, "y2": 1}])
    except GeometryError:
        pass
    else:
        raise AssertionError("validator failed to reject degenerate rect")


def _engine_selftest() -> None:
    # 验收构型：重叠框 -> 面积 10、周长 14。
    area, perimeter = audit_rectangles(
        [Rect("a", 0, 0, 3, 2), Rect("b", 1, 1, 4, 3)]
    )
    if (area, perimeter) != (10, 14):
        raise AssertionError(f"engine selftest mismatch: {area=} {perimeter=}")


class ComponentRegistry:
    def __init__(self) -> None:
        self.validator = Component("request-validator", _validator_selftest)
        self.scan_engine = Component("scan-engine", _engine_selftest)
        self._lock = threading.Lock()
        self._started = False

    def start_all(self) -> None:
        with self._lock:
            self.validator.start()
            self.scan_engine.start()
            self._started = True

    def status(self) -> tuple[bool, dict[str, dict[str, object]]]:
        """返回 (全部就绪, 各组件状态)。"""
        components = {
            c.name: {"ready": c.ready, **({"error": c.error} if c.error else {})}
            for c in (self.validator, self.scan_engine)
        }
        return all(c["ready"] for c in components.values()), components


registry = ComponentRegistry()

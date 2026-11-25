"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

在途报告取数快照（inflight_snapshots）是独立于模块表的领域台账：
周报一旦领取图表数据，就把真实图表版本、覆盖范围和数据值冻结成快照，
图表后续下架或改版不会影响已领取的在途报告。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 在途报告取数快照台账：snapshot_id -> 快照记录
        self._inflight_snapshots: dict[int, dict[str, Any]] = {}
        # 各领域独立序列，避免和模块记录主键混用
        self._sequences: dict[str, int] = {
            "inflight_snapshot": 0,
            "issue_no": 0,
            "receipt": 0,
            "event": 0,
        }

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    # ---- 在途报告取数快照台账 ----
    def next_id(self, sequence: str) -> int:
        """生成领域内自增序列（快照号、发行编号、回执号、事件号）。"""
        current = self._sequences.get(sequence, 0) + 1
        self._sequences[sequence] = current
        return current

    def save_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """写入或更新一份在途报告取数快照。"""
        snapshot_id = int(snapshot["snapshot_id"])
        self._inflight_snapshots[snapshot_id] = snapshot
        return snapshot

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        return self._inflight_snapshots.get(int(snapshot_id))

    def list_snapshots(
        self, *, task_id: int | None = None, chart_id: int | None = None,
        status: str | None = None, issue_no: str | None = None,
    ) -> list[dict[str, Any]]:
        items = list(self._inflight_snapshots.values())
        if task_id is not None:
            items = [item for item in items if int(item.get("task_id")) == int(task_id)]
        if chart_id is not None:
            items = [item for item in items if int(item.get("chart_id")) == int(chart_id)]
        if status is not None:
            items = [item for item in items if item.get("status") == status]
        if issue_no is not None:
            items = [item for item in items if item.get("issue_no") == issue_no]
        return sorted(items, key=lambda item: int(item["snapshot_id"]))

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()

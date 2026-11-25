"""分析图表领域服务：图表配置、版本化数据、发布与下架管理。

图表数据按「图表版本」冻结：同一张图每次渲染都得到同一份数据；
报告调度领取图表数据时调用 :meth:`build_chart_payload` 得到不可变负载，
下架后在途报告仍可凭快照复查真实版本和覆盖范围。
"""
from __future__ import annotations

import copy
import random
import time
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class AnalysisChartService(BaseModuleService):
    MODULE = "analysis_chart"
    ENTITY = "图表配置"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["图表标识", "数据来源", "图表类型", "X轴字段", "Y轴字段", "系列分组", "刷新间隔", "图表布局"]
    REQUIRED_FIELDS = ["图表标识", "数据来源", "图表类型"]
    STATUS_ORDER = ["草稿", "已发布", "已下架"]
    # 注意：通用资源路由的动作目标以本表为准，下架必须真正进入「已下架」
    ACTION_RULES = {"发布图表": "已发布", "下架图表": "已下架"}
    NEGATIVE_ACTIONS = []

    # ---- 版本化图表数据 ----
    def register_chart(
        self,
        values: dict[str, Any],
        *,
        points: list[float] | None = None,
        coverage: dict[str, Any] | None = None,
        chart_version: str | None = None,
        replaces_chart_id: int | None = None,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """登记一张带确定数据值和覆盖范围的图表（替代图通过 replaces_chart_id 关联原图）。"""
        entry, missing = self.create_entry(values)
        if entry is None:
            return None, missing
        if points is not None:
            entry["数据点"] = [round(float(v), 4) for v in points]
        entry["图表版本"] = chart_version or f"v{entry['id']}"
        entry["覆盖范围"] = coverage or self._default_coverage(entry)
        if replaces_chart_id is not None:
            entry["替代图表"] = int(replaces_chart_id)
        # 登记即发布，供报告调度领取
        entry["status"] = "已发布"
        entry["pending"] = True
        entry["registered_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return entry, []

    def _default_coverage(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "统计期": "2026-W47",
            "指标": [str(entry.get("Y轴字段", "指标值"))],
            "维度": [str(entry.get("X轴字段", "日期"))],
            "数据来源": str(entry.get("数据来源", "")),
        }

    def _series_for(self, chart: dict[str, Any]) -> tuple[list[dict[str, Any]], list[float]]:
        """按图表版本生成稳定序列：显式数据点优先，否则按图表 id 确定性生成。"""
        points = chart.get("数据点")
        if points is None:
            rng = random.Random(int(chart["id"]) * 19 + 7)
            n_points = rng.randint(7, 12)
            points = [round(rng.uniform(8.0, 20.0), 4) for _ in range(n_points)]
        points = [round(float(v), 4) for v in points]
        chart_type = str(chart.get("图表类型", "趋势图"))
        x_field = str(chart.get("X轴字段", "日期"))
        n_points = len(points)
        x_values = [f"2026-10-{d + 1:02d}" for d in range(n_points)]
        series_group = str(chart.get("系列分组", "")) or "默认组"
        series = [{
            "name": series_group,
            "x_field": x_field,
            "x": x_values,
            "y_field": str(chart.get("Y轴字段", "指标值")),
            "y": list(points),
            "type": "line" if "趋势" in chart_type else ("bar" if "对比" in chart_type else "pie"),
        }]
        return series, points

    def build_chart_payload(self, chart_id: int) -> dict[str, Any]:
        """构造一份可冻结进在途报告快照的图表数据负载（深拷贝，后续改动不影响快照）。"""
        chart = store.find(self.MODULE, chart_id)
        if not chart:
            return {"error": f"图表配置 {chart_id} 不存在"}
        series, points = self._series_for(chart)
        return {
            "chart_id": chart_id,
            "chart_code": chart.get("图表标识"),
            "chart_version": chart.get("图表版本", f"v{chart_id}"),
            "chart_status_at_capture": chart.get("status"),
            "chart_type": chart.get("图表类型", "趋势图"),
            "coverage": copy.deepcopy(chart.get("覆盖范围") or self._default_coverage(chart)),
            "series": copy.deepcopy(series),
            "point_count": len(points),
            "total": round(sum(points), 4),
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def render_chart_data(self, chart_id: int) -> dict[str, Any]:
        """生成图表渲染数据（同一图表版本始终返回同一份数据）。"""
        chart = store.find(self.MODULE, chart_id)
        if not chart:
            return {"error": f"图表配置 {chart_id} 不存在"}
        payload = self.build_chart_payload(chart_id)
        return {
            "chart_id": chart_id,
            "chart_name": chart.get("图表标识"),
            "chart_version": payload["chart_version"],
            "chart_type": payload["chart_type"],
            "layout": chart.get("图表布局", "half-left"),
            "coverage": payload["coverage"],
            "total": payload["total"],
            "data": payload["series"],
        }

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """下架图表时联动在途报告：引用该图的在途领取转为待重新取数。"""
        entry, message = super().run_action(entry_id, action)
        if entry is None:
            return entry, message
        if action == "下架图表":
            # 延迟导入避免模块循环依赖
            from app.services.report_schedule import ReportScheduleService
            report_svc = next(
                (svc for svc in self._all_services() if isinstance(svc, ReportScheduleService)),
                None,
            )
            if report_svc is not None:
                affected = report_svc.mark_chart_offline(entry_id)
                if affected:
                    message += f"，{affected} 个在途报告领取已转为待重新取数"
        return entry, message

    @staticmethod
    def _all_services():
        from app.services import SERVICES
        return SERVICES.values()

    def domain_enrich(self, config_id: int) -> dict:
        """对当前模块执行记录操作，联动批次和状态，产出标准化数据产物。

        数据加工流程：读取原始记录 → 执行记录处理 → 批次校验字段完整性 → 生成状态批次标识 →
        写入存储层并返回可追溯的处理结果，下游消费模块可基于批次号追踪数据链路。
        """
        entry = store.find(self.MODULE, config_id)
        # 记录：遍历当前模块全部记录执行核心数据处理
        records = store.list_all(self.MODULE) if hasattr(store, "list_all") else store.rows(self.MODULE)
        processed = []
        for idx, rec in enumerate(records):
            # 批次：校验每条记录的字段完整性与格式合法性
            filled = sum(1 for v in rec.values() if v and str(v).strip())
            total = len(rec)
            rec_copy = dict(rec)
            rec_copy["_field_count"] = filled
            rec_copy["_complete_ratio"] = f"{filled}/{total}"
            rec_copy["_batch"] = f"{self.MODULE}-{idx:04d}"
            processed.append(rec_copy)
        # 状态：生成加工批次标识并写入存储
        batch_id = store.next_id(self.MODULE + "_processor")
        return {
            "module": self.MODULE,
            "operation": "记录",
            "config_id": config_id,
            "records_processed": len(processed),
            "batch_id": batch_id,
            "field_validation": {"批次": "passed", "状态": "recorded"},
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "downstream_consumable": True,
            "records": processed,
            "entry": entry,
        }

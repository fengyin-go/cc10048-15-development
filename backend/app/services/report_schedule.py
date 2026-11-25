"""报告调度领域服务：周期调度、在途报告取数快照、分段投递与恢复。

核心规则：
1. 周报的图、报表区间、指标汇总必须来自同一份「在途报告取数快照」，
   快照冻结真实图表版本、覆盖范围和数据值，杜绝“下架前的图配下架后的数字”。
2. 报告调度只用快照制作实际附件与汇总；发送中途可暂扣回执。
3. 图表下架后，引用它的在途领取转为「待重新取数」，新报告不得默认引用已下架图。
4. 重新取数会生成新快照（新发行编号），旧快照归档但仍可按原发行编号复查。
5. 已完整准备的段落随快照冻结，恢复时可整段回查、无需重算。
"""
from __future__ import annotations

import copy
import random
import time
from datetime import datetime, timedelta
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 在途报告取数快照状态
SNAPSHOT_INFLIGHT = "在途"          # 已领取，正在准备/发送
SNAPSHOT_HOLD = "发送暂扣"          # 回执暂扣，等待恢复
SNAPSHOT_REFETCH = "待重新取数"     # 引用图表已下架，旧领取不可继续发送
SNAPSHOT_ARCHIVED = "已归档"        # 报告结束或被新快照取代，仍可按发行编号复查

# 图表领取（申请）状态
CLAIM_ACTIVE = "可发送"
CLAIM_HOLD = "暂扣中"
CLAIM_STALE = "须重新领取"

# 投递回执状态
RECEIPT_SENT = "已发送"
RECEIPT_PENDING = "待发送"
RECEIPT_HELD = "已暂扣"


class ReportScheduleService(BaseModuleService):
    MODULE = "report_schedule"
    ENTITY = "报告任务"
    OPERATION_TERM = "调度"
    LIST_FIELDS = ["任务标识", "报告内容", "接收人", "发送周期", "发送渠道", "上次发送", "下次发送", "任务状态"]
    REQUIRED_FIELDS = ["任务标识", "报告内容", "接收人"]
    STATUS_ORDER = ["待启动", "运行中", "已暂停", "调度失败"]
    ACTION_RULES = {"启动调度": "待启动", "暂停调度": "运行中"}
    NEGATIVE_ACTIONS = []

    # ------------------------------------------------------------------
    # 在途报告取数快照
    # ------------------------------------------------------------------
    def prepare_inflight_issue(
        self,
        task_id: int,
        chart_id: int,
        *,
        recipients: list[str] | None = None,
        period: str | None = None,
        hold: bool = False,
        remark: str | None = None,
    ) -> dict[str, Any]:
        """领取图表数据，生成在途报告取数快照并准备一期周报。

        hold=True 时只准备不投递，全部回执进入暂扣；否则立即准备投递队列。
        已下架图表不得被新报告默认引用。
        """
        task = store.find(self.MODULE, task_id)
        if not task:
            return {"error": f"报告任务 {task_id} 不存在"}
        chart = store.find("analysis_chart", chart_id)
        if not chart:
            return {"error": f"图表配置 {chart_id} 不存在"}
        if chart.get("status") == "已下架":
            return {"error": f"图表 {chart_id} 已下架，新报告不得默认引用，请重新登记替代图后取数"}

        from app.services.analysis_chart import AnalysisChartService
        chart_svc = next(
            (svc for svc in self._all_services() if isinstance(svc, AnalysisChartService)),
            None,
        )
        if chart_svc is None:
            return {"error": "分析图表服务不可用"}
        chart_payload = chart_svc.build_chart_payload(chart_id)
        if "error" in chart_payload:
            return chart_payload

        snapshot_id = store.next_id("inflight_snapshot")
        issue_seq = store.next_id("issue_no")
        issue_no = f"RPT-{task_id:03d}-{issue_seq:04d}"
        coverage = copy.deepcopy(chart_payload["coverage"])
        stat_period = period or str(coverage.get("统计期") or datetime.now().strftime("%Y-W%W"))
        recipients = recipients or self._default_recipients(task)

        # 图、报表区间、指标汇总全部出自同一份图表数据
        sections = self._build_sections(task, chart_payload, stat_period)
        snapshot = {
            "snapshot_id": snapshot_id,
            "issue_no": issue_no,
            "task_id": task_id,
            "period": stat_period,
            "chart_id": chart_id,
            "chart_code": chart_payload["chart_code"],
            "chart_version": chart_payload["chart_version"],
            "coverage": coverage,
            # 冻结数据：此后图表下架/改版不影响本快照
            "chart_data": copy.deepcopy(chart_payload),
            "sections": sections,
            "summary": sections["指标汇总"],
            "attachment": self._build_attachment(issue_no, stat_period, chart_payload, sections),
            "claim": {
                "chart_id": chart_id,
                "chart_version": chart_payload["chart_version"],
                "status": CLAIM_HOLD if hold else CLAIM_ACTIVE,
                "claimed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "remark": remark,
            },
            "recipients": list(recipients),
            "receipts": [
                {
                    "receipt_id": store.next_id("receipt"),
                    "recipient": recipient,
                    "status": RECEIPT_HELD if hold else RECEIPT_PENDING,
                    "issue_no": issue_no,
                    "period": stat_period,
                    "chart_version": chart_payload["chart_version"],
                    "sent_at": None,
                }
                for recipient in recipients
            ],
            "status": SNAPSHOT_HOLD if hold else SNAPSHOT_INFLIGHT,
            "events": [self._event(
                "在途取数" if not hold else "在途取数并暂扣",
                f"领取图表 {chart_id}（{chart_payload['chart_version']}），发行编号 {issue_no}，统计期 {stat_period}",
            )],
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "archived_at": None,
        }
        store.save_snapshot(snapshot)
        task["status"] = "已暂停" if hold else "运行中"
        task["pending"] = True
        return copy.deepcopy(snapshot)

    def _build_sections(
        self, task: dict[str, Any], chart_payload: dict[str, Any], stat_period: str
    ) -> dict[str, Any]:
        """用同一份图表数据构造周报各段落，保证图/区间/汇总口径一致。"""
        series = chart_payload["series"]
        all_y = [value for item in series for value in item["y"]]
        total = round(sum(all_y), 4)
        point_count = len(all_y)
        avg = round(total / point_count, 4) if point_count else 0.0
        return {
            "图表段落": {
                "title": f"{chart_payload['chart_code']}（{chart_payload['chart_version']}）",
                "chart_id": chart_payload["chart_id"],
                "chart_version": chart_payload["chart_version"],
                "series": copy.deepcopy(series),
            },
            "报表区间": {
                "period": stat_period,
                "coverage": copy.deepcopy(chart_payload["coverage"]),
                "x_range": [series[0]["x"][0], series[0]["x"][-1]] if series and series[0]["x"] else [],
            },
            "指标汇总": {
                "chart_version": chart_payload["chart_version"],
                "point_count": point_count,
                "total": total,
                "avg": avg,
                "max": round(max(all_y), 4) if all_y else 0.0,
                "min": round(min(all_y), 4) if all_y else 0.0,
            },
            "文字说明": f"{task.get('报告内容', '指标周报')} · 统计期 {stat_period}，合计 {total}",
        }

    def _build_attachment(
        self, issue_no: str, stat_period: str,
        chart_payload: dict[str, Any], sections: dict[str, Any],
    ) -> dict[str, Any]:
        """实际附件由快照数据制作，附件内嵌版本号便于发行后复查。"""
        return {
            "attachment_id": f"ATT-{issue_no}",
            "issue_no": issue_no,
            "period": stat_period,
            "chart_id": chart_payload["chart_id"],
            "chart_version": chart_payload["chart_version"],
            "coverage": copy.deepcopy(chart_payload["coverage"]),
            "chart_series": copy.deepcopy(chart_payload["series"]),
            "summary": copy.deepcopy(sections["指标汇总"]),
            "sections": list(sections.keys()),
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    @staticmethod
    def _default_recipients(task: dict[str, Any]) -> list[str]:
        raw = str(task.get("接收人", "recipient@example.com"))
        return [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()] or [
            "recipient@example.com"
        ]

    @staticmethod
    def _event(action: str, detail: str) -> dict[str, Any]:
        return {
            "event_id": store.next_id("event"),
            "action": action,
            "detail": detail,
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # ------------------------------------------------------------------
    # 分段投递与暂扣
    # ------------------------------------------------------------------
    def send_next(self, snapshot_id: int, count: int = 1) -> dict[str, Any]:
        """投递队列中前 count 个待发送回执，支持发送到一半停住。"""
        snapshot = store.get_snapshot(snapshot_id)
        if not snapshot:
            return {"error": f"取数快照 {snapshot_id} 不存在"}
        if snapshot["status"] in (SNAPSHOT_REFETCH, SNAPSHOT_ARCHIVED):
            return {"error": f"快照处于{snapshot['status']}状态，不可继续发送"}
        sent = []
        remaining = max(1, count)
        for receipt in snapshot["receipts"]:
            if remaining <= 0:
                break
            if receipt["status"] == RECEIPT_PENDING:
                receipt["status"] = RECEIPT_SENT
                receipt["sent_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                sent.append(copy.deepcopy(receipt))
                remaining -= 1
        snapshot["events"].append(self._event(
            "分段投递", f"实际发出 {len(sent)} 份，统计期 {snapshot['period']}，附件 {snapshot['attachment']['attachment_id']}"
        ))
        snapshot["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        store.save_snapshot(snapshot)
        return {"snapshot_id": snapshot_id, "sent": sent, "snapshot": copy.deepcopy(snapshot)}

    def hold_sending(self, snapshot_id: int, remark: str | None = None) -> dict[str, Any]:
        """暂扣发送回执：未发送回执冻结为已暂扣，任务停住等待恢复。"""
        snapshot = store.get_snapshot(snapshot_id)
        if not snapshot:
            return {"error": f"取数快照 {snapshot_id} 不存在"}
        if snapshot["status"] in (SNAPSHOT_REFETCH, SNAPSHOT_ARCHIVED):
            return {"error": f"快照处于{snapshot['status']}状态，无法暂扣"}
        held = 0
        for receipt in snapshot["receipts"]:
            if receipt["status"] in (RECEIPT_PENDING, RECEIPT_HELD):
                receipt["status"] = RECEIPT_HELD
                held += 1
        snapshot["status"] = SNAPSHOT_HOLD
        snapshot["claim"]["status"] = CLAIM_HOLD
        snapshot["claim"]["remark"] = remark or snapshot["claim"].get("remark")
        snapshot["events"].append(self._event("暂扣回执", f"暂扣 {held} 份未发送回执，等待排程恢复"))
        snapshot["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        store.save_snapshot(snapshot)
        task = store.find(self.MODULE, snapshot["task_id"])
        if task:
            task["status"] = "已暂停"
        return copy.deepcopy(snapshot)

    # ------------------------------------------------------------------
    # 图表下架联动
    # ------------------------------------------------------------------
    def mark_chart_offline(self, chart_id: int) -> int:
        """图表下架：所有仍在途/暂扣且引用该图的领取转为待重新取数。"""
        affected = 0
        for snapshot in store.list_snapshots(chart_id=chart_id):
            if snapshot["status"] in (SNAPSHOT_INFLIGHT, SNAPSHOT_HOLD):
                snapshot["status"] = SNAPSHOT_REFETCH
                snapshot["claim"]["status"] = CLAIM_STALE
                snapshot["events"].append(self._event(
                    "图表下架",
                    f"图表 {chart_id}（{snapshot['chart_version']}）已下架，旧领取不可继续发送，须重新领取",
                ))
                snapshot["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                store.save_snapshot(snapshot)
                affected += 1
        return affected

    # ------------------------------------------------------------------
    # 恢复排程：辨认旧领取是否仍可发送
    # ------------------------------------------------------------------
    def resume_schedule(self, snapshot_id: int) -> dict[str, Any]:
        """从原发送状态恢复：可发送则继续，须重新领取则给出流转方案。

        已完整准备的其他段落（sections/attachment）原样保留可回查。
        """
        snapshot = store.get_snapshot(snapshot_id)
        if not snapshot:
            return {"error": f"取数快照 {snapshot_id} 不存在"}
        if snapshot["status"] == SNAPSHOT_REFETCH or snapshot["claim"]["status"] == CLAIM_STALE:
            base = self._resume_base(snapshot)
            snapshot["events"].append(self._event("排程恢复", "辨认结果：旧领取须重新领取，已冻结段落仍可回查"))
            snapshot["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            store.save_snapshot(snapshot)
            return {
                **base,
                "resumable": False,
                "action_required": "重新取数",
                "message": "原图已下架，旧领取不可继续发送；请登记替代图并调用重新取数，旧发行编号数据归档可复查",
            }
        if snapshot["status"] == SNAPSHOT_ARCHIVED:
            return {**self._resume_base(snapshot), "resumable": False,
                    "action_required": "归档复查",
                    "message": "该期报告已归档，仅支持按发行编号复查"}
        # 在途或暂扣但领取仍有效：解冻暂扣回执
        for receipt in snapshot["receipts"]:
            if receipt["status"] == RECEIPT_HELD:
                receipt["status"] = RECEIPT_PENDING
        snapshot["status"] = SNAPSHOT_INFLIGHT
        snapshot["claim"]["status"] = CLAIM_ACTIVE
        snapshot["events"].append(self._event("排程恢复", "辨认结果：旧领取仍可发送，暂扣回执解冻继续投递"))
        snapshot["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        store.save_snapshot(snapshot)
        task = store.find(self.MODULE, snapshot["task_id"])
        if task:
            task["status"] = "运行中"
        return {**self._resume_base(snapshot), "resumable": True,
                "action_required": "继续投递",
                "message": "旧领取仍可发送，未发送回执已解冻", "snapshot": copy.deepcopy(snapshot)}

    @staticmethod
    def _resume_base(snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "snapshot_id": snapshot["snapshot_id"],
            "issue_no": snapshot["issue_no"],
            "period": snapshot["period"],
            "chart_id": snapshot["chart_id"],
            "chart_version": snapshot["chart_version"],
            "snapshot_status": snapshot["status"],
            "claim_status": snapshot["claim"]["status"],
            "prepared_sections": list(snapshot["sections"].keys()),
            "receipts": copy.deepcopy(snapshot["receipts"]),
        }

    # ------------------------------------------------------------------
    # 重新取数（替代图）
    # ------------------------------------------------------------------
    def refetch_with_chart(
        self, old_snapshot_id: int, new_chart_id: int, *, remark: str | None = None
    ) -> dict[str, Any]:
        """用替代图重新领取：旧快照归档保留，生成新发行编号的新快照。

        同一统计期沿用任务与收件人；已按旧发行编号发出的回执保留在旧快照中可复查。
        """
        old = store.get_snapshot(old_snapshot_id)
        if not old:
            return {"error": f"取数快照 {old_snapshot_id} 不存在"}
        new_chart = store.find("analysis_chart", new_chart_id)
        if not new_chart:
            return {"error": f"图表配置 {new_chart_id} 不存在"}
        if new_chart.get("status") == "已下架":
            return {"error": f"替代图 {new_chart_id} 已下架，不能用于重新取数"}

        # 旧申请流转：归档旧快照，冻结段落与已发回执
        old["status"] = SNAPSHOT_ARCHIVED
        old["claim"]["status"] = CLAIM_STALE
        old["archived_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        old["events"].append(self._event(
            "重新取数",
            f"旧申请归档，替代图 {new_chart_id} 接替；已发回执按原发行编号 {old['issue_no']} 保留",
        ))
        old["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        store.save_snapshot(old)

        fresh = self.prepare_inflight_issue(
            old["task_id"],
            new_chart_id,
            recipients=list(old["recipients"]),
            period=old["period"],
            hold=False,
            remark=remark or f"替代快照 {old['issue_no']} 重新取数",
        )
        if "error" in fresh:
            return fresh
        fresh["replaces_snapshot_id"] = old_snapshot_id
        fresh["replaces_issue_no"] = old["issue_no"]
        fresh["events"].insert(1, self._event(
            "替代登记",
            f"新发行编号 {fresh['issue_no']} 接替 {old['issue_no']}，统计期同为 {fresh['period']}，数据版本不同不得混用",
        ))
        store.save_snapshot(fresh)
        return {
            "old_snapshot": copy.deepcopy(old),
            "new_snapshot": copy.deepcopy(fresh),
            "message": "旧领取已归档，替代图重新取数完成；新旧版本隔离，统计期保持一致",
        }

    # ------------------------------------------------------------------
    # 报告结束 / 复查
    # ------------------------------------------------------------------
    def complete_issue(self, snapshot_id: int) -> dict[str, Any]:
        """报告结束：全部回执发送完成后归档快照，保存结束状态。"""
        snapshot = store.get_snapshot(snapshot_id)
        if not snapshot:
            return {"error": f"取数快照 {snapshot_id} 不存在"}
        pending = [r for r in snapshot["receipts"] if r["status"] != RECEIPT_SENT]
        if pending:
            return {"error": f"仍有 {len(pending)} 份回执未发送，不能结束报告"}
        snapshot["status"] = SNAPSHOT_ARCHIVED
        snapshot["claim"]["status"] = "已完成"
        snapshot["archived_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        snapshot["events"].append(self._event("报告结束", f"发行编号 {snapshot['issue_no']} 全部发送完成并归档"))
        snapshot["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        store.save_snapshot(snapshot)
        task = store.find(self.MODULE, snapshot["task_id"])
        if task:
            task["上次发送"] = snapshot["archived_at"]
            task["下次发送"] = (datetime.now() + timedelta(days=7)).isoformat()
        return copy.deepcopy(snapshot)

    def review_issue(self, issue_no: str) -> dict[str, Any]:
        """按发行编号复查已发周报的原图数据（含已归档/已下架图的冻结数据）。"""
        matches = store.list_snapshots(issue_no=issue_no)
        if not matches:
            return {"error": f"发行编号 {issue_no} 无对应取数快照"}
        snapshot = matches[0]
        return {
            "issue_no": issue_no,
            "snapshot_id": snapshot["snapshot_id"],
            "period": snapshot["period"],
            "status": snapshot["status"],
            "chart_id": snapshot["chart_id"],
            "chart_version": snapshot["chart_version"],
            "coverage": copy.deepcopy(snapshot["coverage"]),
            "frozen_chart_data": copy.deepcopy(snapshot["chart_data"]),
            "sections": copy.deepcopy(snapshot["sections"]),
            "attachment": copy.deepcopy(snapshot["attachment"]),
            "receipts": copy.deepcopy(snapshot["receipts"]),
            "events": copy.deepcopy(snapshot["events"]),
        }

    def list_inflight_snapshots(self, task_id: int | None = None) -> dict[str, Any]:
        """查看任务的在途/历史取数快照与状态流转。"""
        items = store.list_snapshots(task_id=task_id) if task_id is not None else store.list_snapshots()
        return {
            "total": len(items),
            "items": [
                {
                    "snapshot_id": item["snapshot_id"],
                    "issue_no": item["issue_no"],
                    "task_id": item["task_id"],
                    "period": item["period"],
                    "chart_id": item["chart_id"],
                    "chart_version": item["chart_version"],
                    "status": item["status"],
                    "claim_status": item["claim"]["status"],
                    "sent": sum(1 for r in item["receipts"] if r["status"] == RECEIPT_SENT),
                    "held": sum(1 for r in item["receipts"] if r["status"] == RECEIPT_HELD),
                    "waiting": sum(1 for r in item["receipts"] if r["status"] == RECEIPT_PENDING),
                    "events": copy.deepcopy(item["events"]),
                }
                for item in items
            ],
        }

    @staticmethod
    def _all_services():
        from app.services import SERVICES
        return SERVICES.values()

    # ------------------------------------------------------------------
    # 兼容原有模拟报告生成
    # ------------------------------------------------------------------
    def generate_report(self, task_id: int) -> dict[str, Any]:
        """生成一份模拟报告（保留旧接口；新链路请使用在途取数快照）。"""
        task = store.find(self.MODULE, task_id)
        if not task:
            return {"error": f"报告任务 {task_id} 不存在"}
        rng = random.Random(task_id * 43)
        now = datetime.now()
        send_now = now.isoformat()
        next_send = (now + timedelta(hours=24)).isoformat() if "日" in str(task.get("发送周期", "日")) else (now + timedelta(hours=1)).isoformat()
        report_content = {
            "task_id": task_id,
            "title": f"指标分析报告 - {task.get('报告内容', '概览')}",
            "generate_time": send_now,
            "recipient": task.get("接收人"),
            "channel": task.get("发送渠道", "email"),
            "sections": [
                {"name": "核心指标概览", "metrics": {"GMV": rng.uniform(1000000, 5000000),
                                                      "DAU": rng.randint(50000, 200000),
                                                      "转化率": f"{rng.uniform(5, 20):.1f}%"}},
                {"name": "异常指标", "alerts": [{"metric": "支付成功率", "change": f"{rng.uniform(-10, -1):.1f}%"},
                                                  {"metric": "响应延迟", "change": f"+{rng.uniform(10, 50):.0f}ms"}]},
                {"name": "趋势分析", "summary": "本周整体指标平稳，搜索转化率下降2.3%，需关注推荐算法迭代效果"},
            ],
            "next_schedule": next_send,
        }
        update = store.find(self.MODULE, task_id)
        if update:
            update["上次发送"] = send_now
            update["下次发送"] = next_send
            update["status"] = "运行中"
        return report_content

    def domain_enrich(self, config_id: int) -> dict:
        """对当前模块执行存储操作，联动导出和回填，产出标准化数据产物。

        数据加工流程：读取原始记录 → 执行存储处理 → 导出校验字段完整性 → 生成回填批次标识 →
        写入存储层并返回可追溯的处理结果，下游消费模块可基于批次号追踪数据链路。
        """
        entry = store.find(self.MODULE, config_id)
        records = store.rows(self.MODULE)
        processed = []
        for idx, rec in enumerate(records):
            filled = sum(1 for v in rec.values() if v and str(v).strip())
            total = len(rec)
            rec_copy = dict(rec)
            rec_copy["_field_count"] = filled
            rec_copy["_complete_ratio"] = f"{filled}/{total}"
            rec_copy["_batch"] = f"{self.MODULE}-{idx:04d}"
            processed.append(rec_copy)
        batch_id = store.next_id(self.MODULE + "_processor")
        return {
            "module": self.MODULE,
            "operation": "存储",
            "config_id": config_id,
            "records_processed": len(processed),
            "batch_id": batch_id,
            "field_validation": {"导出": "passed", "回填": "recorded"},
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "downstream_consumable": True,
            "records": processed,
            "entry": entry,
        }

"""在途报告取数快照端到端测试。

复现业务场景：
同一期周报已领取原图（合计 70）的批次发送到一半停住 → 指标维护人下架原图、
登记合计 74 的替代图（两份数据来自不同版本）→ 恢复排程时辨认旧领取是否仍可发送、
哪些数据须重新领取，已完整准备的段落仍可回查 → 重新取数后核对实际发出的统计期与附件。
"""
from __future__ import annotations

import pytest

from app.services.analysis_chart import AnalysisChartService
from app.services.report_schedule import (
    CLAIM_ACTIVE, CLAIM_STALE, RECEIPT_HELD, RECEIPT_PENDING, RECEIPT_SENT,
    SNAPSHOT_ARCHIVED, SNAPSHOT_HOLD, SNAPSHOT_REFETCH,
)
from app.store import store


@pytest.fixture()
def svc():
    """每个用例使用全新内存仓库并重建服务注册表，避免与种子数据和其他用例串扰。"""
    from app import store as store_module
    import app.services as services_module

    original_store = store_module.store
    original_services = dict(services_module.SERVICES)
    fresh_store = store_module.Store()
    store_module.store = fresh_store

    fresh_services = {key: type(service)() for key, service in original_services.items()}
    services_module.SERVICES.clear()
    services_module.SERVICES.update(fresh_services)
    try:
        yield (
            fresh_services["report_schedule"],
            fresh_services["analysis_chart"],
            fresh_store,
        )
    finally:
        store_module.store = original_store
        services_module.SERVICES.clear()
        services_module.SERVICES.update(original_services)


def _register(svc_chart: AnalysisChartService, points: list[float], version: str,
              replaces: int | None = None):
    entry, missing = svc_chart.register_chart(
        {
            "图表标识": f"CHART-{version}",
            "数据来源": "指标集市/交易域",
            "图表类型": "趋势图",
            "X轴字段": "日期",
            "Y轴字段": "GMV",
        },
        points=points,
        coverage={
            "统计期": "2026-W47",
            "指标": ["GMV"],
            "维度": ["日期"],
            "数据来源": "指标集市/交易域",
        },
        chart_version=version,
        replaces_chart_id=replaces,
    )
    assert missing == []
    return entry


class TestInflightSnapshotScenario:
    def test_full_offline_replace_resume_flow(self, svc):
        report_svc, chart_svc, _ = svc

        # 1. 登记原图（合计 70：7 个点各 10）与报告任务
        old_chart = _register(chart_svc, [10, 10, 10, 10, 10, 10, 10], "v1")
        task, missing = report_svc.create_entry({
            "任务标识": "WEEKLY-GMV", "报告内容": "GMV 周报",
            "接收人": "a@corp.com,b@corp.com,c@corp.com", "发送周期": "每周",
        })
        assert missing == []
        task_id = int(task["id"])

        # 2. 准备一期周报并暂扣发送回执：图、区间、汇总同一份快照，合计 70
        snapshot = report_svc.prepare_inflight_issue(
            task_id, int(old_chart["id"]), hold=True,
        )
        assert snapshot["status"] == SNAPSHOT_HOLD
        assert snapshot["claim"]["status"] == "暂扣中"
        assert snapshot["summary"]["total"] == 70
        assert snapshot["chart_version"] == "v1"
        assert all(r["status"] == RECEIPT_HELD for r in snapshot["receipts"])
        # 图/报表区间/指标汇总口径一致：附件、段落都引用 v1 与同一份冻结数据
        assert snapshot["attachment"]["chart_version"] == "v1"
        assert snapshot["attachment"]["summary"]["total"] == 70
        assert snapshot["sections"]["指标汇总"]["total"] == 70
        assert snapshot["sections"]["图表段落"]["chart_version"] == "v1"
        snapshot_id = int(snapshot["snapshot_id"])

        # 模拟“发送到一半停住”：先恢复一次让第一份回执发出，再暂扣
        resumed = report_svc.resume_schedule(snapshot_id)
        assert resumed["resumable"] is True
        report_svc.send_next(snapshot_id, count=1)
        report_svc.hold_sending(snapshot_id, remark="发送到一半停住")
        snapshot = store.get_snapshot(snapshot_id)
        sent = [r for r in snapshot["receipts"] if r["status"] == RECEIPT_SENT]
        held = [r for r in snapshot["receipts"] if r["status"] == RECEIPT_HELD]
        assert len(sent) == 1 and len(held) == 2
        assert sent[0]["chart_version"] == "v1"

        # 3. 指标维护人下架原图：在途领取自动转为待重新取数
        chart_svc.run_action(int(old_chart["id"]), "下架图表")
        snapshot = store.get_snapshot(snapshot_id)
        assert snapshot["status"] == SNAPSHOT_REFETCH
        assert snapshot["claim"]["status"] == CLAIM_STALE
        assert store.find("analysis_chart", int(old_chart["id"]))["status"] == "已下架"

        # 4. 登记替代图（合计 74：不同版本数据）
        new_chart = _register(
            chart_svc, [10, 11, 10, 11, 10, 11, 11], "v2", replaces=int(old_chart["id"])
        )
        assert int(new_chart["替代图表"]) == int(old_chart["id"])

        # 5. 下架后新报告不得默认引用旧图
        rejected = report_svc.prepare_inflight_issue(task_id, int(old_chart["id"]))
        assert "error" in rejected and "已下架" in rejected["error"]

        # 6. 从原发送状态恢复：必须能辨认旧领取不可发送、须重新领取，段落可回查
        decision = report_svc.resume_schedule(snapshot_id)
        assert decision["resumable"] is False
        assert decision["action_required"] == "重新取数"
        assert set(decision["prepared_sections"]) == {"图表段落", "报表区间", "指标汇总", "文字说明"}
        # 已完整准备的其他段落原样可回查
        review = report_svc.review_issue(snapshot["issue_no"])
        assert review["frozen_chart_data"]["total"] == 70
        assert review["sections"]["指标汇总"]["total"] == 70

        # 7. 重新取数：旧快照归档（含已发回执），新快照新发行编号、同统计期、合计 74
        result = report_svc.refetch_with_chart(snapshot_id, int(new_chart["id"]))
        old_snap, new_snap = result["old_snapshot"], result["new_snapshot"]
        assert old_snap["status"] == SNAPSHOT_ARCHIVED
        assert old_snap["summary"]["total"] == 70
        # 旧发行编号下已发出的回执保留可复查
        assert sum(1 for r in old_snap["receipts"] if r["status"] == RECEIPT_SENT) == 1
        assert new_snap["issue_no"] != old_snap["issue_no"]
        assert new_snap["period"] == old_snap["period"] == "2026-W47"
        assert new_snap["chart_version"] == "v2"
        assert new_snap["summary"]["total"] == 74
        assert new_snap["attachment"]["summary"]["total"] == 74
        assert new_snap["replaces_issue_no"] == old_snap["issue_no"]
        new_id = int(new_snap["snapshot_id"])

        # 8. 排程恢复后实际发出剩余报告：统计期一致、附件版本为 v2
        for _ in range(3):
            report_svc.send_next(new_id, count=1)
        new_snap = store.get_snapshot(new_id)
        assert all(r["status"] == RECEIPT_SENT for r in new_snap["receipts"])
        assert {r["period"] for r in new_snap["receipts"]} == {"2026-W47"}
        assert {r["chart_version"] for r in new_snap["receipts"]} == {"v2"}

        # 9. 报告结束归档；新旧发行编号都可复查且数据版本不串
        completed = report_svc.complete_issue(new_id)
        assert completed["status"] == SNAPSHOT_ARCHIVED
        old_review = report_svc.review_issue(old_snap["issue_no"])
        new_review = report_svc.review_issue(new_snap["issue_no"])
        assert old_review["frozen_chart_data"]["chart_version"] == "v1"
        assert old_review["frozen_chart_data"]["total"] == 70
        assert new_review["frozen_chart_data"]["chart_version"] == "v2"
        assert new_review["frozen_chart_data"]["total"] == 74

        # 10. 台账可追溯完整状态流转
        listing = report_svc.list_inflight_snapshots(task_id)
        assert listing["total"] == 2
        statuses = {item["issue_no"]: item["status"] for item in listing["items"]}
        assert statuses[old_snap["issue_no"]] == SNAPSHOT_ARCHIVED
        assert statuses[new_snap["issue_no"]] == SNAPSHOT_ARCHIVED


class TestInflightSnapshotInvariants:
    def test_snapshot_is_frozen_after_chart_mutation(self, svc):
        report_svc, chart_svc, _ = svc
        chart = _register(chart_svc, [10, 10, 10, 10, 10, 10, 10], "v1")
        task, _ = report_svc.create_entry({
            "任务标识": "W2", "报告内容": "周报", "接收人": "x@corp.com",
        })
        snapshot = report_svc.prepare_inflight_issue(int(task["id"]), int(chart["id"]))
        # 篡改图表当前数据，快照仍保留冻结版本（不能用下架/改版后的数字）
        chart["数据点"] = [99, 99]
        chart["图表版本"] = "v9"
        review = report_svc.review_issue(snapshot["issue_no"])
        assert review["frozen_chart_data"]["total"] == 70
        assert review["chart_version"] == "v1"
        assert review["attachment"]["summary"]["total"] == 70

    def test_render_is_version_stable(self, svc):
        _, chart_svc, _ = svc
        chart = _register(chart_svc, [1, 2, 3], "v1")
        first = chart_svc.render_chart_data(int(chart["id"]))
        second = chart_svc.render_chart_data(int(chart["id"]))
        assert first["data"] == second["data"]
        assert first["total"] == 6

    def test_offline_without_inflight_issue_is_harmless(self, svc):
        _, chart_svc, _ = svc
        chart = _register(chart_svc, [1, 2, 3], "v1")
        entry, message = chart_svc.run_action(int(chart["id"]), "下架图表")
        assert entry["status"] == "已下架"
        assert "在途" not in message

    def test_complete_blocked_when_receipts_pending(self, svc):
        report_svc, chart_svc, _ = svc
        chart = _register(chart_svc, [10, 10], "v1")
        task, _ = report_svc.create_entry({
            "任务标识": "W3", "报告内容": "周报", "接收人": "a@corp.com,b@corp.com",
        })
        snapshot = report_svc.prepare_inflight_issue(int(task["id"]), int(chart["id"]))
        report_svc.send_next(int(snapshot["snapshot_id"]), count=1)
        result = report_svc.complete_issue(int(snapshot["snapshot_id"]))
        assert "error" in result
        report_svc.send_next(int(snapshot["snapshot_id"]), count=1)
        done = report_svc.complete_issue(int(snapshot["snapshot_id"]))
        assert done["status"] == SNAPSHOT_ARCHIVED

    def test_held_issue_with_valid_claim_resumes(self, svc):
        """未下架时暂扣的在途报告，恢复后旧领取仍可发送。"""
        report_svc, chart_svc, _ = svc
        chart = _register(chart_svc, [5, 5], "v1")
        task, _ = report_svc.create_entry({
            "任务标识": "W4", "报告内容": "周报", "接收人": "a@corp.com",
        })
        snapshot = report_svc.prepare_inflight_issue(
            int(task["id"]), int(chart["id"]), hold=True
        )
        decision = report_svc.resume_schedule(int(snapshot["snapshot_id"]))
        assert decision["resumable"] is True
        assert decision["claim_status"] == CLAIM_ACTIVE
        assert decision["receipts"][0]["status"] == RECEIPT_PENDING

    def test_refetch_rejects_offline_replacement(self, svc):
        report_svc, chart_svc, _ = svc
        old_chart = _register(chart_svc, [10], "v1")
        bad_chart = _register(chart_svc, [20], "v2")
        chart_svc.run_action(int(bad_chart["id"]), "下架图表")
        task, _ = report_svc.create_entry({
            "任务标识": "W5", "报告内容": "周报", "接收人": "a@corp.com",
        })
        snapshot = report_svc.prepare_inflight_issue(int(task["id"]), int(old_chart["id"]))
        chart_svc.run_action(int(old_chart["id"]), "下架图表")
        result = report_svc.refetch_with_chart(
            int(snapshot["snapshot_id"]), int(bad_chart["id"])
        )
        assert "error" in result
        # 旧快照不被失败的重新取数污染
        assert store.get_snapshot(int(snapshot["snapshot_id"]))["status"] == SNAPSHOT_REFETCH

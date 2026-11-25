"""在途报告取数快照的 HTTP 接口测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    """用全新仓库重建服务注册表，保证用例间隔离。"""
    from app import store as store_module
    import app.services as services_module

    original_store = store_module.store
    original_services = dict(services_module.SERVICES)
    store_module.store = store_module.Store()
    fresh = {key: type(service)() for key, service in original_services.items()}
    services_module.SERVICES.clear()
    services_module.SERVICES.update(fresh)
    with TestClient(app) as test_client:
        yield test_client, fresh
    store_module.store = original_store
    services_module.SERVICES.clear()
    services_module.SERVICES.update(original_services)


def _register_chart(client: TestClient, points: list[float], version: str,
                    replaces: int | None = None) -> dict:
    payload = {
        "values": {
            "图表标识": f"CHART-{version}",
            "数据来源": "集市",
            "图表类型": "趋势图",
            "X轴字段": "日期",
            "Y轴字段": "GMV",
        },
        "points": points,
        "coverage": {"统计期": "2026-W47", "指标": ["GMV"], "维度": ["日期"]},
        "chart_version": version,
    }
    if replaces is not None:
        payload["replaces_chart_id"] = replaces
    resp = client.post("/api/domain/analysis_chart/register", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["entry"]


def _create_task(client: TestClient) -> int:
    resp = client.post("/api/report_schedule", json={
        "values": {
            "任务标识": "WEEKLY-API",
            "报告内容": "GMV 周报",
            "接收人": "a@corp.com,b@corp.com",
            "发送周期": "每周",
        }
    })
    assert resp.json()["ok"] is True
    return int(resp.json()["entry"]["id"])


class TestInflightApi:
    def test_prepare_hold_offline_refetch_resume(self, client):
        http, _ = client
        old_chart = _register_chart(http, [10] * 7, "v1")
        task_id = _create_task(http)

        # 准备并暂扣
        resp = http.post(
            f"/api/domain/report_schedule/{task_id}/inflight/prepare",
            json={"chart_id": old_chart["id"], "hold": True},
        )
        assert resp.status_code == 200
        snapshot = resp.json()
        assert snapshot["status"] == "发送暂扣"
        assert snapshot["summary"]["total"] == 70
        snapshot_id = snapshot["snapshot_id"]
        old_issue = snapshot["issue_no"]

        # 下架：通用动作接口触发在途快照联动
        resp = http.post(
            f"/api/analysis_chart/{old_chart['id']}/actions",
            json={"action": "下架图表"},
        )
        assert resp.status_code == 200
        assert resp.json()["entry"]["status"] == "已下架"
        assert "待重新取数" in resp.json()["message"]

        # 下架图被新报告引用时返回 409
        resp = http.post(
            f"/api/domain/report_schedule/{task_id}/inflight/prepare",
            json={"chart_id": old_chart["id"]},
        )
        assert resp.status_code == 409

        # 恢复：辨认出须重新取数
        resp = http.post(f"/api/domain/report_schedule/inflight/{snapshot_id}/resume")
        assert resp.status_code == 200
        decision = resp.json()
        assert decision["resumable"] is False
        assert decision["action_required"] == "重新取数"

        # 替代图合计 74 并重新取数
        new_chart = _register_chart(http, [10, 11, 10, 11, 10, 11, 11], "v2",
                                    replaces=old_chart["id"])
        resp = http.post(
            f"/api/domain/report_schedule/inflight/{snapshot_id}/refetch",
            json={"new_chart_id": new_chart["id"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["old_snapshot"]["status"] == "已归档"
        assert body["new_snapshot"]["summary"]["total"] == 74
        assert body["new_snapshot"]["period"] == "2026-W47"
        new_id = body["new_snapshot"]["snapshot_id"]

        # 继续投递直至完成
        for _ in range(2):
            resp = http.post(
                f"/api/domain/report_schedule/inflight/{new_id}/send",
                params={"count": 1},
            )
            assert resp.status_code == 200
        resp = http.post(f"/api/domain/report_schedule/inflight/{new_id}/complete")
        assert resp.status_code == 200
        assert resp.json()["status"] == "已归档"

        # 两个发行编号均可复查，版本数据不串
        old_review = http.get(f"/api/domain/report_schedule/inflight/review/{old_issue}")
        assert old_review.status_code == 200
        assert old_review.json()["frozen_chart_data"]["total"] == 70
        listing = http.get(f"/api/domain/report_schedule/{task_id}/inflight/snapshots")
        assert listing.json()["total"] == 2

    def test_hold_and_resume_valid_claim(self, client):
        http, _ = client
        chart = _register_chart(http, [5, 5], "v1")
        task_id = _create_task(http)
        snapshot = http.post(
            f"/api/domain/report_schedule/{task_id}/inflight/prepare",
            json={"chart_id": chart["id"], "hold": True},
        ).json()
        snapshot_id = snapshot["snapshot_id"]

        resp = http.post(
            f"/api/domain/report_schedule/inflight/{snapshot_id}/hold",
            json={"remark": "等待回执"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "发送暂扣"

        resp = http.post(f"/api/domain/report_schedule/inflight/{snapshot_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["resumable"] is True
        assert resp.json()["receipts"][0]["status"] == "待发送"

    def test_unknown_snapshot_returns_404(self, client):
        http, _ = client
        resp = http.get("/api/domain/report_schedule/inflight/review/NO-SUCH")
        assert resp.status_code == 404
        resp = http.post("/api/domain/report_schedule/inflight/9999/resume")
        assert resp.status_code == 404

    def test_register_chart_missing_fields(self, client):
        http, _ = client
        resp = http.post("/api/domain/analysis_chart/register", json={"values": {}})
        assert resp.status_code == 400

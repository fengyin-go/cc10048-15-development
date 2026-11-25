"""场景演示：合计 70 原图 → 暂扣/下架 → 合计 74 替代图 → 恢复排程核对。

运行：.venv/bin/python -I scripts/scenario_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app


def main() -> None:
    client = TestClient(app)

    # 1. 登记合计 70 的原图（7 个数据点各 10）
    old_chart = client.post("/api/domain/analysis_chart/register", json={
        "values": {
            "图表标识": "GMV周趋势-原图", "数据来源": "指标集市/交易域",
            "图表类型": "趋势图", "X轴字段": "日期", "Y轴字段": "GMV",
        },
        "points": [10, 10, 10, 10, 10, 10, 10],
        "coverage": {"统计期": "2026-W47", "指标": ["GMV"], "维度": ["日期"],
                     "数据来源": "指标集市/交易域"},
        "chart_version": "v1",
    }).json()["entry"]
    print(f"[1] 原图已登记: id={old_chart['id']} 版本={old_chart['图表版本']} 状态={old_chart['status']}")

    # 2. 登记周报任务（3 个收件人，便于演示发送到一半）
    task = client.post("/api/report_schedule", json={"values": {
        "任务标识": "GMV-WEEKLY", "报告内容": "GMV 周报",
        "接收人": "alice@corp.com,bob@corp.com,carol@corp.com", "发送周期": "每周",
    }}).json()["entry"]
    task_id = task["id"]

    # 3. 用原图准备一期周报并暂扣回执
    snap = client.post(f"/api/domain/report_schedule/{task_id}/inflight/prepare", json={
        "chart_id": old_chart["id"], "hold": True,
    }).json()
    sid = snap["snapshot_id"]
    print(f"[2] 在途快照: {snap['issue_no']} 统计期={snap['period']} "
          f"图表版本={snap['chart_version']} 合计={snap['summary']['total']} 状态={snap['status']}")

    # 4. 解冻并发出第一份，然后再次暂扣 —— 发送到一半停住
    client.post(f"/api/domain/report_schedule/inflight/{sid}/resume")
    client.post(f"/api/domain/report_schedule/inflight/{sid}/send?count=1")
    client.post(f"/api/domain/report_schedule/inflight/{sid}/hold", json={"remark": "发送到一半停住"})
    snap = client.get(f"/api/domain/report_schedule/{task_id}/inflight/snapshots").json()["items"][-1]
    print(f"[3] 发送到一半: 已发={snap['sent']} 暂扣={snap['held']} 待发={snap['waiting']}")

    # 5. 指标维护人下架原图
    offline = client.post(f"/api/analysis_chart/{old_chart['id']}/actions",
                          json={"action": "下架图表"}).json()
    print(f"[4] 下架原图 → {offline['entry']['status']}；联动：{offline['message']}")

    # 6. 登记合计 74 的替代图
    new_chart = client.post("/api/domain/analysis_chart/register", json={
        "values": {
            "图表标识": "GMV周趋势-替代图", "数据来源": "指标集市/交易域",
            "图表类型": "趋势图", "X轴字段": "日期", "Y轴字段": "GMV",
        },
        "points": [10, 11, 10, 11, 10, 11, 11],
        "coverage": {"统计期": "2026-W47", "指标": ["GMV"], "维度": ["日期"],
                     "数据来源": "指标集市/交易域"},
        "chart_version": "v2",
        "replaces_chart_id": old_chart["id"],
    }).json()["entry"]
    print(f"[5] 替代图已登记: id={new_chart['id']} 版本={new_chart['图表版本']} "
          f"合计={sum(new_chart['数据点'])} 替代原图={new_chart['替代图表']}")

    # 7. 恢复排程：辨认旧领取
    decision = client.post(f"/api/domain/report_schedule/inflight/{sid}/resume").json()
    print(f"[6] 恢复辨认: 可恢复={decision['resumable']} 处置={decision['action_required']}")
    print(f"    可回查段落={decision['prepared_sections']}")
    print(f"    说明={decision['message']}")

    # 8. 重新取数
    refetch = client.post(f"/api/domain/report_schedule/inflight/{sid}/refetch", json={
        "new_chart_id": new_chart["id"],
    }).json()
    old_issue = refetch["old_snapshot"]["issue_no"]
    new = refetch["new_snapshot"]
    new_id = new["snapshot_id"]
    print(f"[7] 重新取数: 旧 {old_issue}(v1,合计70)→{refetch['old_snapshot']['status']}；"
          f"新 {new['issue_no']}(v2,合计{new['summary']['total']})，同统计期 {new['period']}")

    # 9. 投递剩余收件人并结束
    for _ in range(3):
        client.post(f"/api/domain/report_schedule/inflight/{new_id}/send?count=1")
    client.post(f"/api/domain/report_schedule/inflight/{new_id}/complete")

    # 10. 核对实际发出的统计期与附件
    new_review = client.get(
        f"/api/domain/report_schedule/inflight/review/{new['issue_no']}").json()
    old_review = client.get(
        f"/api/domain/report_schedule/inflight/review/{old_issue}").json()
    print("[8] 实际发出核对（新发行编号）:")
    for receipt in new_review["receipts"]:
        print(f"    {receipt['recipient']}: {receipt['status']} 统计期={receipt['period']} "
              f"版本={receipt['chart_version']} 时间={receipt['sent_at']}")
    print(f"    附件={new_review['attachment']['attachment_id']} "
          f"内嵌版本={new_review['attachment']['chart_version']} "
          f"汇总合计={new_review['attachment']['summary']['total']} "
          f"段落={new_review['attachment']['sections']}")
    print("[9] 旧发行编号复查（原图数据冻结保留）:")
    print(f"    {old_issue}: 状态={old_review['status']} 版本={old_review['chart_version']} "
          f"合计={old_review['frozen_chart_data']['total']} "
          f"已发回执={sum(1 for r in old_review['receipts'] if r['status'] == '已发送')} 份")

    # 11. 下架图不得被新报告默认引用
    blocked = client.post(f"/api/domain/report_schedule/{task_id}/inflight/prepare", json={
        "chart_id": old_chart["id"],
    })
    print(f"[10] 新报告引用已下架图被拒: HTTP {blocked.status_code} - {blocked.json()['detail']}")


if __name__ == "__main__":
    main()

"""领域业务操作接口：每个模块的计算/处理/聚合等真实业务操作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.schemas import (
    ChartRegisterPayload, InflightPreparePayload, InflightRefetchPayload,
    InflightRemarkPayload,
)
from app.services import SERVICES

router = APIRouter(prefix="/api/domain", tags=["领域业务"])


@router.get("/metric_def/{metric_id}/compute")
def metric_compute(metric_id: int) -> dict[str, Any]:
    """指标聚合计算。"""
    from app.services.metric_def import MetricDefService
    svc = SERVICES.get("metric_def")
    if not svc or not isinstance(svc, MetricDefService):
        raise HTTPException(404, "指标口径服务不可用")
    return svc.domain_compute(metric_id)


@router.get("/dim_query/{query_id}/execute")
def dim_query_execute(query_id: int) -> dict[str, Any]:
    """多维交叉查询执行。"""
    from app.services.dim_query import DimQueryService
    svc = SERVICES.get("dim_query")
    if not svc or not isinstance(svc, DimQueryService):
        raise HTTPException(404, "多维查询服务不可用")
    return svc.execute_query(query_id)


@router.get("/experiment/{experiment_id}/compute-effect")
def experiment_compute(experiment_id: int) -> dict[str, Any]:
    """实验效果计算。"""
    from app.services.experiment import ExperimentService
    svc = SERVICES.get("experiment")
    if not svc or not isinstance(svc, ExperimentService):
        raise HTTPException(404, "实验管理服务不可用")
    return svc.compute_effect(experiment_id)


@router.get("/significance/{task_id}/run-test")
def significance_run_test(task_id: int) -> dict[str, Any]:
    """显著性检验执行。"""
    from app.services.significance import SignificanceService
    svc = SERVICES.get("significance")
    if not svc or not isinstance(svc, SignificanceService):
        raise HTTPException(404, "显著性检验服务不可用")
    return svc.run_test(task_id)


@router.get("/cohort/{cohort_id}/estimate-scale")
def cohort_estimate(cohort_id: int) -> dict[str, Any]:
    """人群规模预估。"""
    from app.services.cohort import CohortService
    svc = SERVICES.get("cohort")
    if not svc or not isinstance(svc, CohortService):
        raise HTTPException(404, "人群圈选服务不可用")
    return svc.estimate_scale(cohort_id)


@router.get("/data_service/{service_id}/invoke")
def data_service_invoke(service_id: int) -> dict[str, Any]:
    """数据服务接口调用。"""
    from app.services.data_service import DataServiceService
    svc = SERVICES.get("data_service")
    if not svc or not isinstance(svc, DataServiceService):
        raise HTTPException(404, "数据服务不可用")
    return svc.invoke_service(service_id)


@router.get("/anomaly_detect/{rule_id}/detect")
def anomaly_detect_run(rule_id: int) -> dict[str, Any]:
    """异常检测执行。"""
    from app.services.anomaly_detect import AnomalyDetectService
    svc = SERVICES.get("anomaly_detect")
    if not svc or not isinstance(svc, AnomalyDetectService):
        raise HTTPException(404, "异常检测服务不可用")
    return svc.detect_anomalies(rule_id)


@router.get("/analysis_chart/{chart_id}/render")
def chart_render(chart_id: int) -> dict[str, Any]:
    """图表数据渲染。"""
    from app.services.analysis_chart import AnalysisChartService
    svc = SERVICES.get("analysis_chart")
    if not svc or not isinstance(svc, AnalysisChartService):
        raise HTTPException(404, "分析图表服务不可用")
    return svc.render_chart_data(chart_id)


@router.get("/aggregate_job/{job_id}/execute")
def aggregate_job_execute(job_id: int) -> dict[str, Any]:
    """预聚合任务执行。"""
    from app.services.aggregate_job import AggregateJobService
    svc = SERVICES.get("aggregate_job")
    if not svc or not isinstance(svc, AggregateJobService):
        raise HTTPException(404, "预聚合任务服务不可用")
    return svc.execute_aggregate(job_id)


@router.get("/drill_down/{path_id}/execute")
def drill_down_execute(path_id: int) -> dict[str, Any]:
    """下钻分析执行。"""
    from app.services.drill_down import DrillDownService
    svc = SERVICES.get("drill_down")
    if not svc or not isinstance(svc, DrillDownService):
        raise HTTPException(404, "下钻分析服务不可用")
    return svc.execute_drill_down(path_id)


@router.get("/data_export/{task_id}/execute")
def data_export_execute(task_id: int) -> dict[str, Any]:
    """数据导出执行。"""
    from app.services.data_export import DataExportService
    svc = SERVICES.get("data_export")
    if not svc or not isinstance(svc, DataExportService):
        raise HTTPException(404, "数据导出服务不可用")
    return svc.execute_export(task_id)


@router.get("/data_freshness/{check_id}/check")
def data_freshness_check(check_id: int) -> dict[str, Any]:
    """数据时效检查执行。"""
    from app.services.data_freshness import DataFreshnessService
    svc = SERVICES.get("data_freshness")
    if not svc or not isinstance(svc, DataFreshnessService):
        raise HTTPException(404, "数据时效服务不可用")
    return svc.run_freshness_check(check_id)


@router.get("/query_cache/{strategy_id}/check-status")
def query_cache_check(strategy_id: int) -> dict[str, Any]:
    """查询缓存状态检查。"""
    from app.services.query_cache import QueryCacheService
    svc = SERVICES.get("query_cache")
    if not svc or not isinstance(svc, QueryCacheService):
        raise HTTPException(404, "查询缓存服务不可用")
    return svc.check_cache_status(strategy_id)


@router.get("/segment_compare/{plan_id}/execute")
def segment_compare_execute(plan_id: int) -> dict[str, Any]:
    """分群对比执行。"""
    from app.services.segment_compare import SegmentCompareService
    svc = SERVICES.get("segment_compare")
    if not svc or not isinstance(svc, SegmentCompareService):
        raise HTTPException(404, "分群对比服务不可用")
    return svc.execute_compare(plan_id)


@router.get("/metric_calibrate/{record_id}/compute")
def metric_calibrate_compute(record_id: int) -> dict[str, Any]:
    """指标校准偏差计算。"""
    from app.services.metric_calibrate import MetricCalibrateService
    svc = SERVICES.get("metric_calibrate")
    if not svc or not isinstance(svc, MetricCalibrateService):
        raise HTTPException(404, "指标校准服务不可用")
    return svc.compute_calibration(record_id)


@router.post("/query_log/log")
def query_log_record() -> dict[str, Any]:
    """查询操作记录。"""
    from app.services.query_log import QueryLogService
    svc = SERVICES.get("query_log")
    if not svc or not isinstance(svc, QueryLogService):
        raise HTTPException(404, "查询日志服务不可用")
    return svc.log_query()


@router.get("/data_sample/{config_id}/execute")
def data_sample_execute(config_id: int) -> dict[str, Any]:
    """数据采样执行。"""
    from app.services.data_sample import DataSampleService
    svc = SERVICES.get("data_sample")
    if not svc or not isinstance(svc, DataSampleService):
        raise HTTPException(404, "数据采样服务不可用")
    return svc.execute_sampling(config_id)


@router.get("/report_schedule/{task_id}/generate")
def report_schedule_generate(task_id: int) -> dict[str, Any]:
    """报告生成。"""
    from app.services.report_schedule import ReportScheduleService
    svc = SERVICES.get("report_schedule")
    if not svc or not isinstance(svc, ReportScheduleService):
        raise HTTPException(404, "报告调度服务不可用")
    return svc.generate_report(task_id)


# ----------------------------------------------------------------------
# 在途报告取数快照链路：分析图表 ⇄ 报告调度
# ----------------------------------------------------------------------
@router.post("/analysis_chart/register")
def analysis_chart_register(payload: ChartRegisterPayload) -> dict[str, Any]:
    """登记带版本、数据点和覆盖范围的图表（支持登记替代图）。"""
    from app.services.analysis_chart import AnalysisChartService
    svc = SERVICES.get("analysis_chart")
    if not svc or not isinstance(svc, AnalysisChartService):
        raise HTTPException(404, "分析图表服务不可用")
    entry, missing = svc.register_chart(
        payload.values,
        points=payload.points,
        coverage=payload.coverage,
        chart_version=payload.chart_version,
        replaces_chart_id=payload.replaces_chart_id,
    )
    if entry is None:
        raise HTTPException(400, f"缺少必填字段：{'、'.join(missing)}")
    return {"ok": True, "message": "图表已登记并发布", "entry": entry}


@router.post("/report_schedule/{task_id}/inflight/prepare")
def report_inflight_prepare(task_id: int, payload: InflightPreparePayload) -> dict[str, Any]:
    """领取图表数据，生成在途报告取数快照并准备周报。"""
    from app.services.report_schedule import ReportScheduleService
    svc = SERVICES.get("report_schedule")
    if not svc or not isinstance(svc, ReportScheduleService):
        raise HTTPException(404, "报告调度服务不可用")
    result = svc.prepare_inflight_issue(
        task_id,
        payload.chart_id,
        recipients=payload.recipients,
        period=payload.period,
        hold=payload.hold,
        remark=payload.remark,
    )
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@router.post("/report_schedule/inflight/{snapshot_id}/send")
def report_inflight_send(snapshot_id: int, count: int = 1) -> dict[str, Any]:
    """投递下一批回执（支持发送到一半停住）。"""
    from app.services.report_schedule import ReportScheduleService
    svc = SERVICES.get("report_schedule")
    if not svc or not isinstance(svc, ReportScheduleService):
        raise HTTPException(404, "报告调度服务不可用")
    result = svc.send_next(snapshot_id, count=count)
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@router.post("/report_schedule/inflight/{snapshot_id}/hold")
def report_inflight_hold(snapshot_id: int, payload: InflightRemarkPayload | None = None) -> dict[str, Any]:
    """暂扣未发送回执。"""
    from app.services.report_schedule import ReportScheduleService
    svc = SERVICES.get("report_schedule")
    if not svc or not isinstance(svc, ReportScheduleService):
        raise HTTPException(404, "报告调度服务不可用")
    remark = payload.remark if payload else None
    result = svc.hold_sending(snapshot_id, remark=remark)
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@router.post("/report_schedule/inflight/{snapshot_id}/resume")
def report_inflight_resume(snapshot_id: int) -> dict[str, Any]:
    """恢复排程：辨认旧领取是否仍可发送、哪些数据须重新领取。"""
    from app.services.report_schedule import ReportScheduleService
    svc = SERVICES.get("report_schedule")
    if not svc or not isinstance(svc, ReportScheduleService):
        raise HTTPException(404, "报告调度服务不可用")
    result = svc.resume_schedule(snapshot_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/report_schedule/inflight/{snapshot_id}/refetch")
def report_inflight_refetch(snapshot_id: int, payload: InflightRefetchPayload) -> dict[str, Any]:
    """用替代图重新取数：旧快照归档，生成新发行编号快照。"""
    from app.services.report_schedule import ReportScheduleService
    svc = SERVICES.get("report_schedule")
    if not svc or not isinstance(svc, ReportScheduleService):
        raise HTTPException(404, "报告调度服务不可用")
    result = svc.refetch_with_chart(snapshot_id, payload.new_chart_id, remark=payload.remark)
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@router.post("/report_schedule/inflight/{snapshot_id}/complete")
def report_inflight_complete(snapshot_id: int) -> dict[str, Any]:
    """报告结束并归档快照。"""
    from app.services.report_schedule import ReportScheduleService
    svc = SERVICES.get("report_schedule")
    if not svc or not isinstance(svc, ReportScheduleService):
        raise HTTPException(404, "报告调度服务不可用")
    result = svc.complete_issue(snapshot_id)
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@router.get("/report_schedule/inflight/review/{issue_no}")
def report_inflight_review(issue_no: str) -> dict[str, Any]:
    """按发行编号复查已发周报的原图冻结数据。"""
    from app.services.report_schedule import ReportScheduleService
    svc = SERVICES.get("report_schedule")
    if not svc or not isinstance(svc, ReportScheduleService):
        raise HTTPException(404, "报告调度服务不可用")
    result = svc.review_issue(issue_no)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/report_schedule/{task_id}/inflight/snapshots")
def report_inflight_snapshots(task_id: int) -> dict[str, Any]:
    """查看任务下在途/历史取数快照与状态流转。"""
    from app.services.report_schedule import ReportScheduleService
    svc = SERVICES.get("report_schedule")
    if not svc or not isinstance(svc, ReportScheduleService):
        raise HTTPException(404, "报告调度服务不可用")
    return svc.list_inflight_snapshots(task_id)
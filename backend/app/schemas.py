"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class ChartRegisterPayload(BaseModel):
    """登记带确定数据值与覆盖范围的图表（可作为替代图）。"""
    values: dict[str, Any] = Field(default_factory=dict)
    points: list[float] | None = None
    coverage: dict[str, Any] | None = None
    chart_version: str | None = None
    replaces_chart_id: int | None = None


class InflightPreparePayload(BaseModel):
    """在途报告取数：领取图表数据并冻结快照。"""
    chart_id: int
    recipients: list[str] | None = None
    period: str | None = None
    hold: bool = False
    remark: str | None = None


class InflightRefetchPayload(BaseModel):
    """用替代图重新取数。"""
    new_chart_id: int
    remark: str | None = None


class InflightRemarkPayload(BaseModel):
    remark: str | None = None

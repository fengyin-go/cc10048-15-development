/**
 * 报告调度领域逻辑（前端）：在途报告取数快照、分段投递、恢复与重新取数。
 * 与后端 app/services/report_schedule.py 的状态机保持一致。
 */
import { request } from '@/api/client'
import type { ChartCoverage, ChartSeries } from '@/domain/analysis_chart'

// 在途快照状态
export const SNAPSHOT_STATUS = {
  inflight: '在途',
  hold: '发送暂扣',
  refetch: '待重新取数',
  archived: '已归档',
} as const

// 图表领取状态
export const CLAIM_STATUS = {
  active: '可发送',
  hold: '暂扣中',
  stale: '须重新领取',
} as const

export type Receipt = {
  receipt_id: number
  recipient: string
  status: '已发送' | '待发送' | '已暂扣'
  issue_no: string
  period: string
  chart_version: string
  sent_at: string | null
}

export type SnapshotEvent = {
  event_id: number
  action: string
  detail: string
  at: string
}

export type InflightSnapshot = {
  snapshot_id: number
  issue_no: string
  task_id: number
  period: string
  chart_id: number
  chart_code: string
  chart_version: string
  coverage: ChartCoverage
  chart_data: { series: ChartSeries[]; total: number }
  sections: Record<string, unknown>
  summary: { point_count: number; total: number; avg: number; max: number; min: number }
  attachment: {
    attachment_id: string
    issue_no: string
    period: string
    chart_version: string
    summary: { total: number }
  }
  claim: { chart_id: number; chart_version: string; status: string; remark?: string | null }
  recipients: string[]
  receipts: Receipt[]
  status: string
  events: SnapshotEvent[]
  replaces_snapshot_id?: number
  replaces_issue_no?: string
  archived_at: string | null
}

export type ResumeDecision = {
  snapshot_id: number
  issue_no: string
  period: string
  chart_id: number
  chart_version: string
  snapshot_status: string
  claim_status: string
  prepared_sections: string[]
  receipts: Receipt[]
  resumable: boolean
  action_required: '继续投递' | '重新取数' | '归档复查'
  message: string
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await request(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail ?? '报告调度操作失败')
  }
  return (await response.json()) as T
}

/** 领取图表数据，生成在途报告取数快照；hold=true 时回执全部暂扣。 */
export function prepareInflightIssue(
  taskId: number,
  chartId: number,
  options: { recipients?: string[]; period?: string; hold?: boolean; remark?: string } = {},
): Promise<InflightSnapshot> {
  return postJson(`/api/domain/report_schedule/${taskId}/inflight/prepare`, {
    chart_id: chartId,
    recipients: options.recipients,
    period: options.period,
    hold: options.hold ?? false,
    remark: options.remark,
  })
}

/** 投递下一批回执（发送到一半可停住）。 */
export function sendNext(snapshotId: number, count = 1): Promise<{ sent: Receipt[] }> {
  return postJson(`/api/domain/report_schedule/inflight/${snapshotId}/send?count=${count}`)
}

/** 暂扣未发送回执。 */
export function holdSending(snapshotId: number, remark?: string): Promise<InflightSnapshot> {
  return postJson(`/api/domain/report_schedule/inflight/${snapshotId}/hold`, { remark })
}

/** 恢复排程：辨认旧领取是否仍可发送、哪些数据须重新领取。 */
export function resumeSchedule(snapshotId: number): Promise<ResumeDecision> {
  return postJson(`/api/domain/report_schedule/inflight/${snapshotId}/resume`)
}

/** 用替代图重新取数：旧快照归档，生成新发行编号快照。 */
export function refetchWithChart(
  snapshotId: number,
  newChartId: number,
  remark?: string,
): Promise<{ old_snapshot: InflightSnapshot; new_snapshot: InflightSnapshot; message: string }> {
  return postJson(`/api/domain/report_schedule/inflight/${snapshotId}/refetch`, {
    new_chart_id: newChartId,
    remark,
  })
}

/** 报告结束并归档。 */
export function completeIssue(snapshotId: number): Promise<InflightSnapshot> {
  return postJson(`/api/domain/report_schedule/inflight/${snapshotId}/complete`)
}

/** 按发行编号复查已发周报的原图冻结数据。 */
export async function reviewIssue(issueNo: string): Promise<InflightSnapshot> {
  const response = await request(
    `/api/domain/report_schedule/inflight/review/${encodeURIComponent(issueNo)}`,
  )
  if (!response.ok) throw new Error('发行编号复查失败')
  return (await response.json()) as InflightSnapshot
}

export type SnapshotListItem = {
  snapshot_id: number
  issue_no: string
  task_id: number
  period: string
  chart_id: number
  chart_version: string
  status: string
  claim_status: string
  sent: number
  held: number
  waiting: number
  events: SnapshotEvent[]
}

export async function listInflightSnapshots(taskId: number): Promise<SnapshotListItem[]> {
  const response = await request(
    `/api/domain/report_schedule/${taskId}/inflight/snapshots`,
  )
  if (!response.ok) throw new Error('在途快照读取失败')
  const body = (await response.json()) as { total: number; items: SnapshotListItem[] }
  return body.items
}

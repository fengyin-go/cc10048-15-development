/**
 * 分析图表领域逻辑（前端）：版本化图表数据、替代图登记。
 * 与后端 app/services/analysis_chart.py 的领域规则保持一致。
 */
import { request } from '@/api/client'

/** 图表覆盖范围：统计期、指标、维度与数据来源，随快照冻结。 */
export type ChartCoverage = {
  统计期: string
  指标: string[]
  维度: string[]
  数据来源?: string
}

export type ChartSeries = {
  name: string
  x_field: string
  x: string[]
  y_field: string
  y: number[]
  type: string
}

/** 登记图表入参；points 决定真实数据版本，replacesChartId 标记替代关系。 */
export type RegisterChartInput = {
  values: Record<string, string>
  points?: number[]
  coverage?: ChartCoverage
  chartVersion?: string
  replacesChartId?: number
}

export type RegisteredChart = {
  id: number
  status: string
  图表标识: string
  图表版本: string
  覆盖范围: ChartCoverage
  数据点?: number[]
  替代图表?: number
}

export async function registerChart(input: RegisterChartInput): Promise<RegisteredChart> {
  const response = await request('/api/domain/analysis_chart/register', {
    method: 'POST',
    body: JSON.stringify({
      values: input.values,
      points: input.points,
      coverage: input.coverage,
      chart_version: input.chartVersion,
      replaces_chart_id: input.replacesChartId,
    }),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail ?? '图表登记失败')
  }
  return (await response.json()).entry as RegisteredChart
}

export type RenderedChart = {
  chart_id: number
  chart_name: string
  chart_version: string
  chart_type: string
  coverage: ChartCoverage
  total: number
  data: ChartSeries[]
}

export async function renderChart(chartId: number): Promise<RenderedChart> {
  const response = await request(`/api/domain/analysis_chart/${chartId}/render`)
  if (!response.ok) throw new Error('图表渲染失败')
  return (await response.json()) as RenderedChart
}

/** 下架后不允许新报告引用的判定，与后端 prepare 接口的 409 规则对应。 */
export function isChartReferenceable(chart: Pick<RegisteredChart, 'status'>): boolean {
  return chart.status !== '已下架'
}

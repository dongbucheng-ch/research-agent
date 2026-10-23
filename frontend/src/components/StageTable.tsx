import { Table, Tag, Typography } from 'antd'

import type { JobRun } from '../api/types'

export interface StageInfo {
  key: string
  label: string
  status: 'pending' | 'running' | 'success' | 'skipped' | 'error'
  seconds?: number
  message?: string
  counters?: Record<string, unknown>
}

export const STAGE_STATUS_META: Record<StageInfo['status'], { label: string; color: string }> = {
  pending: { label: '等待', color: 'default' },
  running: { label: '进行中', color: 'processing' },
  success: { label: '成功', color: 'success' },
  skipped: { label: '跳过', color: 'warning' },
  error: { label: '失败', color: 'error' },
}

/** 读取后端阶段快照:运行中优先 progress(实时),结束后用 result.stages。 */
export function readStagesFromJob(job?: JobRun | null): StageInfo[] {
  const result = job?.result as
    | { stages?: unknown; progress?: { stages?: unknown } }
    | undefined
  const raw = result?.progress?.stages ?? result?.stages
  if (!Array.isArray(raw)) return []
  return raw.filter(
    (row): row is StageInfo =>
      !!row && typeof row === 'object' && typeof (row as StageInfo).key === 'string',
  )
}

/** 实时计数:优先取 ``progress.stages[].counters``(运行中每秒刷新),
 *  回退到任务结束才写入的顶层 ``result.*`` 字段(旧任务)。 */
export function stageCounter(
  job: JobRun | null | undefined,
  stageKey: string,
  field: string,
): number | null {
  const stage = readStagesFromJob(job).find((row) => row.key === stageKey)
  const raw = (stage?.counters ?? {})[field]
  const value = typeof raw === 'number' ? raw : Number(raw)
  return Number.isFinite(value) ? value : null
}

/** ``stageCounter`` 的兜底版本:实时值缺失时用 ``fallback``。 */
export function liveCounter(
  job: JobRun | null | undefined,
  stageKey: string,
  field: string,
  fallback: number,
): number {
  return stageCounter(job, stageKey, field) ?? fallback
}

export default function StageTable({
  stages,
  emptyText = '该任务没有阶段数据(旧任务),重新执行即可看到每个环节的耗时',
}: {
  stages: StageInfo[]
  emptyText?: string
}) {
  return (
    <Table<StageInfo>
      size="small"
      rowKey="key"
      pagination={false}
      dataSource={stages}
      locale={{ emptyText }}
      columns={[
        { title: '环节', dataIndex: 'label', width: 110 },
        {
          title: '状态',
          dataIndex: 'status',
          width: 100,
          render: (value: StageInfo['status']) => (
            <Tag color={STAGE_STATUS_META[value]?.color}>{STAGE_STATUS_META[value]?.label ?? value}</Tag>
          ),
        },
        {
          title: '耗时',
          dataIndex: 'seconds',
          width: 100,
          render: (value?: number) => (typeof value === 'number' ? `${value.toFixed(2)}s` : '—'),
        },
        {
          title: '说明',
          dataIndex: 'message',
          render: (value?: string) => <span style={{ fontSize: 12 }}>{value || '—'}</span>,
        },
      ]}
    />
  )
}

export function StageSummaryText({ stages }: { stages: StageInfo[] }) {
  const total = stages.reduce((acc, stage) => acc + (stage.seconds ?? 0), 0)
  return (
    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
      总耗时 {total.toFixed(1)}s
    </Typography.Text>
  )
}

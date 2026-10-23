import {
  CheckCircleFilled,
  CloseCircleFilled,
  LoadingOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { Button, Tag, Tooltip, Typography } from 'antd'
import type { ReactNode } from 'react'

export type StageState = 'pending' | 'running' | 'success' | 'error'

export interface PipelineStat {
  label: string
  value: ReactNode
  /** 决策指标:占满整行并以 16px/600 呈现,其余降为次级 */
  primary?: boolean
}

export interface PipelineStage {
  key: string
  title: string
  desc: string
  /** 阶段识别色:仅用于图标底与进度线,不承载状态语义 */
  color: string
  /** 图标底色 */
  soft: string
  icon: ReactNode
  state: StageState
  stats: PipelineStat[]
  action: {
    label: string
    onClick: () => void
    disabled?: boolean
    loading?: boolean
    /** 主行动:同一屏只允许一个,其余为次级按钮 */
    emphasis?: 'primary' | 'default'
  }
  note?: string
}

const STATE_TEXT: Record<StageState, string> = {
  pending: '待执行',
  running: '进行中',
  success: '成功',
  error: '失败',
}

/** 状态指示:颜色一律由状态决定(见 .pipeline-dot 样式),阶段色不参与。 */
function StateDot({ state }: { state: StageState }) {
  if (state === 'success') return <CheckCircleFilled />
  if (state === 'error') return <CloseCircleFilled />
  if (state === 'running') return <LoadingOutlined spin />
  return <span className="pipeline-dot-empty" />
}

export default function PipelineBoard({
  title,
  tag,
  schedule,
  refreshing,
  onRefresh,
  stages,
}: {
  title: string
  tag?: ReactNode
  schedule?: ReactNode
  refreshing?: boolean
  onRefresh?: () => void
  stages: PipelineStage[]
}) {
  return (
    <div className="pipeline">
      <div className="pipeline-header">
        <div className="pipeline-header-left">
          <span className="pipeline-kicker">Pipeline</span>
          <span className="pipeline-title">{title}</span>
          {tag}
        </div>
        <div className="pipeline-header-right">
          {schedule && <span className="pipeline-schedule">{schedule}</span>}
          {onRefresh && (
            <Tooltip title="刷新状态">
              <ReloadOutlined
                spin={refreshing}
                className="pipeline-refresh"
                onClick={() => onRefresh()}
              />
            </Tooltip>
          )}
        </div>
      </div>

      <div className="pipeline-grid">
        {stages.map((stage, index) => (
          <div className="pipeline-node" key={stage.key}>
            <div className="pipeline-node-head">
              <span className={`pipeline-dot state-${stage.state}`}>
                <StateDot state={stage.state} />
              </span>
              {index < stages.length - 1 && (
                <span
                  className="pipeline-line"
                  style={{
                    background:
                      stage.state === 'success'
                        ? `linear-gradient(90deg, ${stage.color} 0%, #f0f0f0 100%)`
                        : '#f0f0f0',
                  }}
                />
              )}
            </div>
            <div className="pipeline-node-title">{stage.title}</div>
            <div className="pipeline-node-desc">{stage.desc}</div>
          </div>
        ))}
      </div>

      <div className="pipeline-cards">
        {stages.map((stage) => (
          <div className="pipeline-card" key={stage.key}>
            <div className="pipeline-card-head">
              <span
                className="pipeline-card-icon"
                style={{ background: stage.soft, color: stage.color }}
              >
                {stage.icon}
              </span>
              <div className="pipeline-card-title">{stage.title}</div>
              <span className={`pipeline-card-state state-${stage.state}`}>
                {STATE_TEXT[stage.state]}
              </span>
            </div>
            <div className="pipeline-result">
              <div className="pipeline-result-label">执行结果</div>
              <div className="pipeline-stats">
                {stage.stats.map((stat) => (
                  <div
                    className={stat.primary ? 'pipeline-stat is-primary' : 'pipeline-stat'}
                    key={stat.label}
                  >
                    <div className="k">{stat.label}</div>
                    <div className="v">{stat.value}</div>
                  </div>
                ))}
              </div>
            </div>
            <Button
              block
              type={stage.action.emphasis === 'primary' ? 'primary' : 'default'}
              loading={stage.action.loading}
              disabled={stage.action.disabled}
              onClick={stage.action.onClick}
            >
              {stage.action.label}
            </Button>
            <Typography.Text className="pipeline-note" title={stage.note ?? undefined}>
              {stage.note ?? '\u00a0'}
            </Typography.Text>
          </div>
        ))}
      </div>
    </div>
  )
}

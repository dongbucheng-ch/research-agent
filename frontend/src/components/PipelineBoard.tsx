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
}

export interface PipelineStage {
  key: string
  title: string
  desc: string
  /** 主色:图标、按钮、进度线 */
  color: string
  /** 图标底色 */
  soft: string
  icon: ReactNode
  state: StageState
  stats: PipelineStat[]
  action: { label: string; onClick: () => void; disabled?: boolean; loading?: boolean }
  note?: string
}

const STATE_TEXT: Record<StageState, string> = {
  pending: '待执行',
  running: '进行中',
  success: '成功',
  error: '失败',
}

function StateDot({ state, color }: { state: StageState; color: string }) {
  if (state === 'success') return <CheckCircleFilled style={{ color }} />
  if (state === 'error') return <CloseCircleFilled style={{ color: '#ff4d4f' }} />
  if (state === 'running') return <LoadingOutlined style={{ color: '#1677ff' }} spin />
  return (
    <span
      style={{
        width: 14,
        height: 14,
        borderRadius: '50%',
        border: '1.5px solid #d9d9d9',
        display: 'inline-block',
      }}
    />
  )
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
              <span className="pipeline-dot">
                <StateDot state={stage.state} color={stage.color} />
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
              <div style={{ minWidth: 0 }}>
                <div className="pipeline-card-title">{stage.title}</div>
                <div className={`pipeline-card-state state-${stage.state}`}>
                  {STATE_TEXT[stage.state]}
                </div>
              </div>
            </div>
            <div className="pipeline-result">
              <div className="pipeline-result-label">执行结果</div>
              <div className="pipeline-stats">
                {stage.stats.map((stat) => (
                  <div className="pipeline-stat" key={stat.label}>
                    <div className="k">{stat.label}</div>
                    <div className="v">{stat.value}</div>
                  </div>
                ))}
              </div>
            </div>
            <Button
              block
              type="primary"
              loading={stage.action.loading}
              disabled={stage.action.disabled}
              onClick={stage.action.onClick}
              style={
                stage.action.disabled
                  ? undefined
                  : { background: stage.color, borderColor: stage.color }
              }
            >
              {stage.action.label}
            </Button>
            <Typography.Text className="pipeline-note">{stage.note ?? '\u00a0'}</Typography.Text>
          </div>
        ))}
      </div>
    </div>
  )
}

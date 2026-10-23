import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Button, Input, Space, Tooltip, message } from 'antd'
import {
  CopyOutlined,
  DownloadOutlined,
  SearchOutlined,
  VerticalAlignBottomOutlined,
} from '@ant-design/icons'

interface LogEntry {
  /** 原始日志里的行号(1 基),跳过空行后仍保留真实行号 */
  line: number
  tag: string
  message: string
}

type Severity = 'error' | 'warn' | 'info'

/**
 * 级别只按「标签 + 结构化短语」判定,不对整行做关键词匹配。
 * 依据:实测 4595 行真实日志,消息里常夹带条目标题(自由文本),标题中的「异常/警告/部分」
 * 会把整行误判;而「跳过」这类词命中 3431 行(每条低于门槛的候选一行),
 * 若按关键词着色则有 78.6% 的行变警示色 → 颜色不再表示任何信号。
 * 收敛到白名单后实测:error 0.5% / warn 4.5% / info 95.0%(4595 行语料)。
 * 「抓取 0 条」= 信源未产出,与「诊断」页的空抓取判定保持一致。
 */
const SEVERITY_RULES: Record<string, { error?: RegExp; warn?: RegExp }> = {
  系统: { error: /失败|错误|异常|超时/, warn: /降级|未配置|不足|已跳过|已取消|没有可用/ },
  采集: { error: /抓取失败/, warn: /抓取 0 条|兜底/ },
  提示: { warn: /./ },
  配置: { error: /失败/, warn: /降级|未配置|无可用/ },
  召回: { error: /失败/, warn: /没有达到|未命中/ },
  过滤: { error: /失败/, warn: /为空|回退/ },
  扩词: { error: /失败/, warn: /不足|跳过/ },
  补量: { error: /失败/, warn: /跳过/ },
  大纲: { error: /失败/, warn: /兜底/ },
  写作: { error: /失败/, warn: /跳过/ },
  生成: { error: /失败/, warn: /不足|降级|截断/ },
  合成: { error: /失败/, warn: /兜底|拼接/ },
  富化: { error: /失败/, warn: /降级|不足|上限/ },
  推送: { error: /失败/, warn: /跳过|不存在|未启用/ },
  // 完成行是汇总,「失败源 0 个」不该变红,只有计数非零才降级提示
  完成: { warn: /失败源 [1-9]|降级 [1-9]/ },
  标准化: { error: /失败/, warn: /^「[^」]{0,40}」本轮无新增候选/ },
  去重: { warn: /均已存在/ },
  // 「评分/入库」是每候选一行的高频标签(实测「低于门槛跳过」3422 行),
  // 且消息尾部拼条目标题,着色只会制造噪声,因此整类不着色。
}

function severityOf(tag: string, message: string): Severity {
  const rule = SEVERITY_RULES[tag]
  if (!rule) return 'info'
  if (rule.error?.test(message)) return 'error'
  if (rule.warn?.test(message)) return 'warn'
  return 'info'
}

/** 标签色阶:终端里的等级用文字颜色表达,不用填充胶囊。 */
const TAG_TONES: Record<string, string> = {
  系统: 'dim',
  提示: 'dim',
  配置: 'cyan',
  标准化: 'cyan',
  信源: 'blue',
  采集: 'blue',
  召回: 'blue',
  大纲: 'blue',
  写作: 'blue',
  去重: 'purple',
  过滤: 'purple',
  富化: 'gold',
  评分: 'orange',
  生成: 'gold',
  合成: 'gold',
  入库: 'green',
  完成: 'green',
  扩词: 'magenta',
  推送: 'magenta',
  补量: 'volcano',
}

export function parseLogLines(log: string): LogEntry[] {
  return String(log || '')
    .split('\n')
    .map((text, index) => ({ line: index + 1, text: text.trimEnd() }))
    .filter((item) => item.text.trim().length > 0)
    .map((item) => {
      const match = /^\[([^\]]{1,12})\]\s*(.*)$/.exec(item.text.trim())
      return match
        ? { line: item.line, tag: match[1], message: match[2] }
        : { line: item.line, tag: '', message: item.text }
    })
}

/** 级别统计与最近失败样本:摘要条与工具条共用同一套判定,避免两处各写一份。 */
export function summarizeLog(log: string) {
  const entries = parseLogLines(log)
  const errors = entries.filter((entry) => severityOf(entry.tag, entry.message) === 'error')
  const warn = entries.filter((entry) => severityOf(entry.tag, entry.message) === 'warn').length
  return { total: entries.length, error: errors.length, warn, errorSamples: errors.slice(-3) }
}

/** 命中即高亮,不隐藏上下文(日志里过滤掉行比高亮更危险)。 */
function renderHighlighted(text: string, query: string): ReactNode {
  if (!query) return text
  const haystack = text.toLowerCase()
  const needle = query.toLowerCase()
  const parts: ReactNode[] = []
  let cursor = 0
  let hit = haystack.indexOf(needle)
  let key = 0
  while (hit !== -1) {
    if (hit > cursor) parts.push(text.slice(cursor, hit))
    parts.push(<mark key={key++}>{text.slice(hit, hit + needle.length)}</mark>)
    cursor = hit + needle.length
    hit = haystack.indexOf(needle, cursor)
  }
  if (!parts.length) return text
  parts.push(text.slice(cursor))
  return parts
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const area = document.createElement('textarea')
    area.value = text
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    document.execCommand('copy')
    area.remove()
  }
}

function downloadText(text: string, filename: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export default function JobLogViewer({
  log,
  rows = 16,
  highlightSeverity = false,
  showLineNumbers = false,
  toolbar = false,
  fill = false,
  filename,
  running = false,
}: {
  log: string
  /** 可视行数。终端按整行排版,高度 = 行数 × 行高,最后一行不会被裁成半行 */
  rows?: number
  /** 按内容推断级别着色(失败/警告),默认关闭以保持既有调用方外观 */
  highlightSeverity?: boolean
  /** 行号列:让留白读作终端内边距,并支持「第 N 行」引用 */
  showLineNumbers?: boolean
  /** 工具条:级别统计 + 搜索高亮 + 跟随 + 复制 + 下载 */
  toolbar?: boolean
  /** 高度跟随容器(抽屉内使用),忽略 rows */
  fill?: boolean
  filename?: string
  /** 任务仍在运行:日志是实时追加的,空日志时提示等待而不是「无日志」 */
  running?: boolean
}) {
  const entries = useMemo(() => parseLogLines(log), [log])
  const stats = useMemo(() => (highlightSeverity ? summarizeLog(log) : null), [log, highlightSeverity])
  const [query, setQuery] = useState('')
  const [follow, setFollow] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)

  const hits = useMemo(() => {
    if (!query) return 0
    const needle = query.toLowerCase()
    return entries.reduce((acc, entry) => {
      const text = `${entry.tag} ${entry.message}`.toLowerCase()
      let count = 0
      let index = text.indexOf(needle)
      while (index !== -1) {
        count += 1
        index = text.indexOf(needle, index + needle.length)
      }
      return acc + count
    }, 0)
  }, [entries, query])

  useEffect(() => {
    if (!follow) return
    const node = bodyRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [follow, log])

  const paneStyle = { '--job-log-rows': rows } as CSSProperties

  return (
    <div className="job-log-shell">
      {toolbar && (
        <div className="job-log-toolbar">
          {stats && (
            <Space size={14} className="job-log-stat">
              <span>{stats.total} 行</span>
              <span className="is-error">{stats.error} 失败</span>
              <span className="is-warn">{stats.warn} 警告</span>
            </Space>
          )}
          <Input
            size="small"
            allowClear
            placeholder="搜索日志"
            prefix={<SearchOutlined />}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            style={{ width: 200 }}
          />
          {query && <span className="job-log-hit">{hits} 处匹配</span>}
          <span className="job-log-toolbar-spacer" />
          <Tooltip title="有新日志时自动滚到底部">
            <Button
              size="small"
              type={follow ? 'primary' : 'default'}
              icon={<VerticalAlignBottomOutlined />}
              onClick={() => setFollow((value) => !value)}
            >
              跟随
            </Button>
          </Tooltip>
          <Button
            size="small"
            icon={<CopyOutlined />}
            disabled={!entries.length}
            onClick={async () => {
              await copyText(log)
              message.success('日志已复制')
            }}
          >
            复制
          </Button>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            disabled={!entries.length}
            onClick={() => downloadText(log, filename ?? 'job.log')}
          >
            下载
          </Button>
        </div>
      )}
      <div
        ref={bodyRef}
        className={fill ? 'job-log-viewer job-log-viewer--fill' : 'job-log-viewer'}
        style={paneStyle}
      >
        {entries.length ? (
          entries.map((entry) => (
            <div
              key={`${entry.line}-${entry.tag}`}
              className={[
                'job-log-line',
                showLineNumbers ? 'job-log-line--numbered' : '',
                highlightSeverity ? `job-log-line--${severityOf(entry.tag, entry.message)}` : '',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              {showLineNumbers && <span className="job-log-ln">{entry.line}</span>}
              <span className="job-log-body">
                {entry.tag && (
                  <span className={`job-log-tag job-log-tag--${TAG_TONES[entry.tag] ?? 'dim'}`}>
                    [{entry.tag}]
                  </span>
                )}
                <span className="job-log-msg">{renderHighlighted(entry.message, query)}</span>
              </span>
            </div>
          ))
        ) : (
          <div className="job-log-line job-log-empty">
            {running ? '任务运行中,日志实时追加中…(每 3 秒刷新)' : '(无日志)'}
          </div>
        )}
      </div>
    </div>
  )
}

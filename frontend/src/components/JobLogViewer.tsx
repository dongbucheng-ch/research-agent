import { Space, Tag } from 'antd'
import { useMemo, useState } from 'react'

interface LogEntry {
  tag: string
  message: string
}

const TAG_COLORS: Record<string, string> = {
  系统: 'default',
  配置: 'cyan',
  信源: 'geekblue',
  采集: 'blue',
  标准化: 'cyan',
  去重: 'purple',
  富化: 'gold',
  评分: 'orange',
  入库: 'green',
  扩词: 'magenta',
  补量: 'volcano',
  召回: 'geekblue',
  生成: 'gold',
  过滤: 'purple',
  大纲: 'blue',
  写作: 'blue',
  合成: 'gold',
  推送: 'magenta',
  提示: 'warning',
  完成: 'success',
}

export function parseLogLines(log: string): LogEntry[] {
  return String(log || '')
    .split('\n')
    .map((line) => line.trimEnd())
    .filter((line) => line.trim().length > 0)
    .map((line) => {
      const match = /^\[([^\]]{1,12})\]\s*(.*)$/.exec(line.trim())
      return match ? { tag: match[1], message: match[2] } : { tag: '', message: line }
    })
}

export default function JobLogViewer({ log, height = 420 }: { log: string; height?: number }) {
  const entries = useMemo(() => parseLogLines(log), [log])
  const tags = useMemo(
    () => Array.from(new Set(entries.map((entry) => entry.tag).filter(Boolean))),
    [entries],
  )
  const [activeTag, setActiveTag] = useState<string>('all')
  const shown = activeTag === 'all' ? entries : entries.filter((entry) => entry.tag === activeTag)

  if (!entries.length) return <div className="job-log-viewer">(无日志)</div>

  return (
    <div>
      {tags.length > 1 && (
        <Space wrap size={4} style={{ marginBottom: 8 }}>
          <Tag.CheckableTag checked={activeTag === 'all'} onChange={() => setActiveTag('all')}>
            全部 {entries.length}
          </Tag.CheckableTag>
          {tags.map((tag) => (
            <Tag.CheckableTag key={tag} checked={activeTag === tag} onChange={() => setActiveTag(tag)}>
              {tag} {entries.filter((entry) => entry.tag === tag).length}
            </Tag.CheckableTag>
          ))}
        </Space>
      )}
      <div className="job-log-viewer" style={{ maxHeight: height, overflow: 'auto' }}>
        {shown.map((entry, index) => (
          <div key={`${index}-${entry.tag}`} className="job-log-line">
            {entry.tag && (
              <Tag color={TAG_COLORS[entry.tag] ?? 'default'} style={{ marginInlineEnd: 8 }}>
                {entry.tag}
              </Tag>
            )}
            <span>{entry.message}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

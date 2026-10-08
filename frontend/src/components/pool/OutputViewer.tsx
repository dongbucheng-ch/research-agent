import { Button, Segmented, Space, Spin, Typography, message } from 'antd'
import { useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export type OutputViewMode = 'preview' | 'source' | 'json'

const STORAGE_KEY = 'ra:output-view-mode'

function readStoredMode(): OutputViewMode {
  const stored = localStorage.getItem(STORAGE_KEY)
  return stored === 'source' || stored === 'json' ? stored : 'preview'
}

interface Props {
  /** 产出物 markdown 源码(digest/article 的 content_md)。 */
  contentMd: string
  /** JSON 模式的结构化信封;为 null 时显示加载态。 */
  payload: Record<string, unknown> | null
  loading?: boolean
}

/** 产出物查看器:预览 / 源码 / JSON 三模式,选择记忆到 localStorage。 */
export default function OutputViewer({ contentMd, payload, loading }: Props) {
  const [mode, setMode] = useState<OutputViewMode>(readStoredMode)

  const jsonText = useMemo(() => (payload ? JSON.stringify(payload, null, 2) : ''), [payload])
  const sourceText = contentMd ?? ''

  const copy = () => {
    if (mode === 'json') {
      if (!jsonText) return
      navigator.clipboard?.writeText(jsonText)
      message.success('已复制 JSON')
      return
    }
    navigator.clipboard?.writeText(sourceText)
    message.success('已复制 Markdown')
  }

  return (
    <div className="output-viewer">
      <div className="output-viewer-toolbar">
        <Segmented
          size="small"
          value={mode}
          onChange={(value) => {
            const next = value as OutputViewMode
            setMode(next)
            localStorage.setItem(STORAGE_KEY, next)
          }}
          options={[
            { label: '预览', value: 'preview' },
            { label: '源码', value: 'source' },
            { label: 'JSON', value: 'json' },
          ]}
        />
        <Space size={8}>
          {mode === 'source' && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              content_md · {sourceText.length} 字符
            </Typography.Text>
          )}
          {(loading || (mode === 'json' && !jsonText)) && <Spin size="small" />}
          <Button
            size="small"
            onClick={copy}
            disabled={mode === 'json' ? !jsonText : !sourceText}
          >
            复制
          </Button>
        </Space>
      </div>
      <div className="output-viewer-body">
        {mode === 'preview' && (
          <div className="digest-markdown output-preview">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{sourceText}</ReactMarkdown>
          </div>
        )}
        {mode === 'source' && <pre className="output-code">{sourceText}</pre>}
        {mode === 'json' && <pre className="output-code">{jsonText || '(加载中…)'}</pre>}
      </div>
    </div>
  )
}

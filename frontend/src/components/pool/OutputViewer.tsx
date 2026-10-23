import { CodeOutlined, CopyOutlined, ExportOutlined } from '@ant-design/icons'
import { Button, Segmented, Space, Spin, Switch, Tooltip, message } from 'antd'
import { useCallback, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

export type OutputViewMode = 'preview' | 'source' | 'json'

const STORAGE_KEY = 'ra:output-view-mode'

/** 刊名 + 日期(`研讯日报 · 2026-10-22`):日期降级为元信息,不和刊名争同一级权重 */
const TITLE_DATE_RE = /^(.*?)\s*·\s*(\d{4}-\d{2}-\d{2})\s*$/

/** 外链统一新窗口打开并带角标,避免把阅读中的页面顶掉 */
const MARKDOWN_COMPONENTS: Components = {
  a: ({ node: _node, children, ...props }) => (
    <a {...props} target="_blank" rel="noreferrer">
      {children}
      <ExportOutlined className="output-link-icon" />
    </a>
  ),
  h1: ({ node: _node, children, ...props }) => {
    const text = (Array.isArray(children) ? children.join('') : children) as string
    const matched = typeof text === 'string' ? TITLE_DATE_RE.exec(text) : null
    if (!matched) return <h1 {...props}>{children}</h1>
    return (
      <h1 {...props}>
        {matched[1]}
        <span className="digest-title-date">{matched[2]}</span>
      </h1>
    )
  },
}

/**
 * 日报正文固定以 `# 标题` 开头、`## ` 分节,首个二级标题之前(标题 + 导语)即封面区,
 * 单独渲染成主视觉卡;格式不符合时整篇按普通正文渲染,不猜测结构。
 */
function splitHero(markdown: string): { hero: string; body: string } {
  const section = /^## /m.exec(markdown)
  if (!section || !/^# /m.test(markdown.slice(0, section.index))) {
    return { hero: '', body: markdown }
  }
  return { hero: markdown.slice(0, section.index).trimEnd(), body: markdown.slice(section.index) }
}

function readStoredMode(): OutputViewMode {
  const stored = localStorage.getItem(STORAGE_KEY)
  return stored === 'source' || stored === 'json' ? stored : 'preview'
}

/** 模式状态外置:卡片头与正文要共用同一个模式时,由父组件持有 */
export function useOutputMode(): [OutputViewMode, (mode: OutputViewMode) => void] {
  const [mode, setMode] = useState<OutputViewMode>(readStoredMode)
  const change = useCallback((next: OutputViewMode) => {
    setMode(next)
    localStorage.setItem(STORAGE_KEY, next)
  }, [])
  return [mode, change]
}

interface ToolbarProps {
  mode: OutputViewMode
  onModeChange: (mode: OutputViewMode) => void
  contentMd: string
  payload: Record<string, unknown> | null
  loading?: boolean
  /** 复制只留图标:卡片头里与删除按钮同为 32×32 图标按钮,靠 Tooltip 说明语义 */
  copyAsIcon?: boolean
  /** 模式控件:卡片头用「预览⇄源码」Switch + JSON 图标;正文顶部沿用 Segmented 三段切换 */
  modeControl?: 'segmented' | 'switch'
}

/** 预览/源码/JSON 切换 + 复制;独立成组件,既能留在正文顶部,也能放进卡片头 */
export function OutputToolbar({
  mode,
  onModeChange,
  contentMd,
  payload,
  loading,
  copyAsIcon = false,
  modeControl = 'segmented',
}: ToolbarProps) {
  const jsonText = useMemo(() => (payload ? JSON.stringify(payload, null, 2) : ''), [payload])
  const sourceText = contentMd ?? ''

  const copyLabel = mode === 'json' ? '复制 JSON' : '复制 Markdown'
  const copyDisabled = mode === 'json' ? !jsonText : !sourceText

  const copy = () => {
    if (copyDisabled) return
    navigator.clipboard?.writeText(mode === 'json' ? jsonText : sourceText)
    message.success(mode === 'json' ? '已复制 JSON' : '已复制 Markdown')
  }

  const isSwitch = modeControl === 'switch'

  return (
    <div className="output-viewer-toolbar">
      {isSwitch ? (
        /* 二进制开关:关=渲染预览,开=原始内容;原始内容里再用 JSON 图标切 markdown/JSON */
        <Switch
          checked={mode !== 'preview'}
          onChange={(checked) => onModeChange(checked ? 'source' : 'preview')}
          checkedChildren="源码"
          unCheckedChildren="预览"
          aria-label="切换源码视图"
        />
      ) : (
        <Segmented
          size="small"
          value={mode}
          onChange={(value) => onModeChange(value as OutputViewMode)}
          options={[
            { label: '预览', value: 'preview' },
            { label: '源码', value: 'source' },
            { label: 'JSON', value: 'json' },
          ]}
        />
      )}
      <Space size={8}>
        {(loading || (mode === 'json' && !jsonText)) && <Spin size="small" />}
        {isSwitch && (
          <Tooltip title={mode === 'json' ? '看 Markdown 源码' : '看 JSON'}>
            <Button
              className={`icon-btn${mode === 'json' ? ' is-active' : ''}`}
              icon={<CodeOutlined />}
              aria-label="切换 JSON 视图"
              aria-pressed={mode === 'json'}
              onClick={() => onModeChange(mode === 'json' ? 'source' : 'json')}
              disabled={!jsonText}
            />
          </Tooltip>
        )}
        {copyAsIcon ? (
          <Tooltip title={copyLabel}>
            <Button
              className="icon-btn"
              icon={<CopyOutlined />}
              aria-label={copyLabel}
              onClick={copy}
              disabled={copyDisabled}
            />
          </Tooltip>
        ) : (
          <Button size="small" icon={<CopyOutlined />} onClick={copy} disabled={copyDisabled}>
            复制
          </Button>
        )}
      </Space>
    </div>
  )
}

interface Props {
  /** 产出物 markdown 源码(digest/article 的 content_md)。 */
  contentMd: string
  /** JSON 模式的结构化信封;为 null 时显示加载态。 */
  payload: Record<string, unknown> | null
  loading?: boolean
  /** 受控模式:卡片头持有工具栏时由外部传入 */
  mode?: OutputViewMode
  onModeChange?: (mode: OutputViewMode) => void
  /** 工具栏已放进卡片头时关掉正文里这一份 */
  showToolbar?: boolean
}

/** 产出物查看器:预览 / 源码 / JSON 三模式,选择记忆到 localStorage。 */
export default function OutputViewer({
  contentMd,
  payload,
  loading,
  mode: controlledMode,
  onModeChange,
  showToolbar = true,
}: Props) {
  const [ownMode, setOwnMode] = useOutputMode()
  const mode = controlledMode ?? ownMode
  const changeMode = controlledMode ? (onModeChange ?? (() => {})) : setOwnMode
  const jsonText = useMemo(() => (payload ? JSON.stringify(payload, null, 2) : ''), [payload])
  const sourceText = contentMd ?? ''
  const { hero, body } = useMemo(() => splitHero(sourceText), [sourceText])

  return (
    <div className="output-viewer">
      {showToolbar && (
        <OutputToolbar
          mode={mode}
          onModeChange={changeMode}
          contentMd={contentMd}
          payload={payload}
          loading={loading}
        />
      )}
      <div className="output-viewer-body">
        {mode === 'preview' && (
          <>
            {hero ? (
              <div className="digest-hero">
                <div className="digest-markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                    {hero}
                  </ReactMarkdown>
                </div>
              </div>
            ) : null}
            <div className="digest-markdown output-preview">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                {body}
              </ReactMarkdown>
            </div>
          </>
        )}
        {mode === 'source' && <pre className="output-code">{sourceText}</pre>}
        {mode === 'json' && <pre className="output-code">{jsonText || '(加载中…)'}</pre>}
      </div>
    </div>
  )
}

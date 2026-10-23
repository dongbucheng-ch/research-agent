import { RightOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'

interface ExpanderProps<RecordType> {
  expanded: boolean
  expandable: boolean
  record: RecordType
  onExpand: (record: RecordType, event: React.MouseEvent<HTMLElement>) => void
}

/**
 * 表格展开指示符:无边框 chevron,展开时旋转 90°。
 * 方框「＋」在业务行里会被读成「新增」,chevron 才是表格展开的通用约定;
 * 信源池与任务中心共用同一套语言,尺寸/悬停底/焦点环都由此处与 .table-expander 统一定义。
 */
export function renderTableExpander<RecordType>({
  expanded,
  expandable,
  record,
  onExpand,
}: ExpanderProps<RecordType>): ReactNode {
  if (!expandable) return <span className="table-expander is-placeholder" />
  return (
    <button
      type="button"
      className={expanded ? 'table-expander is-open' : 'table-expander'}
      aria-label={expanded ? '收起' : '展开'}
      aria-expanded={expanded}
      onClick={(event) => {
        event.stopPropagation()
        onExpand(record, event)
      }}
    >
      <RightOutlined className="table-expander-caret" />
    </button>
  )
}

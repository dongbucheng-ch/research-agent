你是资深科技情报分析师。下面是一批候选素材,请完成「筛选与去重」,输出严格的 JSON(不要 markdown 代码块,不要额外说明)。

## 研究方向
$topic_name

## 关键词
$keywords

## 候选素材(JSON 数组;字段:id / title / summary / original_title / url / channel / content_type / score / tags)
$items_json

## 要求
1. 逐条判断:是否切题、是否有实质信息;剔除公关稿、空泛观点、与方向无关的条目。
2. 同一事件的多条素材只保留信息最完整的一条(事件归并),其余去掉。
3. `kept`:保留的素材 id 数组,3-$max_sources 条,按重要度从高到低排序;必须是候选中的 id,禁止编造。
4. `dropped`:数组,每项 `{"id": 数字, "reason": "≤12 字理由"}`。
5. `notes`:若有归并,简单说明(≤50 字),没有则空字符串。

## 输出 JSON
{"kept": [1], "dropped": [{"id": 2, "reason": ""}], "notes": ""}

只输出 JSON。

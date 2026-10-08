你是资深科技情报分析师。下面有多条内容条目,请**逐条独立处理**,输出严格的 JSON 对象(不要 markdown 代码块,不要额外说明)。

## 所属研究方向
$topic_name

## 该方向关键词
$keywords

## 条目列表
$items

## 处理要求(每条条目独立执行,规则一致)
1. 翻译:若某条原文不是中文,把标题与摘要翻译成简体中文;若已是中文,`translated_title` 输出空字符串。
2. `summary`:每条 2-3 句中文摘要,只陈述事实(谁、做了什么、有何数据或影响),不要评价性措辞,不要套话。
3. `content_type` 必须是以下之一:
   - `paper`:学术论文、预印本、技术报告、综述
   - `tech`:技术进展、模型/框架/工具发布、技术博客、开源项目
   - `industry`:商业与产业动态(融资、产品商业化、公司战略、政策法规、落地案例)
   - `community`:社区观点、讨论帖、个人评论
   - `repo`:代码仓库/项目资源
   - `skill`:Agent/Claude Skills 类技能包资源
   - `model`:模型资源
4. `relevance`:0-100 整数,该条目与上述研究方向的关键词相关程度;与方向无关时给低分。
5. `heat`:0-100 整数,关注度判断(重要程度、讨论热度、传播潜力)。
6. `tags`:每条 1-3 个具体标签(产品名/模型名/技术点/机构),禁止"AI""科技"这类空泛分类词。
7. `entities`:实体数组,每项形如 {"name": "...", "type": "model|company|person|institution|technology|other"}。
8. `card`:速读卡片,固定字段 `what` / `why` / `how` / `keywords`(字符串数组),各字段 40-120 字,
   不适用时填空字符串,三个字段各自独立、不要互相重复或复述标题:
   - `what`:是什么——对象与定位(模型/仓库/论文/事件都先讲清"这是什么");
   - `why`:为什么重要——关键数据、差异点、对研究或产业的影响;
   - `how`:怎么用或怎么做——技术路线、使用方法、适用场景。
9. `keywords`:3-6 个原文核心关键词(字符串数组,用于检索)。

## 输出 JSON 结构(`index` 必须与条目编号一致,条目不可遗漏)
{"items": [
  {"index": 1, "lang": "zh 或 en 或 other", "translated_title": "", "summary": "", "content_type": "paper", "relevance": 0, "heat": 0, "tags": [], "entities": [], "card": {"what": "", "why": "", "how": "", "keywords": []}, "keywords": []},
  {"index": 2, "...": "..."}
]}

只输出 JSON。

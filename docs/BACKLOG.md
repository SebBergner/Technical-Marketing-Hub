# Technical Marketing Hub — 待办清单

更新于 2026-10-29（staging v2026.3.163，production 仍是 v2026.3.123；第 1–3 周、"去掉审核"、Seb 的 High 和 GXC 都已上 staging，等切换）。来源：9/2–10/7 的会议笔记、管理层 10/02 的六项要求、
Serge / Seb / Elio 的意见、2026-10-16 的全面代码扫描、FY27 Summit 的 Hub 讨论（10/20 那周）、
Serge 10/23 的会议，以及常见内部内容门户的做法。

每一项写明：**来源**、**现状**、**做法**、**要先定的事**、**工作量**、**依赖**。
工作量是粗估，按"开发 + 测试 + 上 staging"计。

SharePoint 里的数据清理（kit 日期、Demo Type、标错的 LDK/VDK、旧版 VM）由团队负责，
不在本清单内，见文末。

---

## 发布前（2026-10-28 与 Elio、Seb 开会定，取代下面的周计划）

High 的 8 项做完、测试、上线 production 后发布，目标是下周一（11/2）之前。上线后通知 Elio、Seb、Serge，Serge 发公告。
Low 的项目都放到发布之后。

| High（发布前） | 现状 | 要做的 |
|---|---|---|
| Usage dashboard：选择创建者 | Hub activity 有 "Whose demos were used most"，但点了没反应 | 点一个创建者，显示他的 demo 里最常用的内容 |
| Report an issue 改名为 Share feedback | demo 页右上角的 "Report an issue" 链接 | 改名，移到 demo 的操作按钮旁边；保持链接样式，不做成按钮。Admin 里要能看到提交的问题；第一版不发邮件 |
| 去掉侧边栏的 Share feedback | 侧边栏底部的 PTC 反馈表链接 | 去掉 |
| 测试归档 | A8 已完成，没在 staging 上真正归档过 | 推送后和 Liwei 一起：归档一个 demo，检查 SharePoint 里的 `_Archive`，再恢复 |
| PTC Only 与 Customer facing | "Internal" 标签和开关；Customer facing 来自 SharePoint 列 | "Internal" 改名为 "PTC Only"；PTC Only 的 demo 一律不是 customer facing（B8 的一部分） |
| 隐藏申请表 | 侧边栏的 Request New Asset（A12 暂停） | 隐藏入口和页面 |
| 隐藏 Value Roadmap 标签页 | demo 页的 Files / Value Roadmap 标签页 | 隐藏 |
| Consensus 用户名单 | 有 Consensus demo 的页面都显示 "Create DemoBoard" | 只给 Elio 名单上有 Consensus 许可证的人显示；名单是临时做法，名单变了 Elio 再发 |

**已定（Liwei 10/28）**：
- 选择创建者：点一个创建者后，"Most used content" 只显示他的 demo，上方有一个可清除的标签，切换期间时保持选择。
- Consensus 名单：在 Admin 上传 Elio 的 CSV（Consensus 的 ManageUsersReport：First Name、Last Name、Email、Role、Group…），
  每次上传替换整个名单。名单上的所有人都能看到 Create DemoBoard，不按 Role 筛（10 月版 263 人，19 个 partner）。
- PTC Only：标成 PTC Only 时把 SharePoint 的 CustomerFacing 写成 No，编辑器里这一项锁定；取消 PTC Only 时不自动改回。
- A13 相关推荐照常随这次推送上线。

**进度（10/29，staging v2026.3.163）**：High 里除"测试归档"外的 7 项都已上 staging，10/29 在 staging 上逐项看过。
- Usage：可以点创建者。
- Share feedback：已移到操作栏，侧边栏的链接已去掉；Admin 里看问题用现有的 Admin → Report owners（点计数列出该 segment 的报告）。
- PTC Only：已改名，写 CustomerFacing No 并锁定。
- 申请表、Value Roadmap 标签页：已隐藏。
- Consensus 名单：在 Admin → Users & groups → Consensus licences 上传。

- Create DemoBoard 只看名单，不看权限：没有许可证的 Administrator 也看不到（Consensus 本来就要求本人有账号）。

推送后要做：
- ~~上传 Elio 的 CSV~~：staging 已上传（263 人，19 个 partner）；**production 切换后要再传一次**（数据按 slot 分开）。
- 和 Liwei 一起测试归档和恢复：**还没做**，staging 上一个已归档的 demo 都没有。三个库的 `_Archive` 都已建好（GXC Video 的 10/29 补建）。

**10/29 新增（都在 v2026.3.163）**：
- Share feedback 分组：先 "Share something"（这个 demo 有用、想法），再 "Something isn't right"；Related demos 和页面正文分开显示。
- 编辑元数据只检查改动过的字段；没有 Owner 的 demo，问题发给它所在 segment 的负责人。
- Admin → Overview 加了 Brightcove migration 的入口（有 Run Brightcove migration 权限才显示）。
- **GXC 视频**：单独的 SharePoint 库 "GXC Video"；新权限 View GXC videos（Administrators 自动有，Team Member 组一次性加上，partner 永远没有）。
  没有权限的人在 Hub 里完全看不到，打开链接也是 404；有权限的人看到的是 PTC Only、不是 customer facing。下载由 Admin → Content access 的开关控制，默认关。
  迁移时 GXC Gallery 的行进 GXC Video，Segment、Video Type、Products 先空着，以后用 Edit metadata 补。还没真正同步或迁移过（库是空的）。
- 团队组的名字按 production 改成 **Team Member**（之前代码里写的是 TDD Team，切换后三项新权限会落空）。

**切换前后**（详见 docs/SWAP-CHECKLIST.md）：测试归档；切换后在 production 上传 Consensus 名单、填 Report owners（staging 也还空着）、建 GXC 组、选 Featured、跑一次完整同步。

Low（发布后）：Not indexed 状态（B8）、S1 邮件订阅、S5 Value Roadmap 索引（通过 API 推送）、A3 个人播放列表和收藏、
多个关键词用 OR 搜索、A13 相关推荐（已在本地完成）、C1 Consensus 视频迁移、C3 Consensus 视频分享（公开链接）、
在 SharePoint 里创建 demo 页、搜索文档内容和字幕。

会议里的其他事项（不在 Seb 的 High 里）：去掉 segment 的 SCO 选项（10/28 已做，v2026.3.158：新建和编辑不再提供，筛选里不显示，Report owners 没有 SCO 卡片；那一个 SCO demo 保留原值，问题归 General）；按 segment 指定负责人来分派问题（10/29 已做：没有 Owner 的 demo 发给 segment 负责人）；
数据清理，补上发布日期和元数据；11/2 周一和 Myles 开会，催 Consensus 迁移的信息。

---

## 开发计划（2026-10-27 起；10/28 起由上面的发布前清单取代）

2026-10-26 定：按周分批，每批推到 staging 由 Liwei 验证，每周集中 swap 一次（避开周五）。每项开始前先用几句话确认做法。

| 周 | 内容 |
|---|---|
| 第 1 周（10/27） | S3 卡片日期、S4 表格视图 + CSV 导出、S2 Dashboard；顺带 A14 同步时间、D12 Zscaler 提示、筛选写进链接（S6 的前提） |
| 第 2 周（11/3） | A1 在 Details 卡片上编辑元数据（含 A4 Demo Owner、B5 第一步自动视频画面）、S1 邮件订阅、A11 product version 必填 |
| 第 3 周（11/10） | A8 归档移入 _Archive、A6 复查过期 demo、A2 Report asset（含 Report owners） |
| 第 4 周（原定 11/17，10/28 起提前开始） | A13 相关推荐 → A12 申请表改进 → A3 我的 Hub（收藏、最近看过、播放列表）→ A9 View as（10/28 定的顺序：A9 最后做，用来检查 partner 看到的 My Hub） |
| 随时插入 | S5 Value Roadmap 读取（等 Seb 的样例） |

暂不排期：A5（优化）、A10 和 B6（模板和介绍编辑，未来）、S6 导航（不急）、C 类（等别人）。开放给 Marketing 之前，D1 备份和 D2 关掉共享密码登录由 Liwei 在 Portal 里完成。

---

## Serge 会议（2026-10-23）：已定要做的

Serge、Elio、Seb、Liwei。下周开始开发前的最后一次会议，原 TMH Checkpoint 的 5 个话题都有了结论。
**推广顺序**：先把 Hub 在本团队里做稳，再开放给整个 Marketing，最后全 PTC；先收集反馈、确认关键功能可靠，
不急着发全员通知。Elio 已给 Brian Thompson、John Hennessy 演示过，反馈很好（他们要的功能大多已经有了）。

| 话题 | 结论 | 负责 | 工作量 |
|---|---|---|---|
| S1. 订阅新内容 | 先做最简单的个人邮件订阅：有新内容就发邮件；以后再按类别 | Liwei | Hub 1–1.5 天 + 流程半天 |
| S2. 公开 Dashboard | 使用数据 + 内容统计（各类型数量、最常用、历史趋势），标准图表，能截图汇报 | Liwei | 2–3 天 |
| S3. 卡片显示原始发布日期 | 标题下方显示；用原始发布日期，不用复制或导入日期 | Liwei | 半天 + 补数据 |
| S4. 卡片 / 表格切换 | 真正的表格，列可排序；导出看需要 | Liwei | 1–1.5 天（导出再半天） |
| S5. Value Roadmap 索引 | 新上传自动索引，重新索引要受控，存量分批；Hub 暂不直接接 AI | Seb + Liwei | 读取与显示 1–2 天（有样例后） |
| S6. Value Roadmap 导航 | Hub 里浏览 Process → Capability → 视频；以后 Pathfinder 带着预筛列表打开 Hub；不急 | Seb + Liwei | 数据到后 3–4 天 |

### S1. 订阅新内容（已定：个人邮件订阅）
- **结论**：先做"有新内容就给我发邮件"的个人订阅，一个开关即可；以后再扩展到按产品或类型订阅。取代原 A7。
- **做法**：Hub 里加一个 "Email me about new content" 开关（个人菜单或通知设置页，B1 设想的设置页可复用）。
  每次同步后 Hub 算出新出现的 demo，写进一个 SharePoint 列表（如 "Hub New Content"）；Power Automate
  监听这个列表，按订阅名单发邮件。和 Hub Tasks 同一套机制，Hub 不自建发信。
- **要定**：
  1. 频率：每有一个新 demo 发一封，还是当天新增合并成一封（建议每天最多一封）。
  2. 发信账号：Power Automate 用谁的账号或共享邮箱发。
  3. 订阅名单存哪里：SharePoint 列表（流程直接能读，建议）或 Hub 自己的数据。
  4. partner 能否订阅：邮件里只能列他们有权限看的内容；建议第一期只开放给 PTC 员工。
- **工作量**：Hub 侧 1–1.5 天；Power Automate 流程约半天（你来配置）。
- **10/26 备注**：押后处理，还需要讨论（Liwei）。

### S2. 公开 Dashboard（已定：使用 + 内容统计，对 PTC 员工公开）
- **结论**：Hub activity 只是使用数据；Serge 要的 Dashboard 还要有内容统计：内容有多全、各类型数量、
  最常用、历史趋势、类型之间的对比。内容统计放到 Dashboard 下；首页保留可点击的类型入口（Videos、VMs 等）。
  Serge 要**标准图表**，可以直接截图做汇报，不必每次找人导数据；Elio 问能否导出，Seb 说数据本来就是表格。
  创建者排行保留（Serge：良性竞争，推动使用）。取代 B4。
- **做法**：侧边栏 "Dashboard"（和 Hub activity 合并），三块：
  1. Library：各类型、产品、segment、语言的数量；年龄分布；每月新增。
  2. Usage：现有 Hub activity 的全部内容（浏览、下载、搜索、活跃用户、最常用、创建者排行），加上按类型对比。
  3. Trends：按月的使用和新增趋势。
  每个图表可导出 CSV；版面适合截图。数据来自现有 Admin 的 Content dashboard 和 Hub activity。
- **要定**：数据完整度（"未填写"的比例）是否公开（建议留在 Admin）；partner 不可见；趋势从哪天算起
  （使用记录开始的那天）。
- **工作量**：2–3 天。

### S3. 卡片显示原始发布日期（已定）
- **结论**：每张卡片在**标题下方**显示发布日期（不放在图片上），让人分清"真的是新发布的"和"只是标了 New"。
  Elio 提醒：迁移到新地方时系统日期会变成导入日，所以必须用**原始发布日期**；迁移的内容从来源系统
  （如 Consensus）取日期，不用 SharePoint 的复制日期。
- **做法**：卡片标题下一行 "Published Mar 2024"，表格视图同一列（可排序）。日期顺序：Original publish date →
  来源系统的发布日期（Consensus、Brightcove）→ 都没有时不显示具体日期。C1 迁移时把 Consensus 的日期写进
  Original publish date。Create New Demo 已经强制填 Original publish date。
- **数据**：许多 kit 的日期仍是批量上传日（如 104 个都是 2018-12-13），由团队在 SharePoint 补，
  或在 A1 的原地编辑里改。
- **要定**：只有批量上传日的 demo 显示什么（建议不显示具体日期，或只显示年份）。
- **工作量**：显示半天；补数据由团队。

### S4. 卡片 / 表格切换（已定）
- **结论**：要真正的表格（行、列、元数据），点列名排序，比如按发布日期排；不是一张张卡片。Liwei 确认是小改动。
  导出 CSV 看需要。
- **做法**：结果区右上角加视图切换。列：标题、类型、产品、segment、语言、发布日期 / 年龄、浏览量；
  点列名排序，点一行打开 demo；筛选和搜索对两种视图都生效；每人的选择记在自己的浏览器里。
- **工作量**：1–1.5 天；导出 CSV 半天（和 S2 的导出共用）。

### S5. Value Roadmap 索引（已定方向，Seb + Liwei）
- **结论**：
  1. **新上传自动索引**：Seb 现有的 AMP 流程已经按 Value Roadmap（2027 版）索引上传的视频；内容进 Hub 时
     把索引结果一起带进来。
  2. **重新索引要受控**：不让所有人随便点（耗 AI 额度、多人同时点会拖慢页面），限权限或排队。
  3. **Hub 暂不直接接 AI**：Hub 现在没有 AI，要接 Claude 得先解决费用（现在用 Seb 的个人信用卡；
     Seb 去解决公司付费）。存量几百个视频的费用比偶尔用高得多。
  4. **过渡方案**：Seb 在现有 Claude 会话里批量处理，产出索引文件，上传到 Hub；Value Roadmap 本身转成 JSON，
     不用每次重读 PDF。Liwei 研究这个方案。存量分批处理。
  5. AMP 用字幕 + 抽帧截图分析，产出描述、solution coverage、roadmap 主题、场景、value drivers、
     business initiatives；AI 选的 roadmap 条目可以人工改。画面分析不如字幕可靠。
  6. 内容先由内部产品专家（Neal、Elio、Scott 等）审核，再给外部 PM；这个流程由 Serge 和 Elio 建立。
- **Hub 要做的**：
  1. 和 Seb 定索引文件格式和放法（每个 demo 文件夹一个 JSON，9/8 定的方案；或一个批量文件在 Admin 上传），
     先要 1–2 个样例。
  2. 同步时读取；demo 页的 Value Roadmap 卡片显示内容；搜索和筛选加上 Process、Capability。
  3. Admin 里"导入索引文件"和"请求重新索引"（只有新权限的人能点，进队列，由 Seb 的流程处理）。
  4. 人工修改 AI 选的条目：放进 A1 的原地编辑。
- **要定**：文件格式；Value Roadmap 的层级（Process → Capability → Feature，Summit 也说粒度未定）；
  重新索引的权限和上限；AI 费用（Seb）。
- **工作量**：读取与显示 1–2 天（有样例后）；导入和重新索引请求 1 天；Hub 直接接 Claude 另算。
- 取代 C4。

### S6. Value Roadmap 导航（新，不急）
- **结论**：Serge 想在 Hub 里有一个 HTML 的 Value Roadmap 菜单：浏览流程和能力，选中后看到相关视频。
  场景：BDM 和客户讨论时，从"详细设计"这样的话题点到业务驱动、能力和支撑视频。Serge 已有开发中的原型
  （流程全景、portfolio 视图、能力选择）。Seb：以后 Pathfinder 可以带着预筛的列表打开 Hub（他在和 Martin 谈，
  Serge 作为直接相关方参与）。
- **做法**：侧边栏 "Value Roadmap"：左边是流程和能力的树（来自 roadmap JSON），右边是映射到选中节点的 demo
  （复用卡片和表格视图）。
- **Pathfinder 的前提：筛选条件写进链接**。现在 Hub 的筛选不在 URL 里（只有搜索词在），所以别的系统没法
  打开一份筛好的列表。这一步可以先做，顺便让任何筛选结果都能复制链接分享。约半天到 1 天。
- **依赖**：S5 的数据；Serge 的原型（参考结构）。
- **工作量**：数据到后 3–4 天；筛选进链接半天到 1 天。

---

## A. 可以直接开始（不依赖外部）

### A1. 在 Hub 里编辑元数据（"打标签"）
- **来源**：管理层 10/02 第 3 项 "Tag assets as needed"；workshop 上"请大家修日期、修元数据"。
- **现状**：后台有权限 `edit_metadata` 和写回接口（`backend/integrations/graph/writeback.py`、
  `/api/curation`），但**没有任何界面**。写回目前只填**空**列；列里已有不同的值时会停下、不写。
- **做法**：直接在 demo 页的 Details 卡片上原地编辑（Liwei 10/21：不需要 Admin 页面）。有 Edit metadata
  权限的人在 Details 表格右上角看到 "Edit"，点开后字段变成下拉框和输入框，没有权限的人看不到这个按钮。
  缩略图也在这里一起改（Liwei 10/21）：Automatic / Pick a frame / Upload an image，与 B5 共用同一套存储和
  组件，另加约半天。可改 Product、Segment、Language、
  Original publish date、Customer facing（Demo Video 另有 Video Type）。保存时先重读 SharePoint，
  用 ETag 防并发覆盖；每次修改记进 Admin log，可在 SharePoint 版本历史里追溯。
  Consensus 的条目只读（Consensus 不由 Hub 写）。
- **要先定的事**：
  1. **允许覆盖已有值**——已定（Liwei 10/20）：Hub 已能在 SharePoint 创建 demo，"不修改 SharePoint"
     的原则不再适用；只要确保只有有 `edit_metadata` 权限的人能改，每次改动留痕。
  2. 改动要不要审核后才写回，还是直接写？
  3. 谁有权限：目前 Administrators 和 TDD Team 都勾了 `edit_metadata`。
- **工作量**：2–3 天。
- **10/26 已定并已做（本地，待推送）**：能改的字段是该库上传表单的全部字段（标题除外）加 Demo Owner，另可改 PreviewVideo
  和卡片图片（上传图片或从视频选一帧）；不审核，直接写回，记进 Admin log；只有 Administrators 和 TDD Team（Edit metadata）。
  - **标题不可改**：标题就是文件夹名，Hub 的 ID 和所有分享链接由它生成；Title 列与文件夹名在 15 个 kit 上不一致（有的明显错误），
    所以也不能改用 Title 列。Liwei：暂不允许改标题。
  - **Funnel stage 不能改**：SharePoint 两个库都没有这一列（只有 Consensus 的 demo 有）。要改需先在库里建列。
- **依赖**：无。

### A2. Report asset：报告内容问题（用 Hub Tasks 接收）
- **进度（10/28 本地完成，待推送 staging）**：demo 页 "Report an issue"、侧边栏 "Get help"（含 My reports，状态从 Hub Tasks 读回）、Admin → Report owners（CAD/PLM/ALM/SLM/General，Notify 开关、计数、无人通知标红）。写 Hub Tasks：TaskType Support request、Category、Segment、NotifyTo（"; " 分隔）。Partner 可提交，只记 "partner"。第一版没有附件。剩下：在 Report owners 填人；Power Automate 流程（你来配）。
- **来源**：Seb，10/07 会议 —— 和 "Share feedback"（对应用的反馈）、"Request New Asset"
  （申请新 demo）分开，专门处理已有内容的问题和求助。**Summit 确认**：用 "Report asset" 代替开放评论和点赞
  （见 B1）；报告存进 SharePoint 中央列表，**按产品或 segment 分派给负责团队，不发给上传者本人**；
  用邮件或任务通知；partner 能访问后也要考虑。
- **现状**：没有。Hub Tasks 列表的 TaskType 已预留 "Support request"。
- **做法**：两个入口 —— demo 页上的 "Report an issue"（自动带上 demo 链接）和侧边栏的 "Get help"。
  表单字段：类别（文件打不开/缺失、内容过时或有错、演示环境/VM、找不到内容、其他）、说明、
  可选附件。提交后写进 Hub Tasks（Open），处理人在 SharePoint 里改状态；Hub 里提交人能看到状态。
- **Admin → Report owners**（Liwei 10/23）：Admin 新增一个标签 "Report owners"，放在 "Content review" 旁边
  （同属内容治理）。
  - 每个 segment 一栏（CAD、PLM、ALM、SLM，外加 "General"，接收没有 segment 的报告和 Get help），
    可添加多位 owner：姓名、邮箱、Notify 开关（On / Off）。
  - 每个 segment 显示收到的 Report 数：未处理 / 总数 / 最近 30 天；点数字打开该 segment 的报告列表。
  - 分派：提交 Report 时，Hub 按 demo 的 segment 找出开着 Notify 的 owner，把这些邮箱写进 Hub Tasks 的
    "NotifyTo" 列；Power Automate 只按这一列发邮件，不用自己查名单。demo 有多个 segment 时通知各 segment 的
    owner（去重）；某个 segment 没有开着 Notify 的 owner 时转给 General，并在 Admin 里标红提醒。
  - 名单存在 Hub 自己的数据里，改动记进 Admin log；只有有 Manage users & groups 权限的人能改。
  - 约 1 天。
- **要先定的事**：
  1. 类别列表，以及**每个产品或 segment 发给谁**（Elio 提过：CAD → Avi 和 Elio）。分派在 Hub Tasks 上用
     Power Automate 做，需要再加 "Category" 和 "Product" 列（你来建）。
  2. Partner 能不能提交？能的话，按匿名原则不记名字，只记"partner"。
- **工作量**：2–3 天（含 Report owners 约 1 天）。
- **依赖**：在 Report owners 里填好各 segment 的 owner；Hub Tasks 加 "Segment" 和 "NotifyTo" 两列（你来建）。

### A3. 我的 Hub：收藏、最近看过、个人播放列表（PTC 员工和 partner 都有）
- **来源**：常见门户的基本功能；侧边栏原设计里就有 Favorites，目前被移除（"需要按人存储"）。
  **Summit**：每人一个固定的起点——收藏 + 最近看过；partner 能访问后也要有。
- **现状**：没有。
- **做法**：卡片和 demo 页加星标；侧边栏 "My Hub" 显示自己的收藏和最近看过的 demo（最近看过取自已有的
  使用记录）。按登录身份存在 `owned/favorites.json`，只有本人能看到。
- **个人播放列表**（Liwei 10/23）：在卡片或 demo 页点 "Add to playlist"，放进自己建的列表（可改名、排序、删除）；
  My Hub 里列出自己的全部播放列表。
  - "Copy link" 复制一个 Hub 链接分享给同事或其他 partner；打开时仍要登录，每个人只看得到自己有权限的 demo
    （没权限的隐藏，并提示"有 N 个你无法查看"）。收到的人可以 "Save a copy" 变成自己的列表。
  - 只是 Hub 内部的列表，不是对客户的分享；给客户的 Consensus DemoBoard 见 C2。
  - **partner 的匿名**：按 Entra 对象 ID 存，不进任何报表；partner 建的列表分享出去时不显示创建者姓名。
- **已定**（Liwei 10/23）：partner 也有我的 Hub：收藏、最近看过、播放列表和分享。
- **要先定的事**：Partner 也要有吗？有的话按 Entra 对象 ID 存，不在任何报表里出现。
- **已定**（Liwei 10/28）：星标放在卡片和 demo 页两处（表格视图加一列）；"最近看过" 保留 20 条。
- **工作量**：2.5–3 天（收藏和最近看过 1–1.5 天；播放列表和分享约 1.5 天）。
- **依赖**：无。

### A4. Demo 负责人 / 联系人
- **来源**："这个 demo 该问谁"；排行榜把代传的 demo 算到上传人名下（如 Lamborghini）。
- **现状**：负责人取自 SharePoint 文件的创建者。
- **做法**：你在 Demo Catalog 和 Demo Video 各加一列 "Demo Owner"。**建议用单行文本列，存邮箱**
  （和 submitted_by 一样），不要用 Person 列：Graph 写不了 Person 列（已在 Demo Requests 列表验证），而下面的
  自动填写和修改都要 Hub 来写。Hub 优先读它，没填再用文件创建者。demo 页显示 "Contact: 姓名"（可点发邮件），
  "Whose demos were used most" 也按它统计。
- **已定**（Liwei 10/23）：你在 SharePoint 加列。
  - 上传时自动填上传的人：网页上传填 SSO 登录邮箱；API 上传填 submitted_by，没填就填 token 的所有人。
  - 可以在 A1 的原地编辑里改 Owner（有 Edit metadata 权限的人，改动记进 Admin log）。
  - 批量导入的 demo 全部留空，Hub 不自动补写；显示时仍退回文件创建者。
- **工作量**：1.5 天（读取和显示、上传时写入、A1 里可改；加列由你在 SharePoint 里做）。
- **依赖**：列建好。

### A5. 搜索质量
- **优先级**（Liwei 10/23）：属于优化，不急；不放进近期的开发计划。
- **来源**：Admin → Hub usage 里的"零结果搜索"。
- **现状**：标题优先，描述命中排后；没有同义词和拼写纠错。
- **做法**：按零结果搜索的真实记录建同义词表（如 WC → Windchill、CB → Codebeamer、IPL、SLM），
  加简单的拼写容错；搜不到时提示"你是不是要找…"。
- **要先定的事**：无（同义词表可以先给你过目）。
- **工作量**：1 天。

### A6. 协助团员归档过期 demo（Liwei 10/21，含原"团队用的内容复查清单"）
- **进度（10/28 本地完成，待推送 staging）**：侧边栏 "Content to review"（Review content 或 Archive content 可见），全部 demo 按最近使用从旧到新、显示年龄和最近使用日期，Mine / All、按类型和年龄筛选；勾选后批量 Archive（一个理由、一次确认）或 Still current，逐个执行、被拒的说明原因，可 Undo。不做清理行动（Liwei 10/28）。
- **来源**：Liwei 2026-10-21：团员需要在 Hub 里把过期的 demo 归档。归档标准来自 10/07 会议
  （Elio：约 1 年；Seb：还要看使用量）和 Serge 的年龄方案。
- **现状**：归档功能已有，只在 Hub 里隐藏、SharePoint 不动、可以 Restore。TDD Team 有 Review content，
  能在 demo 页的 Manage 标签里逐个归档。但"哪些该归档"的清单（超过 7 年、一年以上且半年没人用、
  Still current 快过期）只在 Admin → Content review 里，团员没有 View Admin，看不到；也没有批量操作。
- **做法**：
  1. Hub 里加一个 "Content to review" 视图，只对有 Review content 的人显示。默认先显示**自己创建的**
     demo（按创建者匹配，归档请求首先落在作者身上），可切换到全部、按产品 / 年龄筛选。
  2. 每行显示年龄和最近一次被使用的日期，可按这两列排序（没有自动的归档标准，由团员判断）。不带任何按人的使用数据。
  3. **批量操作**：勾选多个后 "Archive"（填一个理由）或 "Still current"；都可以撤销，都写进 Admin log。
  4. 可选：一次性"清理行动"，给每位创建者在 Hub Tasks 里写一行"你有 N 个 demo 待复查"，
     配合 workshop 上 "own your content" 的请求。
- **要先定**：归档标准（年龄和未使用时长的阈值）；团员能否归档**别人**的 demo，还是只能处理自己的
  （其余由 Serge 或管理员处理）；要不要做清理行动。
- **已定**（Liwei 10/23）：
  - 没有年龄和未使用时长的门槛：清单不按标准筛选，按年龄和最近使用排序，由团员自己判断。
  - 团员可以归档别人的 demo，不限于自己创建的。
  - 归档的实际动作就是 A8：把 demo 文件夹移进 `_Archive`，只保留团队内的人的访问权限；Hub 保留记录，可以恢复。
  - 还剩一个：要不要做清理行动。
- **注意**：创建者来自 SharePoint 文件创建者，代传的 demo 会算到代传人名下；做了 A4（Demo Owner）后会更准。
- **Summit**：复查流程（谁复查、怎么发出复查请求、怎么通知）由团队定；Hub 提供清单、批量操作和通知。
- **工作量**：清单视图 1 天；批量操作半天；清理行动半天。合计约 2 天；依赖 A8（归档的实际动作）。

### A7. 订阅新 demo 通知 —— 已并入 S1（Serge 10/23 定为个人邮件订阅）

### A8. 归档改为移入 SharePoint 的 _Archive 文件夹（Liwei 10/21 定，Summit 确认，开始做时再建文件夹）
- **进度（10/28 本地完成，待推送 staging）**：新权限 Archive content（Administrators、TDD Team）；SharePoint demo 的文件夹移入 `_Archive`，移动前后各比对一次权限，不一致就移回并拒绝；Restore 移回库根目录、同名时拒绝；同步把 `_Archive` 里的 demo 当作原 demo 读。Admin → Content review 标出以前只在 Hub 里归档的 demo（推送后列进 Data Clean 清单，手动处理）。推送后用一个最老、从没人用过的 demo 做第一次真实归档。
- **来源**：Liwei 2026-10-21。现在的 Archive 只在 Hub 里隐藏，partner 和其他内部人员在 SharePoint 里
  仍能打开。改为把 demo 文件夹移进一个只有团队（TDD Team）能看的文件夹，partner 和团队外的内部人员
  都看不到（Liwei 10/23）。
- **为什么不用 SharePoint 自带的归档**：Microsoft 365 Archive 只能归档整个站点（付费、恢复有延迟）；
  Purview 保留标签只锁定不隐藏；没有单个文件夹的归档功能。权限受限的归档文件夹是常见做法。
- **设置（你来做）**：Demo Catalog 和 Demo Video **各在库内**建一个 `_Archive` 文件夹，只给团队
  （TDD Team 组，含 Admin）权限。放在同一个库里，是因为库内移动文件 ID 不变，Hub 一直认得出是哪个 demo；跨库是复制再删除，ID 会变。
  开始做这一项时再建。
- **新权限 Archive content**：只有有这个权限的人能归档和恢复（和 Review content 分开），给 TDD Team：
  团员可以归档别人的 demo（Liwei 10/23）；partner 永远拿不到。
  每次归档要二次确认、写理由、记进 Admin log。
- **独立权限的 demo：拒绝归档**。Graph 做不到"恢复继承"（只有 SharePoint REST 有，而 Hub 的应用用客户端
  密钥认证，调不了）；只删单条权限会留下一个断开继承的孤岛，而且需要 Full Control。所以归档前，Hub 检查
  demo 文件夹**及其中所有文件和子文件夹**的权限（移动时它们也会保留各自的权限）；发现任何独立权限就拒绝，
  列出是哪些，提示在 SharePoint 里"删除唯一权限"后再归档。如何判断"继承 / 独立"要先在测试库只读验证。
- **还要处理的**：
  1. 同步：`_Archive` 本身不是 demo，它里面的子文件夹是"已归档的 demo"，有 Archive content 权限的人在 Hub 里能看到已归档列表
     （谁、何时、理由）并 Restore（移回原位）；团员没有 View Admin，所以不只放在 Admin 里。
  2. 故事页：页面指向的文件夹已归档时，页面也一并隐藏，不让它作为"只有页面的 demo"复活。
  3. 链接：文件夹的 SharePoint 地址会变，收藏的链接和故事页里的链接失效；Hub 自己的链接不受影响。
  4. 先确认 Hub 的应用身份能访问受限的 `_Archive`（理论上应用权限是站点级的）；写入测试先在测试库做。
  5. Consensus 的 demo 不在 SharePoint，继续只在 Hub 里隐藏。
- **和 A6 的关系**：A6 的批量归档就是批量移入 `_Archive`，同样要逐个做权限检查。
- **工作量**：约 2–3 天（移动与恢复、新权限、权限检查、同步识别 `_Archive`、故事页、测试库验证）。
- **10/26 备注**：两个库都已建好 `_Archive` 文件夹，并移除了 visitor 组的权限。

### A9. View as：以某个组的身份预览 Hub（Liwei 10/21）
- **来源**：Liwei 2026-10-21：只有自己的账号，没法测试 partner 和其他权限的人在 Hub 里看到什么。
- **做法**：Admin → Users & groups 里，对某个组点 "View the Hub as this group"（Partners、PTC employees、
  TDD Team 等）。打开的 Hub 完全按那个组的权限显示：看得到哪些 demo、哪些文件被锁、哪些按钮没有、能否进 Admin。
  页面顶部一直有横幅 "Viewing as Partners — Exit"。
- **安全要求**：
  1. 只能降不能升：预览的权限 = 那个组的权限与自己权限的交集。
  2. 预览期间一律只读：上传、归档、改元数据、提申请等写操作全部拒绝。
  3. 不计入使用统计：不记成 partner，也不记成本人。
  4. 只有 Manage users & groups 的人能用；开始和结束预览都记进 Admin log。
- **测不到的**：SharePoint 本身的权限（比如 partner 直接点 SharePoint 链接会不会被挡）。
- **配合：向 IT 申请两个测试账号**：一个 PTC 测试用户，一个外部来宾测试用户（模拟 partner），用于偶尔的
  端到端验证。日常用 View as，重要改动用测试账号。
- **工作量**：约 1.5–2 天。
- **10/26 备注**：不向 IT 申请测试账号。
- **已定**（Liwei 10/28）：所有组都可以预览（Users & groups 里每个组都有这个按钮，以后新建的组也有）。

### A10. Create New Demo 模板（Summit，Liwei）
- **来源**：Summit：创建 demo 时可以选模板，文件按 Scripts、Presentation deck、Videos、Documents、
  Supporting files 等分好节，Hub 按这个结构和顺序显示，不用再直接维护 SharePoint。
- **现状**：Create New Demo 已有元数据和文件上传；demo 页已能按作者的分节显示（10/21 的故事页，
  e945cae），但分节只来自 SharePoint 页面。
- **做法**：上传时先选模板（如 "Video Demo Kit"、"Live Demo Kit"、"IPL story"），每个模板定义几节；
  每个文件放进一节（按扩展名预填，可改）；文件按节传进对应子文件夹；分节信息写成 demo 的 overview，
  demo 页直接按节显示。模板由管理员在 Admin 里维护。
- **和 B6 的关系**：B6（在 Hub 里写介绍）是同一件事的另一半：模板定结构，B6 补每节的文字。建议一起设计。
- **要定**：有哪些模板、每个模板有哪些节（团队定）；子文件夹命名是否统一。
- **工作量**：2–3 天（不含 B6 的编辑器）。
- **10/26 备注**：待定，是未来的功能，现阶段不着急做。

### A11. 元数据必填项补齐（Summit，Liwei）
- **来源**：Summit：发布前必须填完元数据——标题、描述、产品、segment、customer facing、narrated audio、
  语言、product version。
- **现状**：除 **product version** 外都已强制（另外还强制 Original publish date 和 Owned by）；
  product version 目前选填。
- **要定**：product version 是否必填，对哪些类型（视频？LDK、VDK？）；不适用时允许填 "N/A" 吗。
- **工作量**：2 小时。
- **10/26 备注（已定）**：product version 对所有类型必填；不适用时允许填 N/A；主界面上 N/A 不显示。

### A12. Request New Asset 改进（Summit）
- **来源**：Summit：叫 "request" 容易让人以为一定会做。
- **做法**：
  1. 改名（如 "New asset inquiry"），表单顶部说明"提交后进入队列，不保证制作"。
  2. **提交前查重**：根据填的标题、描述、产品，先用 Hub 的搜索列出相似的已有 demo，"这些是否已经满足需要？"；
     以后可以用 AMP 做语义匹配。
  3. 提交权限已经由 Create demos 权限控制（不必新做）。
- **团队定**：措辞和免责说明；排优先级的后台流程；定期汇总申请，看出反复出现的需求。
- **已定**（Liwei 10/28）：改名为 "New asset inquiry"；表单顶部写 "Your inquiry goes into the team's queue. We review
  inquiries regularly, but can't promise every asset will be made."；查重只提示：列出最多 5 个相似的 demo
  （"这些是否已经满足需要？"），下面是 "No, submit anyway"，不强制确认。
- **工作量**：改名和说明 1 小时；查重 1 天。

### A13. 相关推荐（Summit）
- **来源**：Summit：demo 页显示"你可能也需要"。
- **做法**：demo 页底部 "Related demos"：同产品、同 segment、同类型的 demo，按相似度和使用量排；
  有了 Value Roadmap 数据后加上"同一能力"。
- **工作量**：1 天。可直接做。
- **已定**（Liwei 10/28）：显示 6 个。
- **进度（10/28 本地完成，待推送 staging）**：demo 页底部 "Related demos"，`/api/assets/{id}/related`。打分：共有产品族 4 分（每多共有一个族再加 1）、
  同 segment 2 分、同类型 1 分；既不同族也不同 segment 的不算相关。同分时同语言优先（否则同一视频的日语、意大利语版会占位置），
  再按浏览量、发布日期。归档、隐藏、旧版 VM 不会出现。
- **手动推荐（Liwei 10/28 加，本地完成，待推送）**：有 Edit metadata 权限的人在 Related demos 右上角点 "Add"，按名字搜索后添加；
  手动挑的排在最前面、不加标签，剩下的位置由自动推荐补满 6 个。双向：A 推荐了 B，B 的页面也显示 A。每页最多手动挑 6 个。
  手动挑的卡片底部有 "Remove"（两边同时去掉）；自动推荐的有 "Not related"（只对这一页，下方列出可 Undo）。
  存在 Hub 自己的数据（owned/related_picks.json），每次改动记进 Admin log（Metadata）。

### A14. 显示数据更新时间（Summit，Liwei）
- **来源**：Summit：Hub 每天从 SharePoint 同步两次，SharePoint 的改动最多约 12 小时后才出现；要说明清楚，
  保留手动刷新。
- **做法**：Hub 页脚或搜索结果旁显示 "Catalogue updated 3 h ago · refreshes twice a day"；
  上传完成页说明"新 demo 立即可见，SharePoint 里的改动会在下次同步后出现"；写进用户文档。
- **工作量**：2 小时。

### A15. Create New Demo：视频的子类型随类型变化（Liwei 10/27 转来，A1 之后做）
- **需求**：Video type 选定后，Video subtype 只列出该类型的子类型：
  - Technical Overview → Customer、Feature、Solution、Product
  - Technical Teaser → Product、Social
  - Technical Walkthrough → Customer、Solution
  - Experience Asset → Attract Loop、Presenter Support、XDP Clip
  - Other → 隐藏 Subtype
  只有子类型是 Customer（Technical Overview / Walkthrough）时才显示 Named customer，并且必填。
- **现状（10/27 只读核对 Demo Video 库）**：VideoType 选项是 Technical Overview、Technical Walkthrough、Technical Teaser、
  Presenter Support、Other（还没有 Experience Asset；Presenter Support 作为类型目前没有视频在用）。VideoSubtype 选项是
  Feature、Solution、Customer、Release、N/A（还没有 Product、Social、Attract Loop、Presenter Support、XDP Clip；
  Release 有 3 个视频在用）。6 个视频的子类型是 Customer 但没填 Named customer。
- **做法**：类型与子类型的对应关系放在一处（upload_targets），服务器也按它校验，网页表单和 A1 的编辑对话框共用；
  API 先只给提醒（同 A11）。Hub 的 Video Type 筛选要加上 Experience Asset。
- **要先定 / 你来做**：
  1. 在 VideoType 加 "Experience Asset"；"Presenter Support" 这个类型要删掉吗（0 个视频）？
  2. 在 VideoSubtype 加 Product、Social、Attract Loop、Presenter Support、XDP Clip（原文 "Sovial" 应为 Social？）。
  3. Release（3 个视频）不在新规则里：保留给已有视频、不再提供，还是改成别的子类型？
  4. 已有的 6 个 "Customer 但没有客户名" 的视频：保持原样，等下次编辑时再补（编辑时会要求填）？
- **工作量**：约 1 天。
- **10/27 已定并已做（本地，待推送）**：你在 SharePoint 加 Experience Asset 类型，删掉 Presenter Support 类型（改作
  Experience Asset 的子类型）；子类型加 Product、Social、Attract Loop、Presenter Support、XDP Clip。Release 保留给那 3 个视频，
  新建时不再提供。缺客户名的 6 个视频保持原样，下次编辑时要求补填。SharePoint 还没有的子类型，表单会注明缺哪些。

---

## B. 要先定方向

### B1. 点赞、评论与作者通知（Liwei 10/20 的设想）—— 建议暂缓
- **Summit 的意见**：倾向用 Report asset（A2）代替开放评论和社交式点赞。建议暂缓 B1；其中"作者 / 负责团队
  收到通知"和"通知设置页"的设计并入 A2 和 S1。以下保留原设想备查。
- **来源**：9/8、9/9 与 Elio 的会议（评论）；Liwei 2026-10-20 扩展为点赞、评论、评论点赞、
  作者邮件通知和退订。
- **要解决的**：作者看不到对自己 demo 的反馈；使用者没有地方问问题、补充用法。补上 Hub activity
  之外的"质量"信号。
- **建议的存储**：
  1. **评论**存 SharePoint 列表 "Hub Comments"：DemoId（索引）、作者邮箱、正文、回复哪条（只允许
     一层回复）、状态。团队能在 SharePoint 里管理和导出，Power Automate 能直接接。作者写成邮箱文本
     （Person 列 Hub 写不了）。
  2. **点赞**（demo 和评论的）存 Hub 自己的数据：只是"谁赞了什么"，条数多、要即时切换和计数，
     放列表里会慢，也没人需要在 SharePoint 里看。
  3. **退订设置**存 SharePoint 列表 "Hub Notification Settings"：发信的 Power Automate 流程要能读到。
- **通知的建议**：
  1. 新评论：即时发邮件给作者（和被回复的人），用 Power Automate 监听 Hub Comments，Hub 不自建发信。
  2. 点赞：不要每次都发，容易变成垃圾邮件；每周一封汇总："你的 demo 本周收到 N 个赞、M 条评论"。
  3. 退订：邮件底部一个链接，打开 Hub 的"通知设置"，可分别关闭评论通知和每周汇总；
     以后的订阅功能（S1）也用这个页面。
- **前提：知道"作者"的邮箱**。Hub 现在只存了文件创建者的显示名（如 "Hughes, Paul"），没有邮箱。
  要么同步时一并读取创建者邮箱（待核实 Graph 是否返回），要么先做 A4 的 Demo Owner 列。
  代传的 demo（如 Lamborghini）会发给代传人，也需要 A4 来纠正。
- **顺带的好处**：点赞数可以做成排序 "Most liked"、在 Hub activity 里展示。
- **要和 Elio 定**：
  1. partner 能否点赞、评论、看到评论。建议：评论只对 PTC 员工开放（内部讨论，且 partner 必须匿名）；
     partner 可以点赞，只计入总数。
  2. 点赞是否公开"谁赞了"，还是只显示数字。
  3. 评论的管理：本人可编辑和删除；管理员可删除任何评论；是否需要审核。
  4. 评论挂在 demo 上即可，还是要细到单个文件。
- **工作量**（粗估）：demo 点赞 1 天；评论区（列表、界面、一层回复、编辑删除）2–3 天；评论点赞半天；
  通知设置和退订 1 天；Power Automate 流程由你配置约半天。合计约 5–6 天，可分两期：
  先点赞 + 评论，再通知和退订。
- **依赖**：A4（Demo Owner），以及你建两个 SharePoint 列表。

### B2. 删除重复视频
- **来源**：管理层 10/02 第 4 项。
- **要先定的事**：
  1. 指的是哪种重复：同一视频同时在 Consensus 和 Demo Video（迁移后会变多）、同一视频既是
     单独视频又在某个 VDK 里、还是不同 demo 用了同一个标题（本地数据 14 个标题共 30 个 demo）？
     需要一个具体例子。
  2. "删除" = Hub 里合并成一张卡片（来源都保留，建议这样），还是删源文件（Hub 不会做）？
  3. 合并时保留哪个：建议 SharePoint 版本优先（能预览和下载），其次发布日期新的。
- **工作量**：定下来后 2–3 天。

### B3. 整个 kit 打包成一个 zip 下载（"Download all"）
- **来源**：9/8 笔记；`docs/download-kit-zip-notes.md`。
- **现状**：可行性已验证：服务器按 Graph 列出文件，边读边打包。
- **要先定的事**：要不要做；大小上限（如超过 2 GB 改为跳转 SharePoint，现有 6 个 kit 超过 2 GB）；
  要不要包含 CAD 文件。风险：所有字节都经过 App Service，下载不能断点续传。
- **工作量**：2 天。

### B4. 主页 dashboard 的范围 —— 已定，见 S2（对 PTC 员工公开的 Dashboard）

### B5. 缩略图：网页上传可选帧或传图，API 默认用 SharePoint 自动画面（待与 Elio 讨论）
- **来源**：Liwei，2026-10-20 / 21。许多 demo 只有生成的封面：没有故事页的 kit、通过 Hub 上传的视频
  （没有 Brightcove 海报）。本地粗算约 400 个 kit 有视频、没有图片。
- **实测（2026-10-21）**：随机抽 24 个真实视频，取 SharePoint 自动生成的缩略图：没有一张黑屏或偏暗，
  都是视频中间的实际画面；个别不理想（一张登录页、一张带字幕）。所以自动画面是可靠的默认值，
  不再需要服务器截第 3 秒。（scratchpad/video_frames.py）
- **分工（Liwei 10/21 定）**：
  1. **API 上传**：默认用 SharePoint 自动画面，调用方什么都不用做。保留一个**可选**字段 `thumbnail`，
     把文件列表里的某张图标为缩略图（Seb 的 AMP 本来就截第 3 秒，愿意就顺手传上来）；不填不影响现有脚本。
  2. **网页上传**（Create New Demo 的 Files 一步，"Thumbnail" 三选一）：Automatic（默认，SharePoint 自动
     截取，注明"上传后自动生成"）；Pick a frame（在浏览器里播放刚选的视频，拖到想要的画面点
     "Use this frame"；播不了的格式提示改用上传图片）；Upload an image（选 JPG/PNG，当场预览 16:9 卡片）。
  3. **已有 demo**：同样用主视频的自动画面，几百个只有生成封面的 demo 立刻有图。
- **存储**：选了帧或传了图时，图片作为普通文件存进 demo 文件夹，用文件级是/否列 `HubThumbnail` 标记
  （和 PreviewVideo 同一种做法，需要你在两个库各加一列）。自动画面什么都不用存。
- **封面优先顺序**：自选图片或帧 → 故事页图片 → Brightcove 海报 → 主视频自动画面 → 生成的封面。
- **工作量**（合计约 3 天）：自动画面约半天；网页上传图片约 1 天；网页选帧约 1–1.5 天；API 可选字段约 2 小时。
  自动画面不依赖任何人，可以先做。
- **要和 Elio 定**：这个分工是否可行。（已有 demo 怎么换图已定：在 A1 的 Details 原地编辑里一起改，
  权限用 Edit metadata。）

### B6. 在 Hub 里编写 demo 介绍，SharePoint 只当数据存储（Seb 的设想，待讨论）
- **来源**：Seb，2026-10-21 会议；由 Jorge 的 IPL 故事页引出。
- **现状**（e945cae，staging v2026.3.140）：Hub 已能读取作者在 SharePoint 页面里写的简介、分节和文件顺序，
  合并进 demo 页面。实测 278 个页面：4 个故事页（Hill、Bobcat、E&HT、SDV）分节显示，56 个文字页显示全文，
  218 个普通页不变。页面仍然只能在 SharePoint 里编辑。
- **设想**：作者直接在 Hub 的 demo 页面里写简介、加小标题、把文件拖进各节；内容由 Hub 写回 SharePoint
  （demo 文件夹里一个 `hub-overview.json`），不再需要单独做 SharePoint 页面。
- **好处**：PM 不用学 SharePoint 页面编辑；所有 demo 格式统一；只在一个地方维护；用 Hub 新建 demo 时
  可以一步写好介绍；权限沿用 A1 的 Edit metadata。
- **要讨论的**：
  1. 已有的 SharePoint 页面：继续读取，两者并存（Hub 写的优先）；还是一次性导入 Hub 后不再维护页面？
  2. SharePoint 页面是否还被别处引用（Seismic、邮件、Teams 链接），能否停止更新？
  3. 编辑器范围：建议只做文字、小标题、列表和文件分节；是否还要图片、嵌入视频、按钮？
  4. 谁能编辑：demo 作者本人 + Edit metadata 持有者？改动是否需要审核？
  5. 存储：文件夹里的 JSON 文件（随文件夹移动和归档，建议这样），还是 SharePoint 列表（便于汇总查询）？
- **工作量**（粗估）：编辑器（文字、小标题、列表、拖放分节）2–3 天；写回与同步 1 天；导入已有页面半天。
  合计约 4 天。
- **依赖**：A1（同一个编辑入口和权限）；和 A10（模板）一起设计。

### B7. 搜索文档内容和视频字幕（Summit，团队评估）
- **来源**：Summit：现在能搜到包里的文件名，但搜不到文档里的文字和视频里说的话。
- **可能的做法**：
  1. 文档：同步时提取 PPTX、DOCX、PDF 的文字，存成搜索索引（只对常用文件做，控制同步时间）。
  2. 视频：用 AMP 的字幕（S5 的索引文件里已有）；或 SharePoint / Stream 自动生成的字幕（要先确认能否读取）。
- **要定**：值不值得做、先覆盖哪些内容；和 S5 的索引文件一起设计最省事。
- **工作量**：调研半天；文档文字 2 天；字幕看来源。

### B8. Internal only、Customer facing 和 Unindexed 的关系（Liwei 10/27 转来，待讨论）
- **来源**：创建视频表单的讨论中提出（截图里的 "Internal only — files open only for people with access to internal content"）。
- **现状**：两个独立的设置。Customer facing（是/否，SharePoint 列）表示能否直接给客户看；Internal only（Hub 的 Open/Internal）
  表示文件只有能看内部内容的人能打开，partner 永远不能。还没有 "Unindexed"。
- **要讨论的**：
  1. "Unindexed" 指什么：不出现在 Hub 的列表和搜索里、只能通过链接打开？还是不进 Consensus / 搜索引擎？
  2. 三者是否合成一个 "可见性" 选项（如 Customer facing / Internal only / Unindexed 三选一），还是保持独立的勾选？
     注意 Customer facing 和 Internal only 可以同时成立（能给客户看，但 partner 不能下载），合并时要说清楚。
  3. 对已有内容的影响：现在 Admin 的 "Hidden" 已能把 demo 从 Hub 移除；Unindexed 是否就是它的一个对外版本。
- **工作量**：定下来后 1–2 天。
- **10/27 备注**：先记录，等 Liwei 和 Seb 开会，由 Seb 说明具体要什么。
- **Seb 的定义（来自 "TMH To Do: Permissions / APIs / More" 会议的 AI 总结，Liwei 10/30 转来）**：Not Indexed 是发布前的审阅状态，放在发布后的 Low。
  不出现在搜索和首页（包括 Recent 等发现区域）；详情页照常，有链接的人能打开，页面设计不变，只加一个 "Not Indexed" 标签；管理员仍能找到和管理。
  用途（Elio）：页面已经可以发给别人审阅，但还不想让所有人在 Hub 里看到。和 Archive 不同：Not Indexed 是不被发现但可访问，Archived 是移出 Hub。
  细节待 Liwei 确认后再开发。
- **建议的做法（10/30，未开发，新功能延后到发布之后）**：约 1 天。和归档一样在列表层过滤，按链接仍能取到，但不限制谁能打开。不出现在搜索、筛选、首页、Recent、Featured、Related demos；详情页加 "Not Indexed" 标签；Content to review 加一个视图用来查找和管理；在 Manage 标签和 Content to review 批量设置，记进 Admin log。
  - **它不是权限控制**：登录的人有链接就能打开，ID 由标题生成，可以猜到；要限制访问仍用 PTC Only 或 GXC。
  - **Hub activity**：通过链接打开后不应出现在 "Most used content" 里，和 GXC 一样只对有 Maintain content 的人显示。
  - **要定**：① 谁能找到（建议 Maintain content，Seb 说的是管理员）；② Create New Demo 和 API 是否加这个选项（建议加，默认公开）；③ 状态存哪里（建议 Hub 自己的数据，不改 SharePoint 的列）；④ Partner 能否按链接打开（建议能，文件权限规则不变）。
  - **顺带**：隐藏的 Value Roadmap 标签里有 "Not indexed yet"，意思是还没有 AI 索引；S5 重新打开标签时改掉，以免混淆。

---

## C. 等别人

| 项目 | 等谁 / 什么 | 到了以后做什么 |
|---|---|---|
| C1. Consensus 内容迁移到 Demo Video | Elio 向 Myles（Consensus CSM）要的库导出 | 对照清单已做好；按导出跑迁移，视频带 Consensus ID |
| C2. Playlists 与 DemoBoard | C1 完成；Consensus 是否允许程序创建 DemoBoard | 按 10/07 定的模型：playlist 是单独条目，组成视频记 playlist ID。Summit 新设想：在 Hub 里把多个 demo 放进"剪贴板"，一键生成 Consensus DemoBoard（只链接不重传，可给某个客户专属链接、带个人介绍、以后可补内容，保留历史可复用） |
| C3. 对外分享 / 接 Consensus AI Assistant | Christine 和 Serge 的政策决定；D11 安全审查 | 分享按钮目前隐藏。Summit 讨论的方案：公开链接（可加留资）给没有 Consensus 许可证的人用，有许可证的人用 Consensus 给某个客户生成专属链接，两者并存；只有 customer-facing 的内容显示对外分享；需要对外分享时才把视频传到 Consensus，不再多处维护 |
| C4. Value Roadmap（AMP） | —— | 已并入 S5、S6（Serge 10/23） |
| C5. 其余 flagship story | Cody | Bobcat、Lamborghini 已是正式文件夹；Hill Helicopter、SDV Automotive、E&HT、Medtech Quidel Ortho 待确认 |
| C6. Partner 数据可否做区域级汇总 | Elio 问 legal（Chris McCrell） | 目前 partner 完全匿名 |
| C7. 命名、版本和分类规范 | 团队（Summit 后续任务） | 如 Jetstream 有些视频标题和时长几乎一样，分不清。规范定了以后：Hub 按规范显示版本、上传时校验命名 |
| C8. Release Notes 怎么关联 | 团队 | 继续作为 SharePoint 文档链接，还是在 Hub 里自动关联到对应产品版本的 demo |
| C9. LDK 用视频还是脚本 | 团队向一线调查 | 结果影响 A10 的模板（脚本节、视频节）；AI 从视频生成脚本是远期方向 |

---

## D. 运维与技术债

| 项目 | 为什么 | 怎么做 | 工作量 |
|---|---|---|---|
| D1. **备份 owned 数据** | 权限组、Admin log、审核记录、归档、使用历史只在 Azure Files 上，丢了找不回 | Portal 里给两个 share 开快照或 Azure Backup | 你在 Portal 里设，30 分钟 |
| D2. **关掉共享密码登录** | 管理员都走 SSO 了，过渡期可以结束 | 先确认需要进 Admin 的人都在组里，再删两个 slot 的 `ADMIN_PASSWORD`；之后再删相关代码 | 设置 5 分钟；代码清理半天 |
| D3. 安全响应头 | **10/30 已做**（5187024）：nosniff、只允许 Hub 自己嵌入、Referrer-Policy，HTTPS 的 slot 加 HSTS | —— | 完成 |
| D4. 同步失败提醒 | 失败只记在 Admin 里，没人知道 | 失败时往 Hub Tasks 写一行（可设提醒），或接 Application Insights 告警 | 半天 |
| D5. Admin 显示当前配置 | **10/30 已做**（5187024）：Overview 的 Configuration 卡片，显示登录方式、Hub Tasks、上传测试库、共享密码、curator 设置、常驻管理员；只显示数量 | —— | 完成 |
| D6. 清理 `AUTH_CURATOR_*` | **10/30 定：保留**（Liwei）。两个 slot 上只有 Liwei、Elio、Seb 三人，留作备用入口；合并权限后它们给的是 Maintain content。防止所有人被锁在外面靠的是 `HUB_ADMIN_EMAILS` | 以后想清理时：改由组管理，再删环境变量 | 暂不做 |
| D7. 删除不用的代码 | `/api/debug/backend`、SQL 存储层 | 删除并更新测试 | 半天 |
| D8. 更新 HANDOVER-DEPLOYMENT.md | 还写着 SSO 之前的生产 | 按现在的 slot、设置、swap 流程重写 | 半天 |
| D9. 删测试库和测试数据 | Gallery_Brightcove、Gallery_Brightcove_Test，Hub Tasks 第 1 行 | 每项删除前由你确认 | 你来删，10 分钟 |
| D10. 手机和无障碍检查 | 销售会用手机打开 | 手机宽度逐页过一遍，修布局；检查键盘操作和对比度 | 1 天 |
| D11. 对外开放前的安全审查 | Summit：做公开链接、对外下载之前要先验证。不是一个功能，是 C3 上线前的一次把关；这次发布只对内，不阻塞 | 先定 C3 的范围 → 威胁清单 → 公开链接的设计（随机令牌、可过期、可撤销、只限 customer-facing、限速、留日志）→ 确认 SharePoint 的恶意文件检测 → 请安全团队审查或渗透测试 | 1–2 天 + 安全团队 |
| D12. 上传被网络拦截时说清原因 | **已做**：`static/js/hub/upload.js` 在浏览器报网络错误时提示可能是 Zscaler | —— | 完成 |
| D13. 完整的内容安全策略（CSP） | 现在只有 `frame-ancestors`。页面要嵌入 SharePoint 和 Consensus，还用了内联样式，配错一项预览就全坏 | 先用 Report-Only 模式收集一段时间，确认来源后再强制 | 1 天，发布后 |
| D14. 第三方依赖的漏洞扫描 | 10/30 手动扫过一次：按 `requirements.txt` 新装的 38 个包没有已知漏洞。但 `requirements.txt` 没有固定版本，每次部署取最新版，部署之间也没人检查 | GitHub Actions 每周跑一次 `pip-audit`（或开 Dependabot，要 Seb 开仓库设置）；发布后考虑固定版本 | 半天 |

---

## 团队负责（SharePoint 数据，不改代码）
完整清单和 2026-10-28 的实测数量见 Data Clean 清单：https://claude.ai/artifact/8NJPgQ1hrbtEicmrkgYUcb
- Kit 日期显示为批量上传日（2018–19）：在 SharePoint 补 **Original publish date**。
- 没有 Demo Type 的文件夹不会出现在 Hub：补 Demo Type。
- LDK / VDK 标错的文件夹：在 SharePoint 改正 Demo Type（以后由 PM 在上传时标好）。
- 旧版 Windchill VM、Codebeamer PV：在 SharePoint 删除（Hub 本来只显示最新版本）。

---

## 去掉审核（Liwei 10/28，已上 staging）

- **决定**：有修改权限的人直接完成修改、更新、上传，不再审核；没有权限的人用 Report an issue 提要求（改 Internal / Open 选 Other，自己写明）。
- **Create New Demo**：有 Create new demo 权限的人（API token 也一样）完成即发布；去掉 "Create without review" 权限、token 的 "skip review" 选项、Send back，
  也不再为新 demo 写 Hub Tasks 行。
- **Internal / Open**：去掉 "Request content access change" 权限和申请、撤回流程；Manage content access 一次性加给 Team Member 组（production 上的名字；以后去掉不会再加回）。
- **遗留**：推送前还在等审核或被退回的上传、还没决定的访问申请，都不自动处理：Admin → Content review 列出 "Uploads left from before review was removed"
  （只有 Publish），被退回的由上传人在 My demos 里 "Fix and publish"；Admin → Content access 的 Requests 照旧可批准或拒绝。推送后把清单列给 Liwei。
- **不变**：Edit metadata、Archive 本来就不审核；Request New Asset（申请新 demo）和 Still current 不是审核，保留。

## 已完成（核对过代码，2026-10-19）
9/2–10/07 笔记里的其余要求均已实现，包括：可搜索的筛选下拉、API 与上传、视频命名和类型、
Demo Video 库、sales 预览链接、Share Internally、SharePoint 文件内嵌播放、隐藏 Servigistics、
PTC Ignition、语言标签和筛选、LDK 关联 VM、VM 页面、只显示最新版本 VM、Release Notes 不算 demo、
CAD model 浏览、隐藏旧 CAD 产品、去掉来源标签、Bobcat、Featured、Brightcove 迁移工具、
用户管理和权限、PTC 员工按人统计（partner 匿名）、Hub activity、SSO、Consensus V2（OAuth）、
描述移出卡片（旧设计）、LDK/VDK 名称（源于旧的错误 VDK 列，已修正）。

2026-10-21 新增：SharePoint 故事页的简介、分节和文件顺序合并进 demo 页面（Jorge 的 IPL 页面；
读取 CanvasContent1，含 flexible 区域）。Creo Illustrate - Capabilities 页面内嵌的视频不读取，保持现状（Liwei 10/21）。

Summit 列为后续任务、但其实已经有的：上传时选择预览视频（两个以上视频时必须选 PreviewVideo，网页和 API 都是）；
对内分享直接定位到包里的某个视频（每个文件都有 Share 链接）；手动刷新；年龄标签；文件级搜索；API token 管理。

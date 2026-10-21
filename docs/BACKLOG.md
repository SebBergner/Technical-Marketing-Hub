# Technical Marketing Hub — 待办清单

更新于 2026-10-20（生产 v2026.3.123）。来源：9/2–10/7 的会议笔记、管理层 10/02 的六项要求、
Serge / Seb / Elio 的意见、2026-10-16 的全面代码扫描，以及常见内部内容门户的做法。

每一项写明：**来源**、**现状**、**做法**、**要先定的事**、**工作量**、**依赖**。
工作量是粗估，按"开发 + 测试 + 上 staging"计。

SharePoint 里的数据清理（kit 日期、Demo Type、标错的 LDK/VDK、旧版 VM）由团队负责，
不在本清单内，见文末。

---

## TMH Checkpoint（Serge 的会议，2026-10-23）

Serge 列了 5 个话题：表格视图和卡片日期可以直接做；订阅和 Dashboard 要先问清楚范围；
Value Roadmap 搜索卡在 AMP 数据上。

| 话题 | 现状 | 工作量 | 卡在哪里 |
|---|---|---|---|
| S1. 订阅新内容 | 无（即 A7）；只有 Recently published | 半天到 2 天，看做法 | 渠道和范围未定 |
| S2. Dashboard | 部分已有（Hub activity；Admin 的 Content dashboard） | 1–3 天 | 要先定是哪一种 |
| S3. 年龄 / 卡片显示发布日期 | 已有年龄标签 | 约 2 小时 | 日期数据质量 |
| S4. 卡片视图 vs 表格视图 | 只有卡片 | 1–1.5 天（加导出 CSV 再半天） | 无，可直接做 |
| S5. Value Roadmap 搜索（Process、Capability） | demo 页已留位置；1,715 条数据里一条都没有 | 数据到后 2–3 天 | 等 AMP 和 Seb（即 C4） |

### S1. 订阅新内容
- **他要的**：不用天天来 Hub 翻，也能知道有新 demo。
- **做法 a：Teams 频道推送**（约半天）：新 demo 上线时自动发到一个 Teams 频道，全组共享；
  用 Power Automate，和 Hub Tasks 同一套机制。
- **做法 b：Hub 内"自你上次来以后的新内容"**（约 1 天）：首页显示"上次访问后新增了 N 个 demo"，
  卡片标 "New for you"，按登录时间计算。
- **做法 c：每周邮件摘要**（约 2 天，加发信渠道配置）：按产品或 segment 订阅；用 Power Automate
  或 Seb 的 Azure 邮件服务。
- **建议**：先 a，再 b；c 留到下一阶段。
- **要问他**：给个人还是全组；Hub 内、邮件还是 Teams；实时、每天还是每周；按产品、segment 还是全部。

### S2. Dashboard
- **现状**：Hub activity（所有 PTC 员工）有使用量、最常用 demo、创建者排行、每日趋势；
  Admin → Content dashboard（只有管理员）有内容总量、分布和数据完整度。
- **要问清是哪一种**：
  1. 使用情况：给 Hub activity 补视角（按产品 / segment 的使用量、搜索热词），约 1 天。
  2. 内容健康度：每个产品有多少 demo、年龄分布、哪些产品缺内容、多少已过时，约 2–3 天。
  3. 给管理层的一页汇总。
- **注意**：内容健康度公开给所有人，"未填写"的比例也会被大家看到（与 B4 同一个问题）。

### S3. 年龄 / 卡片显示发布日期
- **现状**：卡片上已有他 10/13 给的年龄标签：1 年内 New；1–2 年无标签；2–4 年显示年份；
  4 年以上 "Older UI · 年份"；有 Still current 时显示 Still current。
- **做法**（约 2 小时）：卡片文字行加 "Published Mar 2024"，或让 1–2 年那一档也显示年份。
- **要提醒他**：许多 kit 的日期仍是批量上传日（10/15 测过，比如 104 个 kit 都是 2018-12-13），
  显示具体日期会让这批错误很扎眼。建议只显示到月份，或只在填了 Original publish date 的 demo
  上显示日期；同时借此推动团队补日期。

### S4. 卡片视图 vs 表格视图
- **做法**：结果区右上角加视图切换。表格列：标题、类型、产品、segment、语言、发布日期 / 年龄、
  浏览量；点列名排序，点一行打开 demo；筛选和搜索对两种视图都生效；每人的选择记在自己的浏览器里。
  可顺带加"导出 CSV"。
- **要问他**：要哪些列；默认哪种视图；要不要导出。

### S5. Value Roadmap 搜索（Process、Capability）
- **他要的**：按业务流程（如 Change Management、BOM）和能力找 demo。
- **现状**：数据由 AMP 分析视频生成，Seb 会把每个 demo 的 JSON 文件放进对应文件夹（9/8 定的方案），
  目前还没有。
- **数据到了以后**：同步时读取 JSON，demo 页显示内容，搜索和筛选加上 Process / Capability。
- **要确认**：AMP 什么时候开始产出、先覆盖哪些 demo（问 Seb）；Process 和 Capability 有没有固定分类
  （有就做筛选下拉，没有只能文字搜索）；能否先给 1–2 个 JSON 样例，提前做好读取和显示。
  最好请 Seb 一起参会。

---

## A. 可以直接开始（不依赖外部）

### A1. 在 Hub 里编辑元数据（"打标签"）
- **来源**：管理层 10/02 第 3 项 "Tag assets as needed"；workshop 上"请大家修日期、修元数据"。
- **现状**：后台有权限 `edit_metadata` 和写回接口（`backend/integrations/graph/writeback.py`、
  `/api/curation`），但**没有任何界面**。写回目前只填**空**列；列里已有不同的值时会停下、不写。
- **做法**：在 demo 页的 Manage 标签加 "Edit details"，可改 Product、Segment、Language、
  Original publish date、Customer facing（Demo Video 另有 Video Type）。保存时先重读 SharePoint，
  用 ETag 防并发覆盖；每次修改记进 Admin log，可在 SharePoint 版本历史里追溯。
  Consensus 的条目只读（Consensus 不由 Hub 写）。
- **要先定的事**：
  1. **允许覆盖已有值**——已定（Liwei 10/20）：Hub 已能在 SharePoint 创建 demo，"不修改 SharePoint"
     的原则不再适用；只要确保只有有 `edit_metadata` 权限的人能改，每次改动留痕。
  2. 改动要不要审核后才写回，还是直接写？
  3. 谁有权限：目前 Administrators 和 TDD Team 都勾了 `edit_metadata`。
- **工作量**：2–3 天。
- **依赖**：无。

### A2. 支持 / 内容问题表单（用 Hub Tasks 接收）
- **来源**：Seb，10/07 会议 —— 和 "Share feedback"（对应用的反馈）、"Request New Asset"
  （申请新 demo）分开，专门处理已有内容的问题和求助。
- **现状**：没有。Hub Tasks 列表的 TaskType 已预留 "Support request"。
- **做法**：两个入口 —— demo 页上的 "Report an issue"（自动带上 demo 链接）和侧边栏的 "Get help"。
  表单字段：类别（文件打不开/缺失、内容过时或有错、演示环境/VM、找不到内容、其他）、说明、
  可选附件。提交后写进 Hub Tasks（Open），处理人在 SharePoint 里改状态；Hub 里提交人能看到状态。
- **要先定的事**：
  1. 类别列表，以及每类发给谁（Elio 提过：CAD → Avi 和 Elio）。按类别分派可以在 Hub Tasks 上用
     Power Automate 做，需要再加一个 "Category" 列（你来建）。
  2. Partner 能不能提交？能的话，按匿名原则不记名字，只记"partner"。
- **工作量**：1–2 天。
- **依赖**：A2 的分派规则。

### A3. 收藏 / 我的清单
- **来源**：常见门户的基本功能；侧边栏原设计里就有 Favorites，目前被移除（"需要按人存储"）。
- **现状**：没有。
- **做法**：卡片和 demo 页加星标；侧边栏 "Favorites" 打开自己的清单。按登录邮箱存在
  `owned/favorites.json`，只有本人能看到。
- **要先定的事**：Partner 也要有吗？有的话按 Entra 对象 ID 存，不在任何报表里出现。
- **工作量**：1 天。
- **依赖**：无。

### A4. Demo 负责人 / 联系人
- **来源**："这个 demo 该问谁"；排行榜把代传的 demo 算到上传人名下（如 Lamborghini）。
- **现状**：负责人取自 SharePoint 文件的创建者。
- **做法**：你在 Demo Catalog 和 Demo Video 各加一个 Person 列 "Demo Owner"；Hub 优先读它，
  没填再用文件创建者。demo 页显示 "Contact: 姓名"（可点发邮件），"Whose demos were used most"
  也按它统计。Hub 只读这一列（Person 列 Hub 写不了，已在 Demo Requests 列表验证）。
- **要先定的事**：要不要加这一列；谁负责填。
- **工作量**：1 天（加列由你在 SharePoint 里做）。
- **依赖**：列建好。

### A5. 搜索质量
- **来源**：Admin → Hub usage 里的"零结果搜索"。
- **现状**：标题优先，描述命中排后；没有同义词和拼写纠错。
- **做法**：按零结果搜索的真实记录建同义词表（如 WC → Windchill、CB → Codebeamer、IPL、SLM），
  加简单的拼写容错；搜不到时提示"你是不是要找…"。
- **要先定的事**：无（同义词表可以先给你过目）。
- **工作量**：1 天。

### A6. 协助团员归档过期 demo（Liwei 10/21，含原"团队用的内容复查清单"）
- **来源**：Liwei 2026-10-21：团员需要在 Hub 里把过期的 demo 归档。归档标准来自 10/07 会议
  （Elio：约 1 年；Seb：还要看使用量）和 Serge 的年龄方案。
- **现状**：归档功能已有，只在 Hub 里隐藏、SharePoint 不动、可以 Restore。TDD Team 有 Review content，
  能在 demo 页的 Manage 标签里逐个归档。但"哪些该归档"的清单（超过 7 年、一年以上且半年没人用、
  Still current 快过期）只在 Admin → Content review 里，团员没有 View Admin，看不到；也没有批量操作。
- **做法**：
  1. Hub 里加一个 "Content to review" 视图，只对有 Review content 的人显示。默认先显示**自己创建的**
     demo（按创建者匹配，归档请求首先落在作者身上），可切换到全部、按产品 / 年龄筛选。
  2. 每行显示年龄、最近一次被使用的日期、为什么出现在清单里。不带任何按人的使用数据。
  3. **批量操作**：勾选多个后 "Archive"（填一个理由）或 "Still current"；都可以撤销，都写进 Admin log。
  4. 可选：一次性"清理行动"，给每位创建者在 Hub Tasks 里写一行"你有 N 个 demo 待复查"，
     配合 workshop 上 "own your content" 的请求。
- **要先定**：归档标准（年龄和未使用时长的阈值）；团员能否归档**别人**的 demo，还是只能处理自己的
  （其余由 Serge 或管理员处理）；要不要做清理行动。
- **注意**：创建者来自 SharePoint 文件创建者，代传的 demo 会算到代传人名下；做了 A4（Demo Owner）后会更准。
- **工作量**：清单视图 1 天；批量操作半天；清理行动半天。合计约 2 天。

### A7. 订阅新 demo 通知
- **来源**：常见门户功能；让销售知道"我关心的产品有新 demo 了"。
- **做法**：按产品或 segment 订阅，每周一封摘要。可以用 SharePoint 列表加 Power Automate 发信，
  Hub 不用自建发信。
- **要先定的事**：发信渠道（Power Automate / Seb 的 Azure 邮件服务）；是否值得做。
- **工作量**：1–2 天。

---

## B. 要先定方向

### B1. 点赞、评论与作者通知（Liwei 10/20 的设想，含原"评论功能"）
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

### B4. 主页 dashboard 的范围
- **来源**：管理层 10/02 第 5 项。
- **现状**：Hub activity 已对所有 PTC 员工开放。
- **要先定的事**：是否还需要更多（比如内容统计、数据完整度对所有人公开）？公开意味着
  "未填写"的比例也会被所有人看到。

### B5. 视频自动画面作缩略图，自选图片可选（待与 Elio 讨论）
- **来源**：Liwei，2026-10-20。许多 demo 只有生成的封面：没有故事页的 kit、通过 Hub 上传的视频
  （没有 Brightcove 海报）。本地粗算约 400 个 kit 有视频、没有图片。
- **实测（2026-10-21）**：随机抽 24 个真实视频（18 个 Demo Catalog kit 的主视频、6 个 Demo Video 视频），
  取 SharePoint 自动生成的缩略图：**没有一张黑屏或偏暗**，都是视频中间的实际画面（软件界面、模型）。
  个别不理想：一张是登录页，一张带字幕。（scratchpad/video_frames.py）
- **结论**：**自动画面就是默认方案**，上传时不用自己截前几秒的画面；"浏览器截帧"和"服务器用 ffmpeg
  截第 3 秒"都不再需要。
- **第一步：主视频的自动画面**（约半天）：没有其他图片的 demo，用 SharePoint 为主视频生成的缩略图，
  经 Hub 自己的缩略图地址提供（取图、缓存、同步后预热都已有）。不用加列、不改上传流程；已有的几百个
  demo 和以后通过 Hub 上传的视频立刻有图。
- **第二步（可选）：自己上传一张图**（约 1.5 天，含 API）：为了避开登录页这类画面、或用一张更有代表性的图。
  Create New Demo 的 Files 一步加可选的 "Thumbnail"，API 加可选字段 `thumbnail`（不填就用自动画面，
  现有脚本不用改）。图片作为普通文件存进 demo 文件夹，用文件级是/否列 `HubThumbnail` 标记（和
  PreviewVideo 同一种做法，只有做这一步才需要你加列）。
- **封面优先顺序**：自选图片 → 故事页图片 → Brightcove 海报 → 主视频自动画面 → 生成的封面。
- **要和 Elio 定**：先做第一步是否就够；要不要第二步；已有 demo 以后能否在 Manage 标签里换图。
- **工作量**：第一步约半天；两步合计约 2 天（原估 3–4 天）。

---

## C. 等别人

| 项目 | 等谁 / 什么 | 到了以后做什么 |
|---|---|---|
| C1. Consensus 内容迁移到 Demo Video | Elio 向 Myles（Consensus CSM）要的库导出 | 对照清单已做好；按导出跑迁移，视频带 Consensus ID |
| C2. Playlists | C1 完成 | 按 10/07 定的模型：playlist 是单独条目，组成视频记 playlist ID，视频页写"属于 playlist X" |
| C3. 对外分享 / Share DemoBoard / 接 Consensus AI Assistant | Christine 和 Serge 的政策决定 | 分享按钮目前隐藏；政策定了再接 |
| C4. Value Roadmap（AMP） | Seb 把每个 demo 的 JSON 放进其文件夹 | 同步时读取 JSON，demo 页的 Value Roadmap 卡片显示内容 |
| C5. 其余 flagship story | Cody | Bobcat、Lamborghini 已是正式文件夹；Hill Helicopter、SDV Automotive、E&HT、Medtech Quidel Ortho 待确认 |
| C6. Partner 数据可否做区域级汇总 | Elio 问 legal（Chris McCrell） | 目前 partner 完全匿名 |

---

## D. 运维与技术债

| 项目 | 为什么 | 怎么做 | 工作量 |
|---|---|---|---|
| D1. **备份 owned 数据** | 权限组、Admin log、审核记录、归档、使用历史只在 Azure Files 上，丢了找不回 | Portal 里给两个 share 开快照或 Azure Backup | 你在 Portal 里设，30 分钟 |
| D2. **关掉共享密码登录** | 管理员都走 SSO 了，过渡期可以结束 | 先确认需要进 Admin 的人都在组里，再删两个 slot 的 `ADMIN_PASSWORD`；之后再删相关代码 | 设置 5 分钟；代码清理半天 |
| D3. 安全响应头 | 现在没有 HSTS、X-Content-Type-Options、frame-ancestors | 中间件统一加 | 半天 |
| D4. 同步失败提醒 | 失败只记在 Admin 里，没人知道 | 失败时往 Hub Tasks 写一行（可设提醒），或接 Application Insights 告警 | 半天 |
| D5. Admin 显示当前配置 | 今天只能靠实际操作确认 Hub Tasks 开没开 | Overview 加一行：Hub Tasks 列表、上传是否指向测试库 | 2 小时 |
| D6. 清理 `AUTH_CURATOR_*` | 只给 Edit metadata，已被权限组取代 | 改由组管理，删过时的警告，之后可删环境变量 | 半天 |
| D7. 删除不用的代码 | `/api/debug/backend`、SQL 存储层 | 删除并更新测试 | 半天 |
| D8. 更新 HANDOVER-DEPLOYMENT.md | 还写着 SSO 之前的生产 | 按现在的 slot、设置、swap 流程重写 | 半天 |
| D9. 删测试库和测试数据 | Gallery_Brightcove、Gallery_Brightcove_Test，Hub Tasks 第 1 行 | 每项删除前由你确认 | 你来删，10 分钟 |
| D10. 手机和无障碍检查 | 销售会用手机打开 | 手机宽度逐页过一遍，修布局；检查键盘操作和对比度 | 1 天 |

---

## 团队负责（SharePoint 数据，不改代码）
- Kit 日期显示为批量上传日（2018–19）：在 SharePoint 补 **Original publish date**。
- 没有 Demo Type 的文件夹不会出现在 Hub：补 Demo Type。
- LDK / VDK 标错的文件夹：在 SharePoint 改正 Demo Type（以后由 PM 在上传时标好）。
- 旧版 Windchill VM、Codebeamer PV：在 SharePoint 删除（Hub 本来只显示最新版本）。

---

## 已完成（核对过代码，2026-10-19）
9/2–10/07 笔记里的其余要求均已实现，包括：可搜索的筛选下拉、API 与上传、视频命名和类型、
Demo Video 库、sales 预览链接、Share Internally、SharePoint 文件内嵌播放、隐藏 Servigistics、
PTC Ignition、语言标签和筛选、LDK 关联 VM、VM 页面、只显示最新版本 VM、Release Notes 不算 demo、
CAD model 浏览、隐藏旧 CAD 产品、去掉来源标签、Bobcat、Featured、Brightcove 迁移工具、
用户管理和权限、PTC 员工按人统计（partner 匿名）、Hub activity、SSO、Consensus V2（OAuth）、
描述移出卡片（旧设计）、LDK/VDK 名称（源于旧的错误 VDK 列，已修正）。

# Technical Marketing Hub — 待办清单

更新于 2026-10-19（生产 v2026.3.119）。来源：9/2–10/7 的会议笔记、管理层 10/02 的六项要求、
Serge / Seb / Elio 的意见、2026-10-16 的全面代码扫描，以及常见内部内容门户的做法。

每一项写明：**来源**、**现状**、**做法**、**要先定的事**、**工作量**、**依赖**。
工作量是粗估，按"开发 + 测试 + 上 staging"计。

SharePoint 里的数据清理（kit 日期、Demo Type、标错的 LDK/VDK、旧版 VM）由团队负责，
不在本清单内，见文末。

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
  1. **允许覆盖已有值吗？** 这会改变"Hub 不修改 SharePoint 已有内容"的原则，需要你明确同意。
     折中做法：只允许改有 `edit_metadata` 权限的人，并且每次改动都留痕。
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

### A6. 给团队用的内容复查清单
- **来源**：TDD Team 没有 View Admin，看不到 Admin → Content review 的清单（太旧、很久没人用、
  Still current 快过期）。
- **做法**：把这份清单放进 Hub（例如 Hub activity 旁边一个 "Content to review"），
  只对有 `review_content` 的人显示。不暴露任何按人的使用数据。
- **要先定的事**：Serge 希望团队自己过这份清单吗？
- **工作量**：1 天。

### A7. 订阅新 demo 通知
- **来源**：常见门户功能；让销售知道"我关心的产品有新 demo 了"。
- **做法**：按产品或 segment 订阅，每周一封摘要。可以用 SharePoint 列表加 Power Automate 发信，
  Hub 不用自建发信。
- **要先定的事**：发信渠道（Power Automate / Seb 的 Azure 邮件服务）；是否值得做。
- **工作量**：1–2 天。

---

## B. 要先定方向

### B1. 评论功能
- **来源**：9/8、9/9 与 Elio 的会议。
- **现状**：没有。
- **要先定的事（和 Elio）**：
  1. 评论挂在 demo 上，还是挂在单个文件上？
  2. 存在哪里：Hub 自己（`owned/comments.jsonl`，只追加）还是 SharePoint 列表（团队可在 SharePoint 里看）？
  3. 谁能评论、谁能看到；partner 能不能看到/发表（匿名原则）。
  4. 能否删除、谁来管理；新评论要不要通知 demo 负责人（可走 Hub Tasks）。
- **工作量**：定下来后 2 天。

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

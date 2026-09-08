# 中文操作指南：改完代码之后怎么推送和部署

写给 Liwei，2026-09-03。假设你手边没有 AI 助手，只有终端和 Azure 门户。

英文版的完整交接在 `docs/HANDOVER-DEVELOPMENT.md`（开发）和
`docs/HANDOVER-DEPLOYMENT.md`（部署）。这一份只讲**你自己动手时的操作流程**。

---

## 0. 先记住三件事

**① 部署是自动的，触发条件只有一个：有代码推到 `main`。**
没有别的开关，没有确认步骤。推上去大约 1 分钟后线上就变了。

**② 数据不走 git。**
`data/runtime/` 是 gitignore 的，而且必须是。线上的数据在 Azure Files
（`/mnt/data`），本地的数据在你电脑上，两边**互不影响**。改代码不会动数据，
上传数据也不需要部署。

**③ 密钥永远不进仓库。**
`.env` 是 gitignore 的。线上的凭据在 Azure 的 App settings 里。
`.env.example` 是提交的，里面**只能有空值和说明**。

---

## 1. 日常流程：改完代码，推上去

### 1.1 完整命令序列

```bash
cd "C:\Work\TDD Hub\technical-marketing-hub\technical-marketing-hub"
```

**第一步，看看自己改了什么。** 不要跳过这步。

```bash
git status
```

```bash
git diff
```

**第二步，跑测试。** 365 个测试大约 35 秒。这一步能挡掉绝大多数"改 A 弄坏 B"。

```bash
python -m pytest tests/ -q
```

看到 `365 passed, 2 skipped` 才继续。（2 个 skip 是正常的，它们有条件跳过。）
如果有 failed，**先修，不要推**。

**第三步，本地起服务器看一眼。**

```bash
python -m uvicorn app:app --reload --port 8000
```

浏览器打开 http://localhost:8000 。看完 `Ctrl+C` 停掉。

> 注意：改了 mirror 数据字段的形状之后，`--reload` 有时候不会真的重载。
> 这个坑在这个项目里踩过至少三次 —— 表现是"我明明改了但没生效"。
> 遇到这种情况**完全停掉再重启**，不要怀疑代码。

**第四步，提交。**

```bash
git add -A
```

```bash
git commit -m "描述你改了什么"
```

**第五步，推到你的分支。**

```bash
git push origin liwei-backend-dev
```

到这里线上**还没有变化**。`liwei-backend-dev` 只是你的工作分支。

### 1.2 提交信息怎么写

这个仓库的习惯是**写事实，不写动作**。对比一下：

| 不好 | 好 |
|---|---|
| `fix sync bug` | `fix: a Graph delta sync was rewriting the mirror from a partial page` |
| `update UI` | `feat: three doors on a card, and the marketing view instead of the sales one` |
| `改了一些东西` | `fix: the hiding rule sat 2.5 MB after the markup it hides` |

半年后你自己回来看 `git log`，第二列能读懂，第一列不能。前缀用
`feat:` / `fix:` / `docs:` / `style:`。中文也可以，一致就行。

---

## 2. 部署到线上：合并到 `main`

### 2.1 用 Pull Request（推荐）

```bash
gh pr create --base main --head liwei-backend-dev --title "标题" --body "说明"
```

然后在网页上点 merge，或者：

```bash
gh pr merge <编号> --squash
```

`--squash` 的意思是把你这一串提交压成一个再合进 `main`。推荐这样，
因为 `main` 是 Elio 也在用的分支，保持干净。

### 2.2 直接合并（急用时）

```bash
git checkout main
```

```bash
git pull origin main
```

```bash
git merge liwei-backend-dev
```

```bash
git push origin main
```

```bash
git checkout liwei-backend-dev
```

**最后一行别忘了**，切回自己的分支再继续干活。

### 2.3 看部署进度

```bash
gh run watch
```

或者：

```bash
gh run list --limit 3
```

去网页看：https://github.com/SebBergner/Technical-Marketing-Hub/actions

大约 1 分钟。绿勾就是好了。

### 2.4 部署完检查什么

按这个顺序，每一步都是在排除一类问题：

| 网址 | 看什么 |
|---|---|
| `/health` | 活着没有。最基本 |
| `/api/debug/backend` | 用的哪个仓储、凭据配了没有、有没有安全警告 |
| `/api/auth/me` | 认证生效没有。`warnings` 应该是空数组 |
| `/api/assets?limit=1` | 数据在不在。`total` 应该是 807 左右 |
| `/` | 界面。左边导航应该是八个产品族，**不是** Elio 带 logo 的那个列表 |

如果 `/` 一闪而过出现 Elio 的 mock-up（带产品 logo 的旧列表），
说明有人动了 `index.html` 顶部那个 `<style>` 块 —— 那个块**必须**留在文件最
上面，原因写在 `HANDOVER-DEVELOPMENT.md` §5.2。

---

## 3. 更新线上数据（和代码完全无关的另一件事）

线上的数据在 Azure Files 的 `/mnt/data`，结构是：

```
/mnt/data/
  mirror/          可以随时重建 —— 重新 sync 就有了
    sharepoint.json
    consensus.json
    seed.json
  owned/           Portal 自己产生的，重建不了
    identity.json        ← 最重要的一个
    curation.json
    stats.json
    share_events.jsonl
    sync_state.json
    segments.json        ← 还没有，需要你手写
```

### 3.1 两种更新方式

**方式 A：让线上自己去同步**（数据最新，需要凭据已配好）

```
POST https://<你的域名>/api/graph/sync
POST https://<你的域名>/api/consensus/sync
```

SharePoint 有 delta token，没变化的时候几乎不花钱，可以经常跑。
Consensus 没有 delta，每次都拉全量，一天一两次就够。

> **目前没有任何自动同步。** 没有定时器、没有后台任务。你不手动调用，
> 数据就一直不变，而且**不会有任何提示**。这是已知的、Liwei 你自己同意
> 先这样的。要做的话是加一个 Azure Timer 去调这两个接口。

**方式 B：从本地上传**（不需要凭据，适合第一次和救急）

Azure 门户 → 存储账户 → 文件共享 → 你的共享 → 建 `mirror` 和 `owned` 两个目录
→ 分别上传文件。8 个文件，2.2 MB。

或者 SSH 进容器之后解压：

```bash
cd /mnt/data && unzip /home/mnt-data-initial.zip
```

### 3.2 上传后要重启吗

要。App Service → Overview → **Restart**。

原因：JSON 仓储对 mirror 文件做了缓存，key 是文件 mtime。正常写入时代码会主动
让缓存失效，但你从门户传文件绕过了代码，所以进程里还是旧的。重启最省事。

### 3.3 千万别做的两件事

**① 别在 `/mnt/data/mirror/` 里放来路不明的 `.json`。**
代码会读那个目录下的**每一个** `.json` 文件，多一个文件就多一批资产。
这个项目出过一次：seed 和第一次 Graph 同步共存，455 个资产变成 907 行。

**② 别删 `owned/identity.json`。**
它记录每个资产的 `first_seen_at` 和退役历史，删了重建不出来。
真要动之前先下载一份备份。

### 3.4 填 segments.json（2026-09-08 更新：优先级降低了）

这条本来是"待办第一条"，但 segment 落地页后来被 Seb/Elio/Serge 三个人在评审时
各自独立提出"应该按产品浏览，不要按 segment"，已经从左边导航拿掉了（现在导航
走的是"Browse by Product"）。`/api/segments` 接口还在、还能用，但**现在没有
入口能点到这个页面**，所以填不填这个文件影响很小。除非以后又把 segment 页面
接回导航，否则不用优先做这个。

格式留档以防以后用得上：

```json
{
  "CAD": {
    "blurb": "一句话介绍这个 segment 有什么内容",
    "owner": { "name": "某某", "email": "someone@ptc.com" },
    "updated_by": "Liwei Chen",
    "updated_at": "2026-09-03"
  }
}
```

---

## 4. Elio 改了 `index.html` 怎么办

这是最容易出问题的场景，单独说。

`index.html` 是 Elio 的文件，我们的集成是**故意做成非侵入式**的：只加了一个
`<script>` 标签和文件顶部一个 `<style>` 块。所以合并他的新版本应该是简单的。

```bash
git fetch origin
```

```bash
git merge origin/Elio-UI-Development
```

如果 `index.html` 冲突了，**保留 Elio 的内容**，然后确认我们那两块还在：

1. 文件**最顶部**、`<title>` 后面那个 `<style>` 块（藏 mock-up 用的，
   必须在它要藏的 markup 前面，因为这个文件没有 `<head>`）
2. 文件底部引入 `static/hub-api.js` 的 `<script>` 标签

合并完必须做的验证：

```bash
python -m pytest tests/ -q
```

然后本地起服务器，**刷新几次**看左边导航会不会闪一下 Elio 的旧产品列表。
会闪就是第 1 块丢了。

---

## 5. 出问题了怎么退回去

### 5.1 回滚线上代码

```bash
gh run list --limit 10
```

找到上一个好的版本，然后：

```bash
gh workflow run "Build and deploy Python app to Azure Web App - Technical-Marketing-Hub" --ref <好的commit的sha>
```

或者在 `main` 上 revert 那次合并，push 上去自动重新部署。

### 5.2 两样东西不会跟着代码回滚

- **App settings**（环境变量）。改了 `AUTH_MODE` 或 `DATA_DIR` 属于配置变更，
  回滚代码不会把它们改回去。
- **`/mnt/data` 里的数据。** 一旦有真实用户提交过请求，那些数据比任何代码版本
  都新。回滚代码不动它 —— 这是对的，但意味着如果你改了这些文件的格式，
  **没有迁移机制**，要自己想清楚。

---

## 6. 安全清单（每次推之前扫一眼）

- [ ] `.env` 没有被 `git add`（`git status` 里不该出现它）
- [ ] `.env.example` 里没有真值
- [ ] 代码和文档里没有粘贴过 client secret、api secret、storage access key
- [ ] `data/runtime/` 没有被提交

快速自查：

```bash
git diff --cached --name-only
```

看到 `.env` 或 `data/runtime/` 就是出问题了，用 `git reset HEAD <文件>` 撤掉。

### 关于认证，一个必须记住的组合

**「Graph 凭据已配 + `AUTH_MODE` 没配」= 公网上任何人都能往 SharePoint 写东西。**

`AUTH_MODE` 默认是 `disabled`，那个模式下代码给每个访问者一个开发身份，
权限全开 —— 本地开发这样是对的，线上不是。App 会在启动日志、`/api/auth/me`
和 `/api/debug/backend` 里报告这个状态，但**它只是警告，不会拦截请求**。

所以：**认证先开，Graph 凭据后配。** 顺序反了会开一个真的口子。

---

## 7. 常用命令速查

| 想做什么 | 命令 |
|---|---|
| 跑测试 | `python -m pytest tests/ -q` |
| 跑单个测试文件 | `python -m pytest tests/test_repository.py -q` |
| 本地起服务 | `python -m uvicorn app:app --reload --port 8000` |
| 看改了什么 | `git status` / `git diff` |
| 提交 | `git add -A` then `git commit -m "..."` |
| 推自己分支 | `git push origin liwei-backend-dev` |
| 拉别人的更新 | `git fetch origin` then `git merge origin/main` |
| 看部署 | `gh run watch` |
| 看 PR | `gh pr list` / `gh pr view <编号>` |
| 撤销还没提交的改动 | `git checkout -- <文件>` |
| 撤销 `git add` | `git reset HEAD <文件>` |

---

## 8. 卡住的时候先看哪里

| 现象 | 先看 |
|---|---|
| 线上打不开 | Azure → Log stream；然后 `/health` |
| 打开了但没数据 | `/api/debug/backend`，看仓储和凭据；再看 `/mnt/data` 有没有东西 |
| 数据是旧的 | **`POST /api/graph/sync` 在线上现在会被拒绝**（2026-09-08 起）——没人有 curator 权限（`AUTH_CURATOR_GROUPS` 还是空的）。现在唯一的刷新方式是：本地跑 sync → 把 `data/runtime/mirror/*.json` 传到 Azure Files 的 `mirror/` 目录 → 重启 App Service。见 §3 |
| 一闪而过 Elio 的 mock-up | `index.html` 顶部的 `<style>` 块被动了 |
| 改了代码本地没生效 | 完全停掉服务器重启，不要靠 `--reload` |
| sync 报 `WouldShrinkMirror` | **这是保护机制在起作用**，不是 bug。说明这次拉到的数据不到原来的一半，通常是分页被当成了全量。查清楚再说，别直接加 `allow_shrink=True` |
| Consensus 的 tag 突然全没了 | `CONSENSUS_V2_TOKEN` 过期了。去 `https://app.goconsensus.com/api/v2/docs/portal/` 重新复制一个 |
| 部署失败 | `gh run view <id> --log-failed` |
| 视频/图片预览弹窗一片空白 | 检查 iframe 有没有 `referrerpolicy="no-referrer"`——SharePoint 的播放页没有 referrer 就渲染不出东西，这个属性是从 Consensus 那个弹窗抄过来的坑 |
| Word/PPT 预览弹窗一片空白 | **这个改不了**——微软 Office 在线查看器自己拒绝在任何跨域 iframe 里运行，同一个链接单独开标签页是好的。这就是为什么文档类文件走"新标签页打开"而不是弹窗 |

---

## 9. 还没做的事（2026-09-08 更新）

上次这里排第一的"填 segments.json"已经降低优先级了——segment 页面被拿掉了
导航入口，见 §3.4。Load More、文件下载/预览、Servigistics 隐藏、IPE 改名、
Language 筛选、LDK 时长隐藏这些都已经上线，不再是待办。

1. **开 Easy Auth 的"Require authentication"**（平台层，不是 App Setting 那个
   `AUTH_MODE=easyauth`）——现在只是应用层信任了 EasyAuth 的 header，Azure
   平台本身没有强制登录，所以匿名也能读到全部数据。同时要把某个 Entra 用户组
   填进 `AUTH_CURATOR_GROUPS`，不然登录了也没人有 curator 权限，`/api/graph/sync`
   照样会被拒绝
2. 做完①之后：
   - 把 `static/hub-api.js` 里的 `SHARE_BUTTON_HIDDEN` 改成 `false`
   - 就能配一个有 curator 权限的账号/服务主体，加定时同步（Azure Timer 调
     `/api/graph/sync` 和 `/api/consensus/sync`）
3. **在 workflow 里加测试步骤** —— 一行，能挡住坏代码上线（部署了 11 次都是
   靠人肉跑测试再推的，还没出过事，但迟早的事）
4. **View All Requests 列表**（Serge 要的）
5. **Admin 区域**
6. **Request New Asset 表单的产品按钮里还有 Servigistics** —— 隐藏 Servigistics
   时漏了这一处，是完全独立的一段代码（`fillProductPills()`）

被别人卡住的：customer-facing 标签（没有数据源）、Value Roadmap（**已经不是
"等 Seb 演示做法"了**——已经定了是 Seb 那边出一个 AMP 分析出来的 json 文件，
放进每个 demo 文件夹里，我们直接读文件，等他交付）、Consensus tag 长期可用
（等 Consensus 支持回复那个 bcrypt 密钥问题）。

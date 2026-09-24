# AIHOT 每日邮件订阅

每天发 **两封**邮件（北京时间）：

| 时间 | 邮件 | 内容来源 |
|---|---|---|
| **09:00** | AIHOT **日报** | 当天精编日报 `GET /api/v1/dailies/latest`（约 08:00 生成） |
| **14:30** | AIHOT **速递** | 当天日报发布**之后**新增的高价值精选条目 `GET /api/v1/items` |

- **无需服务器**：由 GitHub Actions 执行
- **准点可靠**：由外部定时器（cron-job.org）在到点调用 `workflow_dispatch` 触发，绕开 GitHub `schedule` 的数小时漂移
- **发信**：QQ 邮箱 / 163 邮箱的 SMTP

## 目录结构

```
.
├── .github/workflows/send-daily-report.yml   # 工作流（支持 daily / updates 两种邮件）
├── send_daily_report.py                       # 抓取 → 生成 HTML → 发信
└── README.md
```

脚本通过环境变量 `REPORT_KIND` 选择邮件类型：
- `REPORT_KIND=daily`  → 当天日报
- `REPORT_KIND=updates` → 下午新增精选

## 一、准备发件邮箱的 SMTP 授权码

需要开启邮箱的 SMTP 服务并拿到「授权码」（不是登录密码）。

### QQ 邮箱
1. 登录 [mail.qq.com](https://mail.qq.com)，进入 **设置 → 账户**
2. 找到 **POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务**
3. 开启「**SMTP 服务**」，按提示用手机短信验证
4. 生成并复制 **授权码**（16 位字母）

- SMTP 服务器：`smtp.qq.com`，端口 `465`
- SMTP 用户名：你的 QQ 邮箱地址（`xxx@qq.com`）

### 163 邮箱
1. 登录 [mail.163.com](https://mail.163.com)，进入 **设置 → POP3/SMTP/IMAP**
2. 开启「**SMTP 服务**」
3. 生成并复制 **授权码**

- SMTP 服务器：`smtp.163.com`，端口 `465`
- SMTP 用户名：你的 163 邮箱地址（`xxx@163.com`）

## 二、把代码推到 GitHub 并配置 Secrets

在仓库 **Settings → Secrets and variables → Actions → New repository secret**，添加：

| Secret 名称 | 值 |
|---|---|
| `SMTP_HOST` | `smtp.qq.com` 或 `smtp.163.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | 发件邮箱（如 `xxx@qq.com`） |
| `SMTP_PASSWORD` | SMTP 授权码 |
| `MAIL_TO` | 收件邮箱（可和发件邮箱相同） |

## 三、配置外部定时器（准点触发）

GitHub 自带的 `schedule` 会漂移数小时，因此**用外部定时器准点调用** `workflow_dispatch`。

### 1. 创建细粒度 GitHub Token
- 打开 <https://github.com/settings/tokens?type=beta> → Generate new token
- Repository access：**Only select repositories** → 选本仓库
- Permissions → Repository permissions → **Actions: Read and write**
- 生成后复制 token（`github_pat_...`）

### 2. cron-job.org 建两个任务
登录 <https://cron-job.org> → Create cron job：

- Method：**POST**
- URL：
  ```
  https://api.github.com/repos/<owner>/<repo>/actions/workflows/send-daily-report.yml/dispatches
  ```
- Headers：
  ```
  Authorization: Bearer <github_pat_...>
  Accept: application/vnd.github+json
  Content-Type: application/json
  ```
- Body（JSON）：
  - 上午 09:00（时区选 **Asia/Shanghai**）：`{"ref":"main","inputs":{"kind":"daily"}}`
  - 下午 14:30（时区选 **Asia/Shanghai**）：`{"ref":"main","inputs":{"kind":"updates"}}`

## 四、首次验证

仓库 **Actions** → 「发送 AIHOT 邮件」→ **Run workflow**，`kind` 选 `daily` 或 `updates`，各跑一次确认能收到。

## 五、之后的工作

- 外部定时器每日 09:00 / 14:30 自动触发，无需操作
- 日志里能看到 `OK: AIHOT 日报 ... 已发送到 ...` / `OK: AIHOT 速递 ...`

## 常见问题

- **邮件进了垃圾箱**：把发件邮箱加入白名单。
- **想改时间/条数**：时间改 cron-job.org；下午邮件条数/分数门槛可用环境变量 `UPDATES_SINCE_HOUR`(默认8)、`UPDATES_MIN_SCORE`(默认60)、`UPDATES_LIMIT`(默认15) 调整。
- **本地测一次**：
  ```bash
  REPORT_KIND=daily   python3 send_daily_report.py   # 日报
  REPORT_KIND=updates python3 send_daily_report.py   # 下午新增
  # 不配 SMTP 环境变量时，只打印将发送的内容，不发生信
  ```

## API 速查（AIHOT，匿名只读）

- `GET /api/v1/dailies/latest` — 当天日报
- `GET /api/v1/dailies` — 日报列表（`limit`）
- `GET /api/v1/dailies/{date}` — 指定日期日报
- `GET /api/v1/items` — 实时条目，参数：`window=24h|7d`、`mode=selected|all`、`category=ai-models|ai-products|industry|paper|tip`、`q=`、`by=timeline|published`、`limit`、`cursor`

基址：`https://aihot.virxact.com`

## 安全提醒

- Token 与 SMTP 授权码都是敏感凭据，**只放到 GitHub Secrets / 外部定时器**，不要提交到仓库。
- 外部定时器用的 GitHub Token 请使用**细粒度、仅授权本仓库、仅 Actions 权限**，并设置合适的有效期。

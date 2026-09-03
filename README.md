# 每日 AI 日报自动订阅

早上 9 点（北京时间）自动抓取 [AIHOT](https://aihot.virxact.com/) 官方精编 AI 日报，并通过邮件发送到你邮箱。

- **无需服务器**：定时由 GitHub Actions 云端执行
- **数据源**：AIHOT 官方匿名只读 API `GET /api/v1/dailies/latest`
- **发信**：QQ 邮箱 / 163 邮箱的 SMTP（国内收信最稳）

## 目录结构

```
.
├── .github/workflows/send-daily-report.yml   # 定时工作流（每天 09:00 北京）
├── send_daily_report.py                       # 抓取日报 → 生成 HTML → 发信
└── README.md
```

## 一、准备发件邮箱的 SMTP 授权码

需要开启邮箱的 SMTP 服务并拿到「授权码」（不是登录密码）。

### QQ 邮箱
1. 登录 [mail.qq.com](https://mail.qq.com)，进入 **设置 → 账户**
2. 找到 **POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务**
3. 开启「**SMTP 服务**」，按提示用手机短信验证
4. 生成并复制 **授权码**（16 位字母）

- SMTP 服务器：`smtp.qq.com`，端口 `465`
- SMTP 用户名：你的 QQ 邮箱地址（`xxx@qq.com`）

> 若已有独立授权码且是从 QQ 邮箱客户端生成的，直接用即可；没有就按上面流程生成。

### 163 邮箱
1. 登录 [mail.163.com](https://mail.163.com)，进入 **设置 → POP3/SMTP/IMAP**
2. 开启「**SMTP 服务**」
3. 生成并复制 **授权码**

- SMTP 服务器：`smtp.163.com`，端口 `465`
- SMTP 用户名：你的 163 邮箱地址（`xxx@163.com`）

## 二、把代码推到 GitHub 并配置 Secrets

### 1. 建仓库并推送
```bash
# 在项目目录里执行
git add .
git commit -m "add AI daily report auto-subscription"
git remote add origin <你的仓库地址>
git branch -M main
git push -u origin main
```

### 2. 配置 GitHub Secrets
在仓库页面进入 **Settings → Secrets and variables → Actions → New repository secret**，逐个添加下面 4 个：

| Secret 名称 | 值 |
|---|---|
| `SMTP_HOST` | `smtp.qq.com` 或 `smtp.163.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | 发件邮箱（如 `xxx@qq.com`） |
| `SMTP_PASSWORD` | 第二步拿到的 SMTP 授权码 |
| `MAIL_TO` | 收件邮箱（可和发件邮箱相同） |

## 三、首次验证

在仓库 **Actions** 页面，选「发送 AI 日报邮件」→ **Run workflow**（手动触发一次）。

成功后：
- Actions 运行显示绿色
- 你的邮箱收到一封 AIHOT 日报的 HTML 邮件

## 四、之后的工作

- 每天北京时间 09:00（UTC 01:00）由 cron 自动触发，无需任何操作
- Actions 运行日志里能看到「OK: 日报 … 已发送到 …」

## 常见问题

- **邮件进了垃圾箱**：把发件邮箱加入联系人/白名单，或稍后第 1 封正常后一般不再被拦。
- **不想每天收 / 想改时间**：改 `.github/workflows/send-daily-report.yml` 里 `cron: "0 1 * * *"` 的分钟/小时（UTC），推送到仓库即可。
- **想本地测一次**（确认脚本没问题，需电脑能连外网）：
  ```bash
  python3 send_daily_report.py
  # 不配 SMTP 环境变量时，只打印抓到的日报，不发生信
  ```

## 安全提醒

- Smtp 授权码是敏感凭据，**只放到 GitHub Secrets**，绝不要写死在代码里或提交到仓库。
- 本脚本已从环境变量读取配置，代码内不含任何密码。

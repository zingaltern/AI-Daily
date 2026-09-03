#!/usr/bin/env python3
"""抓取 AIHOT 每日精编日报并通过 SMTP 发邮件。

数据源: https://aihot.virxact.com/api/v1/dailies/latest (匿名只读)
仅在环境变量缺失 SMTP 配置时发送邮件; 否则打印抓取的日报文本。
"""

import html
import os
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from urllib.request import Request, urlopen

DAILY_URL = "https://aihot.virxact.com/api/v1/dailies/latest"
API_BASE = "https://aihot.virxact.com"

SECTION_ICONS = {
    "模型发布/更新": "🚀",
    "产品发布/更新": "🧩",
    "论文研究": "📄",
    "技巧与观点": "💡",
}


def fetch_latest():
    req = Request(DAILY_URL, headers={"User-Agent": "AIHOT-Daily-Sub/1.0"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def esc(text):
    return html.escape(text or "", quote=False)


def build_html(report):
    date = report.get("date", "")
    sections = report.get("sections", [])
    title = f"AIHOT 日报 · {date}"

    rows = []
    for sec in sections:
        label = sec.get("label", "资讯")
        icon = SECTION_ICONS.get(label, "📰")
        items = sec.get("items", [])
        if not items:
            continue
        rows.append(f'<tr><td colspan="2" class="sec">{icon} {esc(label)}</td></tr>')
        for item in items:
            it = item.get("title", "")
            sm = item.get("summary", "")
            src = (item.get("source") or {}).get("name", "")
            links = item.get("links") or {}
            aihot_url = links.get("aihot", "")
            orig_url = links.get("original", "")
            out = ["", ""]
            if aihot_url:
                out[0] = f'<a class="ititle" href="{aihot_url}">{esc(it)}</a>'
            else:
                out[0] = f'<span class="ititle">{esc(it)}</span>'
            if sm:
                out[1] = f'<div class="sum">{esc(sm)}</div>'
            row_extra = []
            if src:
                row_extra.append(f"来源：{esc(src)}")
            if orig_url:
                row_extra.append(f'<a class="orig" href="{orig_url}">阅读原文 →</a>')
            if row_extra:
                out.append('<div class="meta">' + " · ".join(row_extra) + "</div>")
            rows.append('<tr><td colspan="2" class="item">' + "\n".join(out) + "</td></tr>")

    body = "\n".join(rows)
    links = report.get("links") or {}
    web_link = links.get("aihot") or API_BASE
    generated_at = report.get("generatedAt", "")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f5f5f7;">
<div style="max-width:680px;margin:0 auto;padding:24px 16px;font-family:-apple-system,'PingFang SC','Microsoft YaHei',Helvetica,Arial,sans-serif;color:#222;background:#ffffff;">
  <div style="text-align:center;padding:24px 16px;background:#1f2329;border-radius:12px 12px 0 0;">
    <h1 style="margin:0;color:#ffffff;font-size:26px;font-weight:700;">AIHOT 日报</h1>
    <p style="margin:8px 0 0;color:#9aa2ac;font-size:14px;">{esc(date)} · 每日精选 {len(sections)} 大板块</p>
  </div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#ffffff;">
    {body}
  </table>
  <div style="padding:20px 16px;background:#f7f8fa;border-radius:0 0 12px 12px;font-size:12px;color:#8a919c;">
    摘要由 AI 生成，重要数字、政策与原话请点「阅读原文」回原文处核对。
    <br>本条日报于 {esc(generated_at)} 自动生成 ·
    <a href="{web_link}" style="color:#4e7cf7;text-decoration:none;">查看网页版</a>
  </div>
</div>
</body>
</html>"""


def send(title, html_body):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    to_addr = os.environ["MAIL_TO"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = title
    msg["From"] = formataddr(("AIHOT 日报订阅", user))
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as srv:
            srv.login(user, password)
            srv.sendmail(user, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as srv:
            srv.starttls(context=ssl.create_default_context())
            srv.login(user, password)
            srv.sendmail(user, [to_addr], msg.as_string())


def main():
    raw = fetch_latest()
    data = json_loads(raw)
    report = data.get("report") or {}
    date = report.get("date", "")
    title = f"AIHOT 日报 · {date}"

    html_body = build_html(report)

    if all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO")):
        send(title, html_body)
        print(f"OK: 日报 {date} 已发送到 {os.environ['MAIL_TO']}")
    else:
        print("未检测到完整 SMTP 配置，以下为将发送的日报内容：")
        print(title)
        print(html_body[:500])

    return report


def json_loads(text):
    import json
    return json.loads(text)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

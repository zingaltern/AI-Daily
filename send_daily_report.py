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
import time
import uuid
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from urllib.request import Request, urlopen

DAILY_URL = "https://aihot.virxact.com/api/v1/dailies/latest"
API_BASE = "https://aihot.virxact.com"

# 日报以北京时间(UTC+8)标注日期, 且当天报约在北京 08:00 前后才生成
BEIJING = timezone(timedelta(hours=8))
# 在等待窗口内轮询, 直到当天日报出现再发送, 避免发到"尚未更新"时的过期旧报
POLL_SECONDS = 600      # 每 10 分钟检查一次
MAX_WAIT_SECONDS = 5 * 3600  # 最多等 5 小时(须小于 workflow 的 timeout-minutes)

SECTION_META = {
    "模型发布/更新": {"icon": "🚀", "color": "#6366f1", "tint": "rgba(99,102,241,.12)"},
    "产品发布/更新": {"icon": "🧩", "color": "#10b981", "tint": "rgba(16,185,129,.12)"},
    "论文研究": {"icon": "📄", "color": "#f59e0b", "tint": "rgba(245,158,11,.14)"},
    "技巧与观点": {"icon": "💡", "color": "#f43f5e", "tint": "rgba(244,63,94,.12)"},
    "行业动态": {"icon": "🌐", "color": "#0ea5e9", "tint": "rgba(14,165,233,.12)"},
    "综合资讯": {"icon": "🗞️", "color": "#0ea5e9", "tint": "rgba(14,165,233,.12)"},
    "模型": {"icon": "🚀", "color": "#6366f1", "tint": "rgba(99,102,241,.12)"},
    "产品": {"icon": "🧩", "color": "#10b981", "tint": "rgba(16,185,129,.12)"},
    "观点": {"icon": "💡", "color": "#f43f5e", "tint": "rgba(244,63,94,.12)"},
}

WEEK_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def fmt_date_cn(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.year}年{d.month}月{d.day}日 · {WEEK_NAMES[d.weekday()]}"
    except (ValueError, TypeError):
        return date_str


def fetch_latest():
    req = Request(DAILY_URL, headers={"User-Agent": "AIHOT-Daily-Sub/1.0"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def esc(text):
    return html.escape(text or "", quote=False)


def build_html(report):
    date = report.get("date", "")
    sections = report.get("sections", [])
    total_items = sum(len(s.get("items", [])) for s in sections)
    minutes = max(1, round(total_items * 0.6))
    date_cn = fmt_date_cn(date)
    links = report.get("links") or {}
    web_link = links.get("aihot") or API_BASE
    generated_at = report.get("generatedAt", "")

    parts = []
    for sec in sections:
        label = sec.get("label", "资讯")
        meta = SECTION_META.get(label, {"icon": "📰", "color": "#64748b", "tint": "rgba(100,116,139,.12)"})
        items = sec.get("items", [])
        if not items:
            continue
        parts.append(
            f'<tr><td colspan="2" class="section">'
            f'<div class="sec-badge" style="background:{meta["tint"]};color:{meta["color"]}">'
            f'{meta["icon"]}&nbsp;&nbsp;{esc(label)}</div>'
            f'<span class="sec-count" style="color:{meta["color"]}">{len(items)} 篇</span></td></tr>'
        )
        for idx, item in enumerate(items, 1):
            it = item.get("title", "")
            sm = item.get("summary", "")
            src = (item.get("source") or {}).get("name", "")
            links_i = item.get("links") or {}
            aihot_url = links_i.get("aihot", "")
            orig_url = links_i.get("original", "")
            title_html = f'<a class="ititle" href="{aihot_url}">{esc(it)}</a>' if aihot_url else f'<span class="ititle">{esc(it)}</span>'
            summary_html = f'<div class="sum">{esc(sm)}</div>' if sm else ""

            foot_cells = "".join((
                f'<td class="foot-cell"><span class="src">来源 · {esc(src)}</span></td>' if src else "",
                f'<td class="foot-cell"><a class="orig" href="{orig_url}">阅读原文 →</a></td>' if orig_url else "",
            ))
            foot_table = f'<table class="footed"><tr>{foot_cells}</tr></table>' if foot_cells else ""

            parts.append(
                f'<tr class="item"><td class="numcell"><div class="num">{idx:02d}</div></td>'
                f'<td class="bodycell"><div class="ititlewrap">{title_html}</div>{summary_html}{foot_table}'
                f'</td></tr>'
            )

    items_html = "\n".join(parts)

    style_block = """
<style>
  body{margin:0;padding:0;background:#eef1f6;-webkit-font-smoothing:antialiased;}
  .wrap{max-width:680px;margin:0 auto;}
  .hero{background:linear-gradient(135deg,#0f172a 0%,#1e1b4b 55%,#3730a3 100%);padding:34px 32px 30px;color:#fff;text-align:center;}
  .brand{font-size:32px;font-weight:800;letter-spacing:1px;line-height:1.1;}
  .brand span{color:#818cf8;}
  .tag{display:inline-block;margin-top:12px;font-size:11px;letter-spacing:2px;color:#a5b4fc;border:1px solid rgba(165,180,252,.4);border-radius:99px;padding:4px 14px;background:rgba(99,102,241,.14);}
  .date{font-size:15px;margin-top:14px;color:#e0e7ff;}
  .stats{display:inline-block;margin-top:16px;font-size:12px;color:#94a3b8;}
  .stats b{color:#c7d2fe;font-weight:700;}
  .content{background:#ffffff;padding:8px 22px 26px;}
  table{width:100%;border-collapse:collapse;font-family:-apple-system,'PingFang SC','Microsoft YaHei',Helvetica,Arial,sans-serif;}
  .section td{padding:26px 0 10px;}
  .sec-badge{display:inline-block;font-size:15px;font-weight:700;border-radius:8px;padding:6px 14px;}
  .sec-count{float:right;font-size:12px;font-weight:700;line-height:34px;}
  tr.item td{border-top:1px solid #eef1f6;vertical-align:top;padding:16px 0;}
  .numcell{width:44px;text-align:left;padding-right:6px;}
  .num{font-size:20px;font-weight:800;opacity:.5;font-variant-numeric:tabular-nums;}
  .bodycell{font-size:14px;line-height:1.7;}
  .ititlewrap{font-size:16px;font-weight:700;line-height:1.5;margin-bottom:6px;}
  .ititle{color:#0f172a;text-decoration:none;}
  a.ititle:hover{text-decoration:underline;}
  .sum{color:#5b6473;font-size:14px;line-height:1.75;margin:2px 0 8px;}
  .footed{border-collapse:collapse;margin-top:6px;}
  .foot-cell{padding:0 14px 0 0;font-size:12px;vertical-align:middle;}
  .src{color:#9aa2ae;}
  .orig{color:#4e7cf7;text-decoration:none;font-weight:600;white-space:nowrap;}
  a.orig:hover{text-decoration:underline;}
  .footer{background:#0f172a;color:#8290a3;font-size:12px;line-height:1.8;padding:20px 32px;text-align:center;}
  .footer a{color:#a5b4fc;text-decoration:none;}
  .footer .hr{display:block;width:44px;height:3px;background:#3730a3;border-radius:2px;margin:0 auto 12px;}
</style>
"""

    top_stat_line = (
        f'<div class="stats">共 <b>{total_items}</b> 篇报道 · 约 <b>{minutes}</b> 分钟读完</div>'
    )

    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        + style_block + "</head>\n<body>"
        "<div class=\"wrap\">"
        "<div class=\"hero\"><div class=\"brand\">AIHOT <span>日报</span></div>"
        "<div class=\"tag\">DAILY&nbsp;BRIEFING</div>"
        f"<div class=\"date\">{esc(date_cn)}</div>{top_stat_line}</div>"
        "<div class=\"content\"><table role=\"presentation\">" + items_html + "</table></div>"
        f"<div class=\"footer\"><span class=\"hr\"></span>"
        f"本文由 AIHOT 编辑系统生成 · {esc(generated_at)}<br>"
        f"摘要由 AI 生成，重要数字、政策与原话请回原文核对 · "
        f"<a href=\"{web_link}\">前往网页版</a></div>"
        "</div></body></html>"
    )


def make_message_id(user):
    domain = user.split("@")[-1] or "localhost"
    return f"<{uuid.uuid4().hex}@aihot.{domain}>"


def send(title, html_body):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    to_addr = os.environ["MAIL_TO"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = title
    msg["From"] = formataddr(("AIHOT 日报", user))
    msg["Reply-To"] = user
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_message_id(user)
    msg["X-Mailer"] = "AIHOT-Daily-Sub/1.0"
    msg.attach(MIMEText(f"AIHOT 日报 {title}，请打开此邮件查看 HTML 版本。", "plain", "utf-8"))
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


def wait_for_report(target, max_wait=MAX_WAIT_SECONDS, interval=POLL_SECONDS):
    """轮询 dailies/latest, 直到出现日期 >= target 的日报, 或等待超时。

    只接受不早于 target 的报, 从而杜绝发送"当天尚未更新"时的过期旧报。
    """
    deadline = time.time() + max_wait
    while True:
        raw = fetch_latest()
        data = json_loads(raw)
        report = data.get("report") or {}
        date = report.get("date", "")
        if date and date >= target:
            return report
        if time.time() >= deadline:
            return None
        print(f"等待 {target} 日报更新, 当前最新 {date or '(无)'}, {interval}s 后重试...", file=sys.stderr)
        time.sleep(interval)


def main():
    # 目标 = 今天(北京)的日报
    target = datetime.now(BEIJING).strftime("%Y-%m-%d")

    report = wait_for_report(target)
    if report is None:
        print(f"SKIP: 等待窗口内未出现 {target} 的日报, 本次不发送(避免发送过期内容)")
        return None

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

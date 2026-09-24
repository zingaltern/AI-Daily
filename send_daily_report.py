#!/usr/bin/env python3
"""抓取 AIHOT 内容并通过 SMTP 发邮件。

两种模式(由环境变量 REPORT_KIND 选择):
  - daily   : 当天精编日报 (dailies/latest), 上午发
  - updates : 当天"日报之后新增"的高价值实时条目 (items), 下午发

数据源: https://aihot.virxact.com/api/v1 (匿名只读)
未配置完整 SMTP 环境变量时, 只打印将发送的内容, 不发生信。
"""

import html
import json
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

API_BASE = "https://aihot.virxact.com"
DAILY_URL = f"{API_BASE}/api/v1/dailies/latest"
ITEMS_URL = f"{API_BASE}/api/v1/items"

# 数据以北京时间(UTC+8)标注日期, 当天日报约在北京 08:00 前后生成
BEIJING = timezone(timedelta(hours=8))
# 日报在等待窗口内轮询, 直到当天日报出现再发送, 避免发到"尚未更新"时的过期旧报
POLL_SECONDS = 300      # 每 5 分钟检查一次
MAX_WAIT_SECONDS = 2 * 3600  # daily 模式最多等 2 小时(须小于 workflow 的 timeout-minutes)

# updates 模式: 只取"今天这个时刻之后"发布/收录的高价值条目
UPDATES_SINCE_HOUR = int(os.environ.get("UPDATES_SINCE_HOUR", "8"))  # 默认 08:00(北京)
UPDATES_MIN_SCORE = int(os.environ.get("UPDATES_MIN_SCORE", "80"))   # 最低评分
UPDATES_LIMIT = int(os.environ.get("UPDATES_LIMIT", "15"))           # 最多条数
UPDATES_ALLOWED_CATEGORIES = {
    "ai-models", "ai-products", "industry", "paper", "tip",
}

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


def fetch_json(url):
    req = Request(url, headers={"User-Agent": "AIHOT-Daily-Sub/1.0"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_updates(since_hour=UPDATES_SINCE_HOUR, min_score=UPDATES_MIN_SCORE, limit=UPDATES_LIMIT):
    """取"当天 since_hour(北京) 之后发布"的高价值精选条目, 按评分降序。"""
    today = datetime.now(BEIJING).strftime("%Y-%m-%d")
    cutoff = datetime.strptime(f"{today} {since_hour:02d}:00", "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING)

    data = fetch_json(f"{ITEMS_URL}?window=24h&mode=selected&limit=50")
    picked = []
    for it in data.get("items", []):
        if not it.get("selected"):
            continue
        if it.get("category") not in UPDATES_ALLOWED_CATEGORIES:
            continue
        pub = parse_ts(it.get("publishedAt"))
        if not pub or pub.astimezone(BEIJING) < cutoff:
            continue
        if (it.get("score") or 0) < min_score:
            continue
        picked.append(it)

    picked.sort(key=lambda x: (-(x.get("score") or 0), x.get("publishedAt") or ""))
    # 同一事件可能被多家来源报道, 用标题去重
    seen, uniq = set(), []
    for it in picked:
        key = (it.get("title") or "")[:20]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    return uniq[:limit], cutoff


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

    top_stat_line = (
        f'<div class="stats">共 <b>{total_items}</b> 篇报道 · 约 <b>{minutes}</b> 分钟读完</div>'
    )

    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        + STYLE_BLOCK + "</head>\n<body>"
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


CATEGORY_META = {
    "ai-models": {"label": "模型", "icon": "🚀", "color": "#6366f1", "tint": "rgba(99,102,241,.12)"},
    "ai-products": {"label": "产品", "icon": "🧩", "color": "#10b981", "tint": "rgba(16,185,129,.12)"},
    "industry": {"label": "行业", "icon": "🌐", "color": "#0ea5e9", "tint": "rgba(14,165,233,.12)"},
    "paper": {"label": "论文", "icon": "📄", "color": "#f59e0b", "tint": "rgba(245,158,11,.14)"},
    "tip": {"label": "观点", "icon": "💡", "color": "#f43f5e", "tint": "rgba(244,63,94,.12)"},
}


def build_updates_html(items, cutoff):
    """下午"新增"邮件: 列表形式列出当天日报之后的新消息。"""
    today = datetime.now(BEIJING).strftime("%Y-%m-%d")
    date_cn = fmt_date_cn(today)
    since_cn = cutoff.astimezone(BEIJING).strftime("%H:%M")
    now_cn = datetime.now(BEIJING).strftime("%H:%M")

    parts = []
    for idx, item in enumerate(items, 1):
        it = item.get("title", "")
        sm = item.get("summary", "")
        src = (item.get("source") or {}).get("name", "")
        links_i = item.get("links") or {}
        aihot_url = links_i.get("aihot", "")
        orig_url = links_i.get("original", "")
        cat = item.get("category", "")
        meta = CATEGORY_META.get(cat, {"label": "资讯", "icon": "📰", "color": "#64748b", "tint": "rgba(100,116,139,.12)"})
        score = item.get("score")
        pub = parse_ts(item.get("publishedAt"))
        pub_cn = pub.astimezone(BEIJING).strftime("%H:%M") if pub else ""

        title_html = f'<a class="ititle" href="{aihot_url}">{esc(it)}</a>' if aihot_url else f'<span class="ititle">{esc(it)}</span>'
        summary_html = f'<div class="sum">{esc(sm)}</div>' if sm else ""

        tags = "".join((
            f'<span class="pill" style="background:{meta["tint"]};color:{meta["color"]}">{meta["icon"]} {esc(meta["label"])}</span>',
            f'<span class="pill pill-time">{pub_cn}</span>' if pub_cn else "",
            f'<span class="pill pill-time">评分 {score}</span>' if score else "",
        ))
        foot_cells = "".join((
            f'<td class="foot-cell"><span class="src">来源 · {esc(src)}</span></td>' if src else "",
            f'<td class="foot-cell"><a class="orig" href="{orig_url}">阅读原文 →</a></td>' if orig_url else "",
        ))
        foot_table = f'<table class="footed"><tr>{foot_cells}</tr></table>' if foot_cells else ""

        parts.append(
            f'<tr class="item"><td class="numcell"><div class="num">{idx:02d}</div></td>'
            f'<td class="bodycell"><div class="itags">{tags}</div>'
            f'<div class="ititlewrap">{title_html}</div>{summary_html}{foot_table}</td></tr>'
        )
    items_html = "\n".join(parts)

    top_stat_line = f'<div class="stats">新增 <b>{len(items)}</b> 篇精选 · {since_cn}–{now_cn}</div>'

    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        + STYLE_BLOCK + "</head>\n<body>"
        "<div class=\"wrap\">"
        "<div class=\"hero\"><div class=\"brand\">AIHOT <span>速递</span></div>"
        "<div class=\"tag\">LATEST&nbsp;UPDATES</div>"
        f"<div class=\"date\">{esc(date_cn)} · 下午茶</div>{top_stat_line}</div>"
        "<div class=\"content\"><table role=\"presentation\">" + items_html + "</table></div>"
        f"<div class=\"footer\"><span class=\"hr\"></span>"
        f"本邮件汇总 {esc(date_cn)} 日报发布后的新增精选资讯<br>"
        f"摘要由 AI 生成，重要数字、政策与原话请回原文核对 · "
        f"<a href=\"{API_BASE}\">前往网页版</a></div>"
        "</div></body></html>"
    )


STYLE_BLOCK = """
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
  .itags{margin-bottom:6px;}
  .pill{display:inline-block;font-size:11px;font-weight:600;border-radius:99px;padding:2px 9px;margin-right:6px;}
  .pill-time{background:#f1f5f9;color:#64748b;font-weight:500;}
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


def make_message_id(user):
    domain = user.split("@")[-1] or "localhost"
    return f"<{uuid.uuid4().hex}@aihot.{domain}>"


def send(title, html_body, plain_note=None):
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
    note = plain_note or f"{title}，请打开此邮件查看 HTML 版本。"
    msg.attach(MIMEText(note, "plain", "utf-8"))
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
        data = fetch_json(DAILY_URL)
        report = data.get("report") or {}
        date = report.get("date", "")
        if date and date >= target:
            return report
        if time.time() >= deadline:
            return None
        print(f"等待 {target} 日报更新, 当前最新 {date or '(无)'}, {interval}s 后重试...", file=sys.stderr)
        time.sleep(interval)


def smtp_configured():
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"))


def deliver(title, html_body, plain_note):
    if smtp_configured():
        send(title, html_body, plain_note)
        print(f"OK: {title} 已发送到 {os.environ['MAIL_TO']}")
    else:
        print("未检测到完整 SMTP 配置，以下为将发送的内容（预览）：")
        print(title)
        print(html_body[:500])


def run_daily():
    """上午: 当天精编日报。"""
    target = datetime.now(BEIJING).strftime("%Y-%m-%d")
    report = wait_for_report(target)
    if report is None:
        print(f"SKIP: 等待窗口内未出现 {target} 的日报, 本次不发送(避免发送过期内容)")
        return None
    date = report.get("date", "")
    title = f"AIHOT 日报 · {date}"
    deliver(title, build_html(report), f"AIHOT 日报 {title}，请打开此邮件查看 HTML 版本。")
    return report


def run_updates():
    """下午: 当天日报之后的新增精选条目。"""
    items, cutoff = fetch_updates()
    today = datetime.now(BEIJING).strftime("%Y-%m-%d")
    if not items:
        print(f"SKIP: {today} {UPDATES_SINCE_HOUR:02d}:00 之后无达标新增条目, 本次不发送")
        return []
    title = f"AIHOT 速递 · {today} 下午新增精选 ({len(items)} 篇)"
    deliver(title, build_updates_html(items, cutoff),
            f"AIHOT 速递 {today}，当天日报发布后的新增精选资讯，请查看 HTML 版本。")
    return items


def main():
    kind = (os.environ.get("REPORT_KIND") or "daily").strip().lower()
    if kind == "updates":
        return run_updates()
    if kind == "daily":
        return run_daily()
    print(f"ERROR: 未知 REPORT_KIND={kind!r} (应为 'daily' 或 'updates')", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

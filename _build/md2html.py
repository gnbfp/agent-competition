#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal Markdown -> standalone HTML converter (no third-party deps).

Supports: #/##/### headings, paragraphs, - / 1. lists, GFM tables,
> blockquotes, --- rules, **bold**, `code`, [text](url), inline - .
"""
import html
import re
import sys


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def is_table_sep(line: str) -> bool:
    return bool(re.match(r"^\s*\|?[\s:\-|]+\|[\s:\-|]*$", line)) and "-" in line


def split_row(line: str):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def convert(md: str) -> str:
    lines = md.split("\n")
    out = []
    i = 0
    n = len(lines)
    in_ul = in_ol = False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            close_lists()
            i += 1
            continue

        # horizontal rule
        if re.match(r"^(---|\*\*\*|___)\s*$", stripped):
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        # fenced code block
        if stripped.startswith("```"):
            close_lists()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            out.append('<pre class="code"><code>'
                       + html.escape("\n".join(buf), quote=False)
                       + "</code></pre>")
            continue

        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            close_lists()
            level = len(m.group(1))
            text = inline(m.group(2))
            anchor = re.sub(r"[^\w\u4e00-\u9fff]+", "-", m.group(2)).strip("-")
            out.append(f'<h{level} id="{anchor}">{text}</h{level}>')
            i += 1
            continue

        # table
        if stripped.startswith("|") and i + 1 < n and is_table_sep(lines[i + 1]):
            close_lists()
            header = split_row(stripped)
            i += 2
            body = []
            while i < n and lines[i].strip().startswith("|"):
                body.append(split_row(lines[i].strip()))
                i += 1
            out.append('<div class="table-wrap"><table>')
            out.append("<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr></thead>")
            out.append("<tbody>")
            for row in body:
                row = row + [""] * (len(header) - len(row))
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row[: len(header)]) + "</tr>")
            out.append("</tbody></table></div>")
            continue

        # blockquote (consecutive -> one block)
        if stripped.startswith(">"):
            close_lists()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            inner = "<br>".join(inline(b) for b in buf if b)
            out.append(f'<blockquote>{inner}</blockquote>')
            continue

        # task list / bullet list
        m = re.match(r"^[-*]\s+(.*)$", stripped)
        if m:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            i += 1
            continue

        m = re.match(r"^\d+\.\s+(.*)$", stripped)
        if m:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            i += 1
            continue

        # paragraph
        close_lists()
        buf = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(("#", ">", "|", "- ", "* "))
                    or re.match(r"^\d+\.\s", nxt) or re.match(r"^(---|\*\*\*|___)\s*$", nxt)):
                break
            buf.append(nxt)
            i += 1
        out.append("<p>" + "<br>".join(inline(b) for b in buf) + "</p>")

    close_lists()
    return "\n".join(out)


CSS = """
:root{
  --ink:#1b1f24; --ink-soft:#4a545e; --line:#e3e8ef; --bg:#f5f7fa;
  --accent:#0b5fff; --accent-soft:#eaf1ff; --warn:#b45309; --ok:#0a7a45;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:"Microsoft YaHei","PingFang SC","Hiragino Sans GB","Segoe UI",system-ui,sans-serif;
  font-size:16.5px; line-height:1.85; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1000px;margin:0 auto;padding:40px 22px 90px}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;
  box-shadow:0 1px 2px rgba(16,24,40,.04),0 12px 32px -18px rgba(16,24,40,.18);
  padding:52px 56px 60px}
h1{font-size:30px;line-height:1.35;margin:0 0 6px;letter-spacing:-.3px}
h1+blockquote{margin-top:18px}
h2{font-size:22px;margin:52px 0 16px;padding-top:18px;border-top:1px solid var(--line);letter-spacing:-.2px}
h2:first-of-type{border-top:0}
h3{font-size:18.5px;margin:34px 0 12px;color:#0b1b3a}
h3::before{content:"";display:inline-block;width:4px;height:16px;background:var(--accent);
  border-radius:2px;margin-right:10px;vertical-align:-2px}
p{margin:12px 0}
strong{color:#0b1b3a}
a{color:var(--accent);text-decoration:none;border-bottom:1px solid #bcd0ff}
ul,ol{margin:12px 0;padding-left:26px}
li{margin:7px 0}
li::marker{color:var(--accent)}
hr{border:0;border-top:1px dashed var(--line);margin:36px 0}
blockquote{margin:20px 0;padding:16px 20px;background:var(--accent-soft);
  border-left:4px solid var(--accent);border-radius:0 10px 10px 0;color:#123;font-size:15.5px}
blockquote strong{color:var(--accent)}
code{background:#f2f5f9;border:1px solid var(--line);border-radius:5px;
  padding:1.5px 6px;font-family:"Cascadia Mono",Consolas,monospace;font-size:13.5px;color:#0b3d91}
pre.code{overflow-x:auto;margin:18px 0;padding:16px 18px;background:#0b1220;color:#dbe6f6;
  border-radius:10px;font-family:"Cascadia Mono",Consolas,"Courier New",monospace;
  font-size:13px;line-height:1.6;white-space:pre}
pre.code code{background:none;border:0;padding:0;color:inherit;font-size:inherit}
.table-wrap{overflow-x:auto;margin:18px 0;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:14.8px;background:#fff}
thead th{background:#f0f4fa;text-align:left;font-weight:700;color:#0b1b3a;
  padding:11px 14px;border-bottom:1px solid var(--line);white-space:nowrap}
tbody td{padding:11px 14px;border-bottom:1px solid #eef2f7;vertical-align:top;color:var(--ink-soft)}
tbody tr:last-child td{border-bottom:0}
tbody tr:nth-child(even){background:#fafbfd}
tbody tr:hover{background:#f3f7ff}
@media (max-width:720px){
  .card{padding:28px 20px 36px;border-radius:12px}
  .wrap{padding:16px 10px 60px}
  h1{font-size:24px} h2{font-size:19px} body{font-size:15.5px}
}
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="wrap"><article class="card">
{body}
</article></div>
</body>
</html>
"""


def main():
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        md = f.read()
    title = "文档"
    m = re.search(r"^#\s+(.+)$", md, re.M)
    if m:
        title = m.group(1).strip()
    body = convert(md)
    out = TEMPLATE.format(title=html.escape(title), css=CSS, body=body)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print(f"OK {dst} ({len(out)} chars)")


if __name__ == "__main__":
    main()

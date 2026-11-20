#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a formatted DOCX from the project markdown plan."""
import re
import sys

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

INK = RGBColor(0x1B, 0x1F, 0x24)
INK_SOFT = RGBColor(0x4A, 0x54, 0x5E)
ACCENT = RGBColor(0x0B, 0x5F, 0xFF)
DEEP = RGBColor(0x0B, 0x1B, 0x3A)
GRAY = RGBColor(0x6B, 0x74, 0x80)

BODY_CN = "宋体"
BODY_EN = "Times New Roman"
HEAD_CN = "微软雅黑"
MONO = "Consolas"


def set_run(run, name_cn, name_en, size, bold=False, color=None, italic=False):
    run.font.name = name_en
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), name_en)
    rfonts.set(qn("w:hAnsi"), name_en)
    rfonts.set(qn("w:eastAsia"), name_cn)


def shade(paragraph, fill):
    ppr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    ppr.append(shd)


def bottom_border(paragraph, color="D6DEE9", size="8"):
    ppr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), color)
    pbdr.append(bottom)
    ppr.append(pbdr)


def cell_shade(cell, fill):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcpr.append(shd)


def repeat_header(row):
    trpr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trpr.append(el)


def cant_split(row):
    trpr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:cantSplit")
    el.set(qn("w:val"), "true")
    trpr.append(el)


def add_page_number_footer(section):
    para = section.footer.paragraphs[0]
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run()
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    inner = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "1"
    inner.append(t)
    fld.append(inner)
    run._r.addnext(fld)
    for r in para.runs:
        set_run(r, BODY_CN, BODY_EN, 9, color=GRAY)


INLINE = re.compile(r"(\*\*(?:.+?)\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|\*[^*\s][^*]*\*)")


def add_inline(paragraph, text, size=10.5, color=INK, bold=False):
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            run = paragraph.add_run(part[2:-2].replace("`", ""))
            set_run(run, BODY_CN, BODY_EN, size, bold=True, color=DEEP)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            set_run(run, BODY_CN, BODY_EN, size, bold=bold, color=color, italic=True)
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            set_run(run, BODY_CN, MONO, size - 0.5, bold=bold, color=RGBColor(0x0B, 0x3D, 0x91))
        elif part.startswith("[") and "](" in part:
            label, url = part[1:-1].split("](", 1)
            run = paragraph.add_run(f"{label}（{url}）")
            set_run(run, BODY_CN, BODY_EN, size, color=ACCENT, bold=bold)
        else:
            run = paragraph.add_run(part)
            set_run(run, BODY_CN, BODY_EN, size, bold=bold, color=color)


def is_table_sep(line):
    return bool(re.match(r"^\s*\|?[\s:\-|]+\|[\s:\-|]*$", line)) and "-" in line


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def disp_width(text):
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


TOKEN_SPLIT = re.compile(r"[\s\u3000，。、；：（）()｜|/]+")


def set_col_widths(table, header, rows, total_cm=16.4):
    """Width by content, but never narrower than the longest unbreakable token
    (so `activity.schema.json` does not get chopped into `activity.schema.j|son`)."""
    ncols = len(header)
    weights = []
    for c in range(ncols):
        cells = [header[c]] + [r[c] for r in rows if c < len(r)]
        avg = max(disp_width(x) for x in cells)
        token = 0
        for x in cells:
            for tok in TOKEN_SPLIT.split(x):
                token = max(token, disp_width(tok))
        weights.append(max(6, min(token + 1, 22), min(avg, 22)))
    total = float(sum(weights))
    tblpr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblpr.append(layout)
    table.autofit = False

    # total table width
    tbl_w = tblpr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tblpr.append(tbl_w)
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(int(total_cm * 567)))

    # LibreOffice/Word lay out from <w:tblGrid>, not from <w:tcW> — set both
    grid_cols = list(table._tbl.tblGrid.gridCol_lst)
    for i, weight in enumerate(weights):
        width = Cm(total_cm * weight / total)
        twips = int(total_cm * 567 * weight / total)
        if i < len(grid_cols):
            grid_cols[i].set(qn("w:w"), str(twips))
        for cell in table.columns[i].cells:
            cell.width = width


def add_table(doc, header, rows):
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    hdr = table.rows[0]
    repeat_header(hdr)
    cant_split(hdr)
    for i, text in enumerate(header):
        cell = hdr.cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.space_before = Pt(1)
        add_inline(p, text, size=9, bold=True)
        cell_shade(cell, "EAF1FF")
    for row in rows:
        new_row = table.add_row()
        cant_split(new_row)
        cells = new_row.cells
        for i in range(len(header)):
            value = row[i] if i < len(row) else ""
            cell = cells[i]
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.line_spacing = 1.15
            add_inline(p, value, size=9, color=INK_SOFT)
    set_col_widths(table, header, rows)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def build(md_path, out_path):
    with open(md_path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.3)
    section.bottom_margin = Cm(2.3)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

    normal = doc.styles["Normal"]
    normal.font.name = BODY_EN
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_CN)
    pf = normal.paragraph_format
    pf.line_spacing = 1.45
    pf.space_after = Pt(4)

    add_page_number_footer(section)

    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        line = raw.strip()

        if not line:
            i += 1
            continue

        # fenced code
        if line.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            block = "\n".join(buf)
            if "┌" in block:
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after = Pt(6)
                add_inline(p, "**结构**：Agent 主循环（Plan → Act → Observe → Self-check）"
                              "── 调用 ──▶ 8 个工具 ──▶ 状态与可解释报告", size=10.5)
            elif "──→" in block:
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(6)
                add_inline(p, "**依赖链**：P2 数据格式 ──▶ P3 指标计算 ──▶ P4 agent 编排 ──▶ P5 界面展示；"
                              "P1 规则库从旁支撑 P3、P4；P1 计划书与答辩承接 P5 的成品。", size=10.5)
            elif "①" in block or "↓" in block:
                p = doc.add_paragraph()
                pf5 = p.paragraph_format
                pf5.left_indent = Cm(0.5)
                pf5.space_before = Pt(6)
                pf5.space_after = Pt(10)
                pf5.line_spacing = 1.5
                shade(p, "F7FAFF")
                parts = block.split("\n")
                for idx, part in enumerate(parts):
                    run = p.add_run(part)
                    set_run(run, HEAD_CN, HEAD_CN, 9.5, color=INK)
                    if idx < len(parts) - 1:
                        run.add_break()
            else:
                p = doc.add_paragraph()
                pf2 = p.paragraph_format
                pf2.left_indent = Cm(0.3)
                pf2.space_before = Pt(6)
                pf2.space_after = Pt(8)
                pf2.line_spacing = 1.15
                shade(p, "F2F5F9")
                parts = block.split("\n")
                for idx, part in enumerate(parts):
                    run = p.add_run(part)
                    set_run(run, BODY_CN, MONO, 9, color=RGBColor(0x0B, 0x3D, 0x91))
                    if idx < len(parts) - 1:
                        run.add_break()
            continue

        # table
        if line.startswith("|") and i + 1 < n and is_table_sep(lines[i + 1]):
            header = split_row(line)
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i].strip()))
                i += 1
            add_table(doc, header, rows)
            continue

        # horizontal rule -> spacing only
        if re.match(r"^(---|\*\*\*|___)\s*$", line):
            i += 1
            continue

        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip().replace("`", "")
            if level == 1:
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(4)
                run = p.add_run(text)
                set_run(run, HEAD_CN, HEAD_CN, 21, bold=True, color=DEEP)
                bottom_border(p, "0B5FFF", "12")
            elif level == 2:
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(16)
                p.paragraph_format.space_after = Pt(6)
                p.paragraph_format.keep_with_next = True
                run = p.add_run(text)
                set_run(run, HEAD_CN, HEAD_CN, 14.5, bold=True, color=DEEP)
                bottom_border(p, "E3E8EF", "6")
            else:
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(10)
                p.paragraph_format.space_after = Pt(3)
                p.paragraph_format.keep_with_next = True
                run = p.add_run(text)
                set_run(run, HEAD_CN, HEAD_CN, 11.5, bold=True, color=RGBColor(0x0B, 0x1B, 0x3A))
            i += 1
            continue

        # blockquote
        if line.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            for item in buf:
                if not item:
                    continue
                p = doc.add_paragraph()
                pf3 = p.paragraph_format
                pf3.left_indent = Cm(0.5)
                pf3.space_after = Pt(1)
                pf3.line_spacing = 1.3
                add_inline(p, item, size=9.5, color=GRAY)
            continue

        # checklist  - [ ] item  ->  □ item (no bullet char)
        m = re.match(r"^[-*]\s+\[[ xX]\]\s+(.*)$", line)
        if m:
            p = doc.add_paragraph()
            pf5 = p.paragraph_format
            pf5.left_indent = Cm(0.75)
            pf5.first_line_indent = Cm(-0.75)
            pf5.space_after = Pt(2)
            pf5.line_spacing = 1.4
            run = p.add_run("□ ")
            set_run(run, BODY_CN, BODY_EN, 10.5, bold=False, color=ACCENT)
            add_inline(p, m.group(1))
            i += 1
            continue

        # bullets
        m = re.match(r"^[-*]\s+(.*)$", line)
        if m:
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = 1.4
            add_inline(p, m.group(1))
            i += 1
            continue

        # ordered -> literal number, hanging indent
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            p = doc.add_paragraph()
            pf4 = p.paragraph_format
            pf4.left_indent = Cm(0.95)
            pf4.first_line_indent = Cm(-0.95)
            pf4.space_after = Pt(2)
            pf4.line_spacing = 1.4
            run = p.add_run(m.group(1) + ".\u00a0\u00a0")
            set_run(run, BODY_CN, BODY_EN, 10.5, bold=True, color=ACCENT)
            add_inline(p, m.group(2))
            i += 1
            continue

        # paragraph
        buf = [line]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(("#", ">", "|", "```"))
                    or re.match(r"^[-*]\s", nxt) or re.match(r"^\d+\.\s", nxt)
                    or re.match(r"^(---|\*\*\*|___)\s*$", nxt)):
                break
            buf.append(nxt)
            i += 1
        p = doc.add_paragraph()
        add_inline(p, "".join(buf))

    doc.save(out_path)
    print("OK", out_path)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simple Markdown to docx converter using python-docx, tuned for Chinese docs."""
import sys
import re
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls


def set_chinese_font(run, font_name='Microsoft YaHei', size_pt=12, bold=False):
    font = run.font
    font.name = font_name
    font.size = Pt(size_pt)
    font.bold = bold
    run._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)


def parse_inline(text, paragraph):
    """Parse **bold** segments and add runs to paragraph."""
    parts = re.split(r'\*\*(.*?)\*\*', text)
    for i, part in enumerate(parts):
        if not part:
            continue
        run = paragraph.add_run(part)
        set_chinese_font(run, size_pt=11, bold=(i % 2 == 1))


def add_heading(doc, text, level):
    sizes = {1: 18, 2: 15, 3: 13, 4: 12, 5: 11, 6: 11}
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(text)
    set_chinese_font(run, size_pt=sizes.get(level, 11), bold=True)
    # Set outline level via style-like paragraph formatting (best effort)
    p.paragraph_format.space_before = Pt(12 if level <= 2 else 8)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.5
    return p


def add_paragraph(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.first_line_indent = Inches(0.3)
    parse_inline(text, p)
    return p


def add_list_item(doc, text, level, numbered):
    p = doc.add_paragraph(style='List Bullet' if not numbered else 'List Number')
    p.paragraph_format.left_indent = Inches(0.3 + level * 0.25)
    p.paragraph_format.first_line_indent = Inches(-0.2)
    p.paragraph_format.line_spacing = 1.5
    prefix = f"{numbered}. " if type(numbered) is int else "• "
    # Replace style bullet with our own content run to control font
    p.text = ""
    run = p.add_run(prefix + text)
    set_chinese_font(run, size_pt=11)
    return p


def parse_table(lines, start_idx):
    rows = []
    i = start_idx
    while i < len(lines) and lines[i].strip().startswith('|'):
        rows.append(lines[i].strip())
        i += 1
    # Filter separator row
    data_rows = [r for r in rows if not re.match(r'^\|[-:\|\s]+\|$', r.strip())]
    cells = []
    for r in data_rows:
        parts = [c.strip() for c in r.strip('|').split('|')]
        cells.append(parts)
    return cells, i


def add_table(doc, cells):
    if not cells:
        return
    table = doc.add_table(rows=len(cells), cols=len(cells[0]))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = 'Table Grid'
    for ri, row_cells in enumerate(cells):
        row = table.rows[ri]
        for ci, cell_text in enumerate(row_cells):
            if ci >= len(row.cells):
                continue
            cell = row.cells[ci]
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.line_spacing = 1.2
            run = p.add_run(cell_text)
            set_chinese_font(run, size_pt=10, bold=(ri == 0))
            if ri == 0:
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
                # Header shading (light gray) via XML
                shading_elm = parse_xml(r'<w:shd {} w:fill="E8E8E8"/>'.format(nsdecls('w')))
                cell._tc.get_or_add_tcPr().append(shading_elm)
    doc.add_paragraph()  # spacing after table


def convert(md_path, docx_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    doc = Document()
    # Page setup A4
    section = doc.sections[0]
    section.page_height = Inches(11.69)
    section.page_width = Inches(8.27)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)

    i = 0
    in_code = False
    list_stack = []
    while i < len(lines):
        line = lines[i].rstrip('\n')
        stripped = line.strip()

        # Code blocks
        if stripped.startswith('```'):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            p = doc.add_paragraph()
            run = p.add_run(stripped)
            set_chinese_font(run, font_name='JetBrains Mono', size_pt=10)
            i += 1
            continue

        # Empty line
        if not stripped:
            i += 1
            continue

        # Heading
        m = re.match(r'^(#{1,6})\s+(.*)$', stripped)
        if m:
            level = len(m.group(1))
            add_heading(doc, m.group(2).strip(), level)
            i += 1
            continue

        # Table
        if stripped.startswith('|'):
            cells, i = parse_table(lines, i)
            add_table(doc, cells)
            continue

        # List item
        m = re.match(r'^(\s*)(\d+)\.\s+(.*)$', line)
        if m:
            indent = len(m.group(1))
            level = indent // 2
            text = m.group(3).strip()
            add_list_item(doc, text, level, int(m.group(2)))
            i += 1
            continue

        m = re.match(r'^(\s*)[-*]\s+(.*)$', line)
        if m:
            indent = len(m.group(1))
            level = indent // 2
            text = m.group(2).strip()
            add_list_item(doc, text, level, False)
            i += 1
            continue

        # Normal paragraph
        add_paragraph(doc, stripped)
        i += 1

    doc.save(docx_path)
    print(f"Saved: {docx_path}")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 md_to_docx_manual.py input.md output.docx")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])

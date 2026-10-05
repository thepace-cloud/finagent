"""生成《参赛作品文档》正式排版 docx（黑体标题体系 + 宋体正文 + 底纹表头 + 规范图注）

用法: python -X utf8 build_docx.py   （在任意目录运行均可）
输入: 同目录 参赛作品文档.md（内容唯一来源，本脚本只做版式映射，不改一字）
输出: 同目录 参赛作品文档.docx（交稿文件）

样式体系与《参赛作品文档-排版稿.txt》严格一致（样式方案已经用户 10-05 确认）：
  主标题 黑体二号居中 / 赛道 黑体三号 / 一级标题 黑体三号 / 二级 黑体四号 /
  正文 宋体+Times New Roman 小四 1.5 倍行距 首行缩进 2 字符 /
  表格 表头黑体五号+浅灰底纹 表体宋体五号 / 图注 宋体五号居中 / 页码 目录起编。
两个已确认的版式决定：
  ① 图 8a/8b 并排（1×2 无边框表格，各宽 7cm，共用图注）；
  ② gitlog.png 补编号"图 10"（原 md 无编号）。
分节：封面+知产声明 = 第 1 节（无页码）；目录起 = 第 2 节（页码从 1 重排）。
"""
import os
import re

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "参赛作品文档.md")
OUT = os.path.join(HERE, "参赛作品文档.docx")

HEI, SONG, TNR, MONO = "黑体", "宋体", "Times New Roman", "Consolas"
SZ2, SZX2, SZ3, SZ4, SZX4, SZ5, SZX5 = (Pt(22), Pt(18), Pt(16), Pt(14),
                                       Pt(12), Pt(10.5), Pt(9))
CENTER, JUSTIFY, RIGHT = (WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.JUSTIFY,
                          WD_ALIGN_PARAGRAPH.RIGHT)

INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")
IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def fig_no(alt, rel):
    """图号：优先替代文字里的'图 N'，否则按文件名（gitlog→图 10）"""
    m = re.search(r"图\s*(\d+)", alt)
    if m:
        return int(m.group(1))
    if "gitlog" in rel:
        return 10
    raise ValueError(f"无法确定图号: {alt} -> {rel}")

FIG_CAPTION = {
    1: "图 1　主对话界面",
    2: "图 2　引用溯源面板",
    3: "图 3　多产品对比表",
    4: "图 4　拒答红卡",
    5: "图 5　适配测评推荐卡（诚实全拒场景）",
    6: "图 6　运营看板",
    7: "图 7　记忆面板“它记得我”",
    8: "图 8　深色／浅色双主题（左：深色；右：浅色）",
    9: "图 9　系统架构（受控编排）",
    10: "图 10　git 提交历史（原型仓库 24 次＋冲刺仓库 32 次）",
}
FIG_WIDTH = {8: 7.0, 9: 15.0, 10: 14.5}  # cm；未列出 = 手机截图默认 8.0

doc = Document()


# ── 基础工具 ────────────────────────────────────────────────
def setup_page(sec):
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.54)
    sec.left_margin = sec.right_margin = Cm(3.17)


def mk_run(par, text, east=SONG, ascii_=TNR, size=SZX4, bold=False):
    r = par.add_run(text)
    r.font.name = ascii_
    r.font.size = size
    r.font.bold = bold
    r._element.rPr.rFonts.set(qn("w:eastAsia"), east)
    return r


def add_inline(par, text, size=SZX4):
    """行内解析：**粗体**→黑体（西文同黑体以保持强调），`代码`→Consolas"""
    for tok in INLINE.split(text):
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**"):
            mk_run(par, tok[2:-2], east=HEI, ascii_=HEI, size=size)
        elif tok.startswith("`") and tok.endswith("`"):
            mk_run(par, tok[1:-1], east=MONO, ascii_=MONO, size=size)
        else:
            mk_run(par, tok, size=size)


def ind_chars(p, first=None, left=None, hanging=None):
    """以'字符'为单位设置缩进（Word 原生 firstLineChars 等，随字号自适应）"""
    e = p._p.pPr.find(qn("w:ind"))
    if first is not None:
        e.set(qn("w:firstLineChars"), str(first))
    if left is not None:
        e.set(qn("w:leftChars"), str(left))
    if hanging is not None:
        e.set(qn("w:hangingChars"), str(hanging))


def shade(cell, fill="F2F2F2"):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:fill"), fill)
    tcPr.append(sh)


# ── 段落样式 ────────────────────────────────────────────────
def p_center(text, east, ascii_, size, bold=False, before=0, after=0):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.alignment = CENTER
    pf.space_before, pf.space_after, pf.line_spacing = before, after, 1.0
    mk_run(p, text, east=east, ascii_=ascii_, size=size, bold=bold)
    return p


def p_h1(text, brk=False):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(18), Pt(10), 1.3
    pf.keep_with_next = True
    pf.page_break_before = brk
    mk_run(p, text, east=HEI, ascii_=HEI, size=SZ3, bold=True)


def p_h2(text):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(13), Pt(6), 1.3
    pf.keep_with_next = True
    mk_run(p, text, east=HEI, ascii_=HEI, size=SZ4, bold=True)


def p_body(text, keep=False, first=True):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.alignment = JUSTIFY
    pf.line_spacing = 1.5
    pf.space_after = Pt(6)
    pf.keep_with_next = keep
    if first:
        pf.first_line_indent = Pt(24)
        ind_chars(p, first=200)
    add_inline(p, text)


def p_list(text, level=0):
    """悬挂式列表：左缩进 (2+level) 字符、悬挂 2 字符（编号/圆点随文）"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.alignment = JUSTIFY
    pf.line_spacing = 1.5
    pf.space_after = Pt(4)
    pf.left_indent = Pt(12 * (2 + level))
    pf.first_line_indent = Pt(-24)
    ind_chars(p, left=200 + level * 200, hanging=200)
    add_inline(p, text)


def p_caption(text, before=Pt(4), after=Pt(12), keep=False):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.alignment = CENTER
    pf.space_before, pf.space_after = before, after
    pf.line_spacing = 1.0
    pf.keep_with_next = keep
    mk_run(p, text, size=SZ5)


def p_right(text, before=0):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.alignment = RIGHT
    pf.space_before, pf.space_after, pf.line_spacing = before, Pt(6), 1.5
    mk_run(p, text, size=SZ4)


# ── 图 ──────────────────────────────────────────────────────
def figure(rel, no):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.alignment = CENTER
    pf.space_before = Pt(8)
    pf.keep_with_next = True
    p.add_run().add_picture(os.path.join(HERE, rel),
                            width=Cm(FIG_WIDTH.get(no, 8.0)))
    p_caption(FIG_CAPTION[no])


def figure_pair(rels, no):
    """两张竖版截图并排：1×2 无边框表格（已确认的图 8 版式）"""
    t = doc.add_table(rows=1, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for j, rel in enumerate(rels):
        c = t.cell(0, j)
        c.width = Cm(7.3)
        cp = c.paragraphs[0]
        cp.alignment = CENTER
        cp.paragraph_format.space_before = Pt(8)
        cp.add_run().add_picture(os.path.join(HERE, rel), width=Cm(7.0))
    p_caption(FIG_CAPTION[no])


# ── 表 ──────────────────────────────────────────────────────
def cover_table(rows):
    """封面信息：无边框两列表，左列黑体四号、右列宋体四号，均居中"""
    t = doc.add_table(rows=len(rows), cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, (c1, c2) in enumerate(rows):
        cells = t.rows[i].cells
        cells[0].width, cells[1].width = Cm(4.2), Cm(10.4)
        for j, txt in enumerate((c1, c2)):
            cp = cells[j].paragraphs[0]
            cp.alignment = CENTER
            cp.paragraph_format.space_before = Pt(4)
            cp.paragraph_format.space_after = Pt(4)
            if j == 0:
                mk_run(cp, txt, east=HEI, ascii_=HEI, size=SZ4)
            else:
                mk_run(cp, txt, size=SZ4)
        for c in cells:
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def data_table(rows, widths, header=False, first_col_shaded=False, tcap=None):
    """带框线数据表：表头黑体五号+底纹+跨页重复；表体宋体五号"""
    if tcap:
        p_caption(tcap, before=Pt(10), after=Pt(4), keep=True)
    t = doc.add_table(rows=len(rows), cols=2)
    t.style = doc.styles["Table Grid"]
    t.autofit = False
    for i, (c1, c2) in enumerate(rows):
        cells = t.rows[i].cells
        for j, w in enumerate(widths):
            cells[j].width = Cm(w)
        for c in cells:
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p1 = cells[0].paragraphs[0]
        p1.alignment = CENTER
        p2 = cells[1].paragraphs[0]
        if header and i == 0:
            for c in cells:
                shade(c)
            mk_run(p1, c1, east=HEI, ascii_=HEI, size=SZ5)
            p1.runs[-1].font.bold = True
            mk_run(p2, c2, east=HEI, ascii_=HEI, size=SZ5)
            p2.runs[-1].font.bold = True
            p2.alignment = CENTER
            trPr = t.rows[0]._tr.get_or_add_trPr()
            th = OxmlElement("w:tblHeader")
            th.set(qn("w:val"), "true")
            trPr.append(th)
        else:
            if first_col_shaded:
                shade(cells[0])
                mk_run(p1, c1, east=HEI, ascii_=HEI, size=SZ5)
            else:
                mk_run(p1, c1, size=SZ5)
            add_inline(p2, c2, size=SZ5)


# ── 页码（第 2 节起） ───────────────────────────────────────
def footer_page_number(sec):
    sec.footer.is_linked_to_previous = False
    p = sec.footer.paragraphs[0]
    p.alignment = CENTER
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), " PAGE ")
    r = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    rf = OxmlElement("w:rFonts")
    rf.set(qn("w:ascii"), TNR)
    rf.set(qn("w:eastAsia"), SONG)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "18")  # 小五 = 9pt = 18 半磅
    rPr.append(rf)
    rPr.append(sz)
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(rPr)
    r.append(t)
    fld.append(r)
    p._p.append(fld)


# ── 主流程：解析 md → 版式映射 ─────────────────────────────
def main():
    sec1 = doc.sections[0]
    setup_page(sec1)
    normal = doc.styles["Normal"]
    normal.font.name = TNR
    normal.font.size = SZX4
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), SONG)

    lines = open(SRC, encoding="utf-8").read().splitlines()
    n = len(lines)
    toc_mode = False
    first_h1 = True

    def table_rows(i):
        rows = []
        while i < n and lines[i].strip().startswith("|"):
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                rows.append(cells)
            i += 1
        return rows, i

    i = 0
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s or s == ">" or s == "---":
            i += 1
            continue

        # —— 封面区 ——
        if s.startswith("# "):
            p_center(s[2:], HEI, HEI, SZ2, bold=True, before=Pt(48), after=Pt(28))
        elif s.startswith("## 移动互联网"):
            p_center(s[3:], HEI, HEI, SZ3, after=Pt(22))
        elif s.startswith("**【项目名称】"):
            p_center(s[2:-2], HEI, HEI, SZX2, bold=True, after=Pt(10))
        elif s.startswith("（响应式"):
            p_center(s, SONG, TNR, SZ4, after=Pt(36))
        elif s.startswith("## 参赛作品知识产权声明"):
            p = p_center(s[3:], HEI, HEI, SZ3, bold=True,
                         before=Pt(12), after=Pt(16))
            p.paragraph_format.page_break_before = True
        elif s.startswith("## 目录"):
            sec2 = doc.add_section(WD_SECTION_START.NEW_PAGE)
            setup_page(sec2)
            footer_page_number(sec2)
            pg = OxmlElement("w:pgNumType")
            pg.set(qn("w:start"), "1")
            sec2._sectPr.insert_element_before(
                pg, "w:cols", "w:formProt", "w:vAlign", "w:noEndnote",
                "w:titlePg", "w:textDirection", "w:bidi", "w:rtlGutter",
                "w:docGrid", "w:printerSettings")
            p_center("目　　录", HEI, HEI, SZ3, bold=True,
                     before=Pt(12), after=Pt(16))
            toc_mode = True
        elif re.match(r"## [一二三四五六七]、", s):
            p_h1(s[3:], brk=first_h1)
            first_h1 = False
            toc_mode = False
        elif s.startswith("### "):
            p_h2(s[4:])

        # —— 表格 ——
        elif s.startswith("|"):
            rows, i = table_rows(i)
            i -= 1  # 抵消循环末 +1
            if rows[0][1] == "填写":
                cover_table(rows[1:])
            elif rows[0][0] == "功能名称":
                data_table(rows, widths=(3.3, 11.3), header=True,
                           tcap="表 1　功能概述")
            elif rows[0][0] == "所在学校":
                data_table(rows, widths=(4.6, 10.0), first_col_shaded=True,
                           tcap="表 2　团队与分工")

        # —— 原型设计图组（引用块内：说明段 + 图） ——
        elif s.startswith("> "):
            content = s[2:]
            m = IMG.search(content)
            if m:
                no = fig_no(m.group(1), m.group(2))
                # 图 8a/8b 并排：向前看一张，若是同号图则合并
                j = i + 1
                while j < n and lines[j].strip() in ("", ">"):
                    j += 1
                if j < n:
                    m2 = IMG.search(lines[j].strip().lstrip("> "))
                    if m2 and no == 8:
                        figure_pair([m.group(2), m2.group(2)], 8)
                        i = j
                        i += 1
                        continue
                figure(m.group(2), no)
            else:
                p_body(content, keep=True)

        # —— 正文散图（图 9 架构图 / 图 10 gitlog） ——
        elif s.startswith("!["):
            m = IMG.search(s)
            figure(m.group(2), fig_no(m.group(1), m.group(2)))

        # —— 列表 ——
        elif raw.startswith("  ") and re.match(r"\s*\d+\.", raw):
            p_list(re.sub(r"^(\d+)\.\s*", r"\1．", s), level=1)
        elif re.match(r"\d+\.\s", s):
            p_list(re.sub(r"^(\d+)\.\s*", r"\1．", s))
        elif s.startswith("- "):
            p_list("● " + s[2:])
        elif re.match(r"（\d+）", s) and raw != s:
            p_list(s, level=1)

        # —— 目录条目 / 知产签名 / 正文段 ——
        elif toc_mode:
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.line_spacing, pf.space_after = 1.5, Pt(6)
            mk_run(p, s)
        elif s.startswith("作品小组全体成员"):
            p_right(s, before=Pt(36))
        elif s.startswith("日期："):
            p_right(s)
        else:
            p_body(s)
        i += 1

    p_center("（全文完）", SONG, TNR, SZ5, before=Pt(30))

    doc.save(OUT)
    size = os.path.getsize(OUT)
    check = Document(OUT)
    print(f"saved: {OUT}")
    print(f"size={size} bytes  paragraphs={len(check.paragraphs)}  "
          f"tables={len(check.tables)}  images={len(check.inline_shapes)}  "
          f"sections={len(check.sections)}")


if __name__ == "__main__":
    main()

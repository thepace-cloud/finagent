"""渲染特色4佐证图：两个仓库的 git 提交历史（终端风格）

用法: python -X utf8 draw_gitlog.py
输出: gitlog.png（同目录）

为什么用 Pillow 而不是 matplotlib：本项目图9 用 matplotlib 渲染正常，
但本脚本在完整流程中中文始终渲染为缺字形方块（最小实验可复现环境正常，
脚本内字体路由静默失效，原因未定位）。Pillow 直连 FreeType 加载 ttc/ttf，
渲染结果与任何 rcParams 状态无关，一次到位。
数据取自真实 git log，数字与文档正文严格一致（原型仓 24 + 冲刺仓 32 = 56）。
"""
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

REPO_OLD = r"C:\Users\pace\Desktop\python-learning"
REPO_NEW = r"C:\Users\pace\Desktop\finagent"

BG = (12, 12, 12)          # Windows Terminal 底色
FG = (220, 220, 220)
HASH_C = (108, 166, 216)   # hash 蓝
TITLE_C = (22, 198, 12)    # 段标题绿
GRAY = (154, 154, 154)

W, MARGIN, LINE_H, TITLE_H, BAR_H = 2400, 48, 34, 56, 64
HASH_X = MARGIN + 12
MSG_X = MARGIN + 200


def git_oneline(repo, grep=None):
    cmd = ["git", "-C", repo, "log", "--oneline", "--no-color"]
    if grep:
        cmd += [f"--grep={grep}"]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout.strip().splitlines()


FDIR = r"C:\Windows\Fonts"
f_hash = ImageFont.truetype(os.path.join(FDIR, "consola.ttf"), 21)
f_msg = ImageFont.truetype(os.path.join(FDIR, "msyh.ttc"), 21)
f_bar = ImageFont.truetype(os.path.join(FDIR, "msyh.ttc"), 24)
_bd = os.path.join(FDIR, "msyhbd.ttc")
f_title = ImageFont.truetype(_bd if os.path.exists(_bd)
                             else os.path.join(FDIR, "msyh.ttc"), 26)

blocks = [
    ("原型仓库 python-learning/projects/finagent — 24 次提交"
     "（2026-08~09，V1→V5 主线迭代）",
     git_oneline(REPO_OLD, grep="FinAgent")),
    ("冲刺仓库 finagent — 32 次提交"
     "（2026-09-29 起，参赛冲刺：对比/测评/记忆/评测/文档）",
     git_oneline(REPO_NEW)),
]

n = sum(len(t) for _, t in blocks)
H = BAR_H + 30 + n * LINE_H + 2 * (TITLE_H + 26) + MARGIN
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# 终端窗口栏：三个圆点 + 标题
for i, c in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
    x = MARGIN + i * 34
    d.ellipse([x, 22, x + 18, 40], fill=c)
d.text((MARGIN + 140, 18), "git log --oneline  —  两个仓库的提交历史",
       font=f_bar, fill=GRAY)

y = BAR_H + 30
for title, lines in blocks:
    d.text((MARGIN, y), title, font=f_title, fill=TITLE_C)
    y += TITLE_H
    for ln in lines:
        sha, msg = ln.split(" ", 1)
        d.text((HASH_X, y), sha, font=f_hash, fill=HASH_C)
        while (d.textlength(msg, font=f_msg) > W - MSG_X - MARGIN
               and len(msg) > 6):
            msg = msg[:-2]
        d.text((MSG_X, y), msg.rstrip(" ，,;；") + " …"
               if len(msg) < len(ln.split(" ", 1)[1]) else msg,
               font=f_msg, fill=FG)
        y += LINE_H
    y += 26

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gitlog.png")
img.save(out)
print(f"saved: {out}  blocks={[len(t) for _, t in blocks]}  size={img.size}")

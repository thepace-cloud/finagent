import json
import os
import re

CORPUS_DIR = "corpus"
OUTPUT = "chunks.json"

CHUNK_SIZE = 500
OVERLAP = 50


def split_pages(text: str) -> list[tuple[int, str]]:
    """按 [PAGE N] 标记把一页页切开，返回 [(页码, 该页文本)]"""
    pages = []
    cur_page = None
    cur_lines = []

    for line in text.splitlines():
        m = re.match(r"\[PAGE (\d+)\]", line)
        if m:
            # 遇到页标记：先结算上一页，再开新页
            if cur_page is not None:
                pages.append((cur_page, "\n".join(cur_lines)))
            cur_page = int(m.group(1))
            cur_lines = []
        else:
            cur_lines.append(line)

    # 循环结束，补上最后一页
    if cur_page is not None:
        pages.append((cur_page, "\n".join(cur_lines)))

    return pages


def chunk_page(page_text: str, size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[str]:
    """页内分块：先按段落切出天然边界，再逐段凑块，尾块 overlap 进下一块"""
    units = [p for p in re.split(r"\n\s*\n", page_text) if p.strip()]
    chunks = []
    current = ""

    for unit in units:
        if len(current) + len(unit) + 1 <= size:
            current = (current + "\n" + unit).strip()
        else:
            if current:
                chunks.append(current)
            # 新块带着上一块尾巴（overlap）开头，保上下文连续
            current = (current[-overlap:] + "\n" + unit).strip() if current and overlap else unit

    if current:
        chunks.append(current)
    return chunks


def main():
    all_chunks = []

    for filename in sorted(os.listdir(CORPUS_DIR)):
        if not filename.endswith(".txt"):
            continue
        company = filename.replace(".txt", "")
        text = open(os.path.join(CORPUS_DIR, filename), encoding="utf-8").read()

        idx = 0
        file_pages = set()
        for page, page_text in split_pages(text):
            file_pages.add(page)
            for chunk in chunk_page(page_text):
                all_chunks.append({
                    "company": company,
                    "chunk_id": f"{company}_{idx}",
                    "page": page,
                    "text": chunk,
                })
                idx += 1

        print(f"{company}: {idx} 块, 跨页 {sorted(file_pages)}")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    print(f"\n总共 {len(all_chunks)} 块，已写入 {OUTPUT}")


if __name__ == "__main__":
    main()

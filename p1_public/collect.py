"""Download official source snapshots; HTML has paragraph locators, not fake pages."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
URLS = [
    ("national_student", "200806/t20080626_727.html"),
    ("commercial_student", "200806/t20080626_728.html"),
    ("overseas_student", "200907/t20090723_784900.html"),
    ("suixin", "202409/t20240929_25163938.html"),
    ("e_loan", "201602/t20160229_6465863.html"),
    ("unsecured", "202409/t20240929_25163936.html"),
    ("mortgage_consumer", "202409/t20240929_25163935.html"),
    ("pledge_consumer", "202409/t20240929_25163937.html"),
    ("auto", "200806/t20080625_714.html"),
    ("commercial_property", "200806/t20080626_730.html"),
    ("provident", "200806/t20080626_729.html"),
    ("first_home", "200806/t20080625_723.html"),
]


class Article(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif "sub_con" in attrs.get("class", ""):
                self.depth = 1
        if self.depth and tag in ("p", "br", "tr", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.depth and tag in ("p", "tr", "li"):
            self.parts.append("\n")
        if tag == "div" and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


def download(item):
    doc_id, path = item
    url = "https://www.boc.cn/pbservice/pb2/" + path
    cache = ROOT / "raw" / f"{doc_id}.html"
    raw = cache.read_bytes() if cache.exists() else urlopen(url, timeout=40).read()
    html = raw.decode("utf-8")
    parser = Article()
    parser.feed(html)
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 8:
        raise ValueError(f"Extraction too short: {doc_id}")
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1).strip()
    (ROOT / "raw" / f"{doc_id}.html").write_bytes(raw)
    (ROOT / "raw" / f"{doc_id}.txt").write_text("\n".join(lines), encoding="utf-8")
    meta = {"id": doc_id, "title": title, "source_url": url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "published_at": None, "url_archive_date": path.split("t")[1][:8],
            "date_note": "URL date is an archive hint, not a verified publication/update date.",
            "sha256": sha256(raw).hexdigest(), "page": None,
            "locator_type": "HTML paragraph; no physical page number"}
    return meta, [{"id": f"{doc_id}:p{i}", "doc_id": doc_id, "title": title,
                   "text": line, "source_url": url, "page": None,
                   "locator": f"paragraph {i}"} for i, line in enumerate(lines, 1)]


if __name__ == "__main__":
    (ROOT / "raw").mkdir(parents=True, exist_ok=True)
    results = list(ThreadPoolExecutor(max_workers=4).map(download, URLS))
    (ROOT / "sources.json").write_text(json.dumps([r[0] for r in results], ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "passages.json").write_text(json.dumps([p for r in results for p in r[1]], ensure_ascii=False, indent=2), encoding="utf-8")
    for meta, passages in results:
        print(meta["id"], len(passages), meta["title"], flush=True)

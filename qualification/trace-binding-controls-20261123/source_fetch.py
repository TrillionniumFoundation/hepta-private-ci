"""Read the two registered Stack Overflow pages into a private working directory."""
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class Prose(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.exclude = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("pre", "script", "style"):
            self.exclude += 1
        if not self.exclude and tag in ("p", "li", "div", "br", "blockquote"):
            self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in ("pre", "script", "style"):
            self.exclude = max(0, self.exclude-1)
        if not self.exclude and tag in ("p", "li", "div", "blockquote"):
            self.parts.append("\n")
    def handle_data(self, data):
        if not self.exclude:
            self.parts.append(data)
    def paragraphs(self):
        return [" ".join(p.split()) for p in "".join(self.parts).splitlines() if p.strip()]


def fetch(root):
    root.mkdir(exist_ok=False)
    pages, seen = [], {}
    for title in ("multiples","divisible"):
        args=dict(order="asc", sort="creation", intitle=title, tagged="python",
                  site="stackoverflow", todate=1767225599, pagesize=30, page=1, filter="withbody")
        url="https://api.stackexchange.com/2.3/search?" + urlencode(args)
        with urlopen(Request(url,headers={"User-Agent":"Hepta-research-public-readback/1.0"}),timeout=20) as r:
            raw=r.read()
        if raw.startswith(b"\x1f\x8b"):
            raw=gzip.decompress(raw)
        (root/(title+"-raw.json")).write_bytes(raw)
        obj=json.loads(raw)
        if len(obj["items"]) > 30:
            raise ValueError("unexpected page size")
        pages.append(dict(url=url, sha256=sha256(raw).hexdigest(),has_more=obj["has_more"],
                          time=datetime.now(timezone.utc).isoformat(),
                          ids=[i["question_id"] for i in obj["items"]]))
        for item in obj["items"]:
            parser=Prose()
            parser.feed(item["body"])
            seen[item["question_id"]]=dict(id=item["question_id"],title=item["title"],url=item["link"],
                owner=item["owner"].get("display_name","deleted user"),license=item.get("content_license"),
                body_sha256=sha256(item["body"].encode()).hexdigest(), paragraphs=parser.paragraphs())
        if "backoff" in obj:
            time.sleep(obj["backoff"])
    (root/"pages.json").write_text(json.dumps(pages,indent=2))
    (root/"private.json").write_text(json.dumps(seen,ensure_ascii=False))


if __name__=="__main__":
    fetch(Path(sys.argv[1]))

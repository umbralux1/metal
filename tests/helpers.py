import json
import re
from html.parser import HTMLParser


class PageInfo(HTMLParser):
    """Достаёт из HTML то, что важно для SEO: title, canonical, robots, H1, JSON-LD."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.title = ""
        self.canonical: str | None = None
        self.robots: str | None = None
        self.description: str | None = None
        self.h1: list[str] = []
        self.jsonld: list[dict] = []
        self._in: str | None = None
        self._buf = ""
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        elif tag == "meta" and a.get("name") == "robots":
            self.robots = a.get("content")
        elif tag == "meta" and a.get("name") == "description":
            self.description = a.get("content")
        elif tag in ("title", "h1") or (tag == "script" and a.get("type") == "application/ld+json"):
            self._in, self._buf = tag, ""

    def handle_data(self, data):
        if self._in:
            self._buf += data

    def handle_endtag(self, tag):
        if tag != self._in:
            return
        if tag == "title":
            self.title = self._buf.strip()
        elif tag == "h1":
            self.h1.append(re.sub(r"\s+", " ", self._buf).strip())
        elif tag == "script":
            self.jsonld.append(json.loads(self._buf))
        self._in = None

    def jsonld_types(self) -> set[str]:
        return {block["@type"] for block in self.jsonld}

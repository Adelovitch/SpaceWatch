#!/usr/bin/env python3
"""Collecter des liens d'actualités spatiales depuis les flux officiels."""
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "articles.json"
FEEDS = [
    ("NASA", "https://www.nasa.gov/news-release/feed/"),
    ("NASA Images", "https://www.nasa.gov/feeds/iotd-feed/"),
    ("ESA", "https://www.esa.int/rssfeed/Our_Activities/Space_News"),
    ("ESA Science", "https://www.esa.int/rssfeed/Our_Activities/Space_Science"),
]
ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"

class Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)

def clean(text):
    parser = Stripper()
    parser.feed(text or "")
    return re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()[:360]

def childtext(node, *tags):
    for tag in tags:
        child = node.find(tag)
        if child is not None and child.text:
            return child.text.strip()
    return ""

def iso(value):
    if not value:
        return ""
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()

def parse(payload, source):
    root = ET.fromstring(payload)
    atom = root.tag == ATOM + "feed"
    entries = root.findall(ATOM + "entry") if atom else root.findall("./channel/item")
    articles = []
    for node in entries:
        title = clean(childtext(node, "title", ATOM + "title"))
        url = childtext(node, "link")
        if atom:
            for link in node.findall(ATOM + "link"):
                if link.get("rel", "alternate") == "alternate" and link.get("href", "").startswith("https://"):
                    url = link.get("href")
                    break
        if not title or not url.startswith("https://"):
            continue
        published = iso(childtext(node, "pubDate", ATOM + "published", ATOM + "updated", DC + "date"))
        summary = clean(childtext(node, "description", ATOM + "summary", ATOM + "content"))
        articles.append(dict(title=title, url=url, source=source, summary=summary, published=published))
    return articles

def main():
    articles, states = [], []
    for name, url in FEEDS:
        try:
            request = Request(url, headers={"User-Agent": "SpaceWatch/0.1 RSS reader"})
            with urlopen(request, timeout=25) as response:
                payload = response.read(3_000_000)
            found = parse(payload, name)
            articles += found
            states.append(dict(source=name, status="ok", count=len(found)))
        except Exception as exc:
            states.append(dict(source=name, status="error", detail=str(exc)[:180]))
    unique = {}
    for article in articles:
        unique.setdefault(article["url"].split("#")[0].rstrip("/"), article)
    articles = sorted(unique.values(), key=lambda a: a["published"], reverse=True)[:120]
    print(json.dumps({"articles": len(articles), "sources": states}))
    if not articles:
        raise SystemExit("Aucun article reçu — données précédentes conservées")
    OUT.parent.mkdir(exist_ok=True, parents=True)
    OUT.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "articles": articles, "sources": states}, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Collecter des liens d'actualités spatiales depuis les flux officiels."""
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin
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
MEDIA = "{http://search.yahoo.com/mrss/}"

class Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)

def clean(text, limit=900):
    parser = Stripper()
    parser.feed(text or "")
    return re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()[:limit]

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

class ImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "img":
            values = dict(attrs)
            self.images.append(values.get("src", "") or values.get("data-src", ""))

def safe_image(url):
    parsed = urlparse(url or "")
    return url if parsed.scheme == "https" and parsed.netloc and not parsed.username else ""

def image_from_entry(node):
    for tag in ("enclosure", MEDIA + "content", MEDIA + "thumbnail"):
        for element in node.findall(tag):
            url = safe_image(element.get("url", ""))
            if url and (tag != "enclosure" or element.get("type", "").startswith("image/")):
                return url
    raw = childtext(node, "description", ATOM + "content", "{http://purl.org/rss/1.0/modules/content/}encoded")
    parser = ImageParser()
    parser.feed(raw)
    return next((u for item in parser.images if (u := safe_image(item))), "")

class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image = ""
        self.description = ""
    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return
        data = dict(attrs)
        key = (data.get("property") or data.get("name") or "").lower()
        if key in ("og:image", "twitter:image") and not self.image:
            self.image = data.get("content", "")
        if key in ("og:description", "description") and not self.description:
            self.description = clean(data.get("content", ""))

class ArticleTextParser(HTMLParser):
    """Extract readable introductory paragraphs, excluding navigation and scripts."""
    def __init__(self):
        super().__init__()
        self.stack = []
        self.parts = []
        self.current = []
        self.in_paragraph = False
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.stack.append(tag)
        if tag in ("script", "style", "nav", "footer", "header", "aside"):
            self.blocked += 1
        if tag == "p" and not self.blocked:
            self.in_paragraph = True
            self.current = []

    def handle_data(self, text):
        if self.in_paragraph and not self.blocked:
            self.current.append(text)

    def handle_endtag(self, tag):
        if tag == "p" and self.in_paragraph:
            paragraph = re.sub(r"\s+", " ", unescape(" ".join(self.current))).strip()
            if 70 <= len(paragraph) <= 1200:
                self.parts.append(paragraph)
            self.in_paragraph = False
            self.current = []
        if tag in ("script", "style", "nav", "footer", "header", "aside"):
            self.blocked = max(0, self.blocked - 1)
        if self.stack:
            self.stack.pop()

def richer_description(page, fallback):
    parser = ArticleTextParser()
    parser.feed(page)
    # Prefer informative opening paragraphs; do not replicate the whole article.
    chunks = []
    for paragraph in parser.parts:
        if paragraph in fallback or paragraph.lower().startswith(("subscribe", "sign up", "cookies", "share this")):
            continue
        chunks.append(paragraph)
        if len(" ".join(chunks)) >= 530 or len(chunks) >= 2:
            break
    enriched = clean(" ".join(chunks), limit=700)
    return enriched if len(enriched) >= 160 and len(enriched) > len(fallback) else fallback

def enrich(article):
    # Metadata from the original publisher only, with a short timeout.
    try:
        req = Request(article["url"], headers={"User-Agent": "Mozilla/5.0 (compatible; SpaceWatch/0.2)"})
        with urlopen(req, timeout=7) as response:
            page = response.read(350_000).decode("utf-8", errors="replace")
        parser = MetadataParser()
        parser.feed(page)
        if not article.get("image"):
            article["image"] = safe_image(urljoin(article["url"], parser.image)) if parser.image else ""
        if parser.description and not ("APOD Science APOD" in parser.description or "Archive Submissions Index" in parser.description or "Today’s APOD Archive" in parser.description) and (
            article.get("summary", "").startswith("APOD Science APOD")
            or not article.get("summary")
        ):
            article["summary"] = parser.description
        article["summary"] = richer_description(page, article.get("summary", ""))
    except Exception:
        pass
    if not article.get("summary") and "APOD:" in article.get("title", ""):
        article["summary"] = "NASA Astronomy Picture of the Day — " + article["title"].split("–")[-1].strip() + ". Read the original NASA page for the scientific explanation."
    return article

def parse(payload, source):
    root = ET.fromstring(payload)
    atom = root.tag == ATOM + "feed"
    entries = root.findall(ATOM + "entry") if atom else root.findall("./channel/item")
    articles = []
    for node in entries:
        title = clean(childtext(node, "title", ATOM + "title"), limit=180)
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
        if "APOD Science APOD" in summary or "Archive Submissions Index" in summary or "Today’s APOD Archive" in summary:
            summary = ""
        articles.append(dict(title=title, url=url, source=source, summary=summary, published=published, image=image_from_entry(node)))
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
    # Prioritize visible articles; cap requests to protect the update schedule.
    for article in articles[:18]:
        enrich(article)
    print(json.dumps({"articles": len(articles), "sources": states}))
    if not articles:
        raise SystemExit("Aucun article reçu — données précédentes conservées")
    OUT.parent.mkdir(exist_ok=True, parents=True)
    OUT.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "articles": articles, "sources": states}, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()

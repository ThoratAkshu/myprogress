"""A deliberately small, safe text format for learning articles.

Everything is HTML-escaped first; only a fixed set of tags is added back:
headings (#, ##, ###) with link anchors, ``` or ~~~ fenced code blocks, inline code, **bold**, *italic*,
~~strikethrough~~, "- " and "1. " lists, "> " quotes and "> [!TIP]" callouts, "---" dividers,
paragraphs, [text](https://...) links, auto-linked http(s) URLs, and ![alt](...) images that
were uploaded to this site. No author-supplied markup reaches the page.
"""
import re
from html import escape
from django.conf import settings
from django.utils.safestring import mark_safe
URL_PATTERN = re.compile(r"https?://[^\s<]+[^\s<.,;:!?)\]'\"]")
MARKDOWN_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
HEADING_PATTERN = re.compile(r"^(#{1,3})\s+(.+)$")
LIST_PATTERN = re.compile(r"^\s*[-*]\s+(.+)$")
ORDERED_PATTERN = re.compile(r"^\s*\d{1,3}[.)]\s+(.+)$")
QUOTE_PATTERN = re.compile(r"^\s*>\s?(.*)$")
CALLOUT_PATTERN = re.compile(r"^\[!(note|tip|warning)\]\s*$", re.IGNORECASE)
DIVIDER_PATTERN = re.compile(r"^\s*(-{3,}|\*{3,})\s*$")
IMAGE_PATTERN = re.compile(r"^\s*!\[([^\]\n]{0,200})\]\(([^\s)]+)\)\s*$")
LANGUAGE_PATTERN = re.compile(r"^[A-Za-z0-9+#.-]{1,20}$")
ITALIC_PATTERN = re.compile(r"(?<![*\w])\*(?![\s*])([^*\n]+?)(?<!\s)\*(?![*\w])")
STRIKE_PATTERN = re.compile(r"~~(?!\s)(.+?)(?<!\s)~~")
CALLOUT_TITLES = {"note": "Note", "tip": "Tip", "warning": "Warning"}
def _link(href, label):
    return f'<a href="{href}" rel="nofollow noopener" target="_blank">{label}</a>'
def _text(raw, autolink=True):
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escape(raw))
    text = STRIKE_PATTERN.sub(r"<del>\1</del>", ITALIC_PATTERN.sub(r"<em>\1</em>", text))
    return URL_PATTERN.sub(lambda match: _link(match.group(0), match.group(0)), text) if autolink else text
def _inline(raw):
    pieces = []
    for index, part in enumerate(re.split(r"`([^`\n]+)`", raw)):
        if index % 2:
            pieces.append(f"<code>{escape(part)}</code>")
            continue
        position = 0
        for match in MARKDOWN_LINK.finditer(part):
            pieces.append(_text(part[position:match.start()]))
            pieces.append(_link(escape(match.group(2)), _text(match.group(1), autolink=False)))
            position = match.end()
        pieces.append(_text(part[position:]))
    return "".join(pieces)
def _slug(text, used):
    base = re.sub(r"[^a-z0-9]+", "-", re.sub(r"[`*~\[\]()]", "", text).lower()).strip("-")[:60] or "section"
    slug, number = base, 2
    while slug in used:
        slug, number = f"{base}-{number}", number + 1
    used.add(slug)
    return slug
def _uploaded_image(url):
    """Only images uploaded to this site's article image folder may be shown."""
    prefix = f"{settings.MEDIA_URL.rstrip('/')}/learning/images/"
    return url.startswith(prefix) and re.fullmatch(r"[A-Za-z0-9_./-]+\.(png|jpe?g|gif|webp)", url[len(prefix):], re.IGNORECASE) and ".." not in url
def article_outline(source):
    """The article's headings as (level, text, anchor), matching the anchors render_article adds."""
    used, outline, fence = set(), [], None
    for line in (source or "").replace("\r\n", "\n").split("\n"):
        marker = line.strip()[:3]
        if marker in ("```", "~~~") and fence in (None, marker):
            fence = None if fence else marker
        elif not fence and HEADING_PATTERN.match(line):
            hashes, text = HEADING_PATTERN.match(line).groups()
            outline.append({"level": len(hashes) + 1, "text": re.sub(r"[`*~]", "", text).strip(), "anchor": _slug(text, used)})
    return outline
def render_article(source):
    lines = (source or "").replace("\r\n", "\n").split("\n")
    blocks, paragraph, items, quote, used = [], [], [], [], set()
    list_tag = ["ul"]
    def flush():
        if paragraph:
            blocks.append("<p>" + "<br>".join(_inline(line) for line in paragraph) + "</p>")
            paragraph.clear()
        if items:
            blocks.append(f"<{list_tag[0]}>" + "".join(f"<li>{_inline(item)}</li>" for item in items) + f"</{list_tag[0]}>")
            items.clear()
        if quote:
            kind = CALLOUT_PATTERN.match(quote[0].strip())
            if kind:
                name = kind.group(1).lower()
                inner = render_article("\n".join(quote[1:]))
                blocks.append(f'<aside class="callout callout-{name}"><b class="callout-title">{CALLOUT_TITLES[name]}</b>{inner}</aside>')
            else:
                blocks.append(f"<blockquote>{render_article(chr(10).join(quote))}</blockquote>")
            quote.clear()
    def add_item(tag, text):
        if paragraph or quote or (items and list_tag[0] != tag):
            flush()
        list_tag[0] = tag
        items.append(text)
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip().startswith(("```", "~~~")):
            flush()
            fence, language = line.strip()[:3], line.strip()[3:].strip()
            code = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                code.append(lines[index])
                index += 1
            css = f' class="language-{escape(language.lower())}"' if LANGUAGE_PATTERN.match(language) else ""
            blocks.append(f"<pre><code{css}>{escape(chr(10).join(code))}</code></pre>")
        elif HEADING_PATTERN.match(line):
            flush()
            hashes, text = HEADING_PATTERN.match(line).groups()
            level = len(hashes) + 1
            blocks.append(f'<h{level} id="{_slug(text, used)}">{_inline(text)}</h{level}>')
        elif QUOTE_PATTERN.match(line):
            if paragraph or items:
                flush()
            quote.append(QUOTE_PATTERN.match(line).group(1))
        elif DIVIDER_PATTERN.match(line):
            flush()
            blocks.append("<hr>")
        elif IMAGE_PATTERN.match(line) and _uploaded_image(IMAGE_PATTERN.match(line).group(2)):
            flush()
            alt, url = IMAGE_PATTERN.match(line).groups()
            caption = f"<figcaption>{escape(alt)}</figcaption>" if alt.strip() else ""
            blocks.append(f'<figure><img src="{escape(url)}" alt="{escape(alt)}" loading="lazy">{caption}</figure>')
        elif LIST_PATTERN.match(line):
            add_item("ul", LIST_PATTERN.match(line).group(1))
        elif ORDERED_PATTERN.match(line):
            add_item("ol", ORDERED_PATTERN.match(line).group(1))
        elif not line.strip():
            flush()
        else:
            if items or quote:
                flush()
            paragraph.append(line)
        index += 1
    flush()
    return mark_safe("\n".join(blocks))

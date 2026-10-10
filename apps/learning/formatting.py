"""A deliberately small, safe text format for learning articles.

Everything is HTML-escaped first; only a fixed set of tags is added back:
headings (#, ##, ###), fenced code blocks, inline code, **bold**, "- " lists,
paragraphs, [text](https://...) links, and auto-linked http(s) URLs.
No author-supplied markup reaches the page.
"""
import re
from html import escape
from django.utils.safestring import mark_safe
URL_PATTERN = re.compile(r"https?://[^\s<]+[^\s<.,;:!?)\]'\"]")
MARKDOWN_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
HEADING_PATTERN = re.compile(r"^(#{1,3})\s+(.+)$")
LIST_PATTERN = re.compile(r"^\s*[-*]\s+(.+)$")
LANGUAGE_PATTERN = re.compile(r"^[A-Za-z0-9+#.-]{1,20}$")
def _link(href, label):
    return f'<a href="{href}" rel="nofollow noopener" target="_blank">{label}</a>'
def _text(raw, autolink=True):
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escape(raw))
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
def render_article(source):
    lines = (source or "").replace("\r\n", "\n").split("\n")
    blocks, paragraph, items = [], [], []
    def flush():
        if paragraph:
            blocks.append("<p>" + "<br>".join(_inline(line) for line in paragraph) + "</p>")
            paragraph.clear()
        if items:
            blocks.append("<ul>" + "".join(f"<li>{_inline(item)}</li>" for item in items) + "</ul>")
            items.clear()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip().startswith("```"):
            flush()
            language = line.strip()[3:].strip()
            code = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            css = f' class="language-{escape(language.lower())}"' if LANGUAGE_PATTERN.match(language) else ""
            blocks.append(f"<pre><code{css}>{escape(chr(10).join(code))}</code></pre>")
        elif HEADING_PATTERN.match(line):
            flush()
            hashes, text = HEADING_PATTERN.match(line).groups()
            level = len(hashes) + 1
            blocks.append(f"<h{level}>{_inline(text)}</h{level}>")
        elif LIST_PATTERN.match(line):
            if paragraph:
                flush()
            items.append(LIST_PATTERN.match(line).group(1))
        elif not line.strip():
            flush()
        else:
            if items:
                flush()
            paragraph.append(line)
        index += 1
    flush()
    return mark_safe("\n".join(blocks))

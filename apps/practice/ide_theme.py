"""The developer UI's dark theme, generated from the app's own stylesheets.

The stylesheets set many light colours directly (white cards, pale badges, dark text). Rather than restyle every page
by hand, build() reads them in the order pages load them and writes a matching rule for each light background, dark
text and light border, scoped to body.ide: white panels become editor panels, tints become a soft glow of the same hue,
dark text turns light. Run `manage.py build_ide_css` after changing a stylesheet; a test checks the file is current."""
import colorsys
import re
from pathlib import Path
from django.conf import settings

CSS = Path(settings.BASE_DIR) / "apps/landing/static/landing/css"
OUTPUT = CSS / "ide-auto.css"
# The order app_base.html loads them, then page-specific sheets, then the ones loaded last.
FIRST = ["style.css", "analytics.css", "git-hub.css", "portfolio.css", "recruiting.css", "learning.css"]
LAST = ["legacy-readability.css", "app.css", "themes.css", "practice.css"]
# site.css: the signed-out pages, which never use the developer UI. mode-switch.css: the same colours in both views.
SKIP = {"site.css", "ide.css", "ide-auto.css", "mode-switch.css"}

COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\bwhite\b|\bblack\b|rgba?\([^)]*\)")


def sources():
    rest = sorted(path.name for path in CSS.glob("*.css") if path.name not in SKIP and path.name not in FIRST + LAST)
    return [CSS / name for name in FIRST + rest + LAST if (CSS / name).exists()]


def strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def matching(text, start):
    """Index of the } closing the { at start, skipping strings."""
    depth, index, quote = 0, start, None
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return len(text) - 1


def parse(text):
    """Rules as (selector, body) and @media/@supports blocks as (prelude, [rules]); other at-rules are left out."""
    items, index = [], 0
    while True:
        brace = text.find("{", index)
        if brace == -1:
            return items
        prelude = text[index:brace].strip()
        if ";" in prelude and prelude.startswith("@"):  # @import and friends before the block
            prelude = prelude[prelude.rfind(";") + 1:].strip()
        end = matching(text, brace)
        body = text[brace + 1:end]
        if prelude.startswith("@media") or prelude.startswith("@supports"):
            items.append((prelude, parse(body)))
        elif not prelude.startswith("@"):
            items.append((prelude, body))
        index = end + 1


def rgb(token):
    token = token.lower()
    if token == "white":
        return 255, 255, 255, 1.0
    if token == "black":
        return 0, 0, 0, 1.0
    if token.startswith("#"):
        digits = token[1:]
        if len(digits) in (3, 4):
            digits = "".join(char * 2 for char in digits)
        alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), alpha
    parts = [part.strip() for part in token[token.index("(") + 1:-1].replace("/", ",").split(",")]
    values = [float(part[:-1]) * 2.55 if part.endswith("%") else float(part) for part in parts[:3]]
    alpha = float(parts[3][:-1]) / 100 if len(parts) > 3 and parts[3].endswith("%") else float(parts[3]) if len(parts) > 3 else 1.0
    return int(values[0]), int(values[1]), int(values[2]), alpha


def describe(token):
    red, green, blue, alpha = rgb(token)
    hue, light, sat = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
    neutral = sat < 0.2 or max(red, green, blue) - min(red, green, blue) < 22
    return round(hue * 360), light, sat, alpha, neutral


def background(token):
    hue, light, sat, alpha, neutral = describe(token)
    if alpha < 0.5:
        return None  # overlays and glows are already meant to sit on anything
    if neutral:
        if light >= 0.95:
            return "var(--ide-panel)"
        if light >= 0.86:
            return "var(--ide-panel-2)"
        if light >= 0.74:
            return "var(--ide-line-2)"
        return None
    if light >= 0.84:
        return f"hsla({hue},70%,60%,.13)"
    if light >= 0.7:
        return f"hsla({hue},65%,58%,.22)"
    return None


def text_color(token):
    hue, light, sat, alpha, neutral = describe(token)
    if neutral:
        if light < 0.26:
            return "var(--ide-ink)"
        if light < 0.56:
            return "var(--ide-muted)"
        return None
    if light < 0.5:
        return f"hsl({hue},{min(90, round(sat * 100) + 10)}%,72%)"
    return None


def border(token):
    hue, light, sat, alpha, neutral = describe(token)
    if light < 0.74 or alpha < 0.5:
        return None
    return "var(--ide-line)" if neutral else f"hsla({hue},60%,55%,.35)"


MANAGED = {"background", "background-color", "color", "border", "border-top", "border-right", "border-bottom", "border-left", "border-color",
           "border-top-color", "border-right-color", "border-bottom-color", "border-left-color"}


def light_gradient(value):
    """A gradient of only light colours (a pale card or badge) becomes a panel, or a soft glow of its hue."""
    if "url(" in value:
        return None
    tokens = COLOR.findall(value)
    stops = [describe(token) for token in tokens]
    looks = [(0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255 for red, green, blue, _ in map(rgb, tokens)]  # how light it looks
    if not stops or "var(" in value or any(seen < 0.8 or alpha < 0.5 for seen, (_, _, _, alpha, _) in zip(looks, stops)):
        return None
    tinted = [hue for hue, _, _, _, neutral in stops if not neutral]
    return f"hsla({tinted[0]},70%,60%,.16)" if tinted else "var(--ide-panel-2)"


def convert(prop, value, rule_color=None):
    """The dark version of one declaration's value, or None to leave it alone."""
    important = "!important" if "!important" in value else ""
    value = value.replace("!important", "").strip()
    if prop in ("background", "background-color") and "gradient" in value:
        new = light_gradient(value)
        return f"{new}{' !important' if important else ''}" if new else None
    if prop in ("background", "background-color") and ("var(--violet" in value or value.startswith("var(--ink)")) and rule_color in ("#fff", "#ffffff", "white"):
        return f"var(--ide-accent-strong){' !important' if important else ''}"  # the accent is a light blue here, too pale under white text
    if "gradient" in value or "url(" in value or "var(" in value:
        return None
    if prop in ("background", "background-color"):
        tokens = COLOR.findall(value)
        if len(tokens) != 1 or value.replace(tokens[0], "").strip():
            return None  # only a plain colour
        new = background(tokens[0])
    elif prop == "color":
        tokens = COLOR.findall(value)
        new = text_color(tokens[0]) if len(tokens) == 1 and value == tokens[0] else None
    elif prop.startswith("border") and ("color" in prop or prop in ("border", "border-top", "border-right", "border-bottom", "border-left")):
        changed = False

        def swap(match):
            nonlocal changed
            replacement = border(match.group(0))
            changed = changed or replacement is not None
            return replacement or match.group(0)
        new = COLOR.sub(swap, value)
        new = new if changed else None
    else:
        return None
    return f"{new}{' !important' if important else ''}" if new else None


def scope(selector):
    selector = selector.strip()
    if selector.startswith(":root") or selector.startswith("html") or ".ide" in selector:
        return None
    if selector.startswith("body"):
        return re.sub(r"^body", "body.ide", selector, count=1)
    if selector.startswith(".theme-"):
        return f"body.ide{selector}"
    return f"body.ide {selector}"


def declarations(body):
    for part in re.split(r";(?![^(]*\))", body):
        if ":" in part:
            prop, value = part.split(":", 1)
            yield prop.strip().lower(), value.strip()


def rules(items):
    out = []
    for prelude, content in items:
        if isinstance(content, list):
            inner = rules(content)
            if inner:
                out.append(f"{prelude}{{{''.join(inner)}}}")
            continue
        # Every colour declaration is copied, converted or not: scoping makes these rules more specific than the
        # originals, so the copies must keep their order among themselves, or an untouched .button.primary would lose
        # to a converted .button.
        found = list(declarations(content))
        color = next((value.replace("!important", "").strip().lower() for prop, value in found if prop == "color"), None)
        kept = [(prop, convert(prop, value, color), value) for prop, value in found if prop in MANAGED]
        selectors = [scoped for scoped in (scope(item) for item in re.split(r",(?![^(]*\))", prelude)) if scoped]
        if selectors and any(new for _, new, _ in kept):
            out.append(f"{','.join(selectors)}{{{';'.join(f'{prop}:{new or value}' for prop, new, value in kept)}}}\n")
        elif selectors and kept:
            out.append(f"{','.join(selectors)}{{{';'.join(f'{prop}:{value}' for prop, _, value in kept)}}}\n")
    return out


def build():
    parts = ["/* Generated by `manage.py build_ide_css` from the stylesheets below. Don't edit by hand. */\n"]
    for path in sources():
        generated = rules(parse(strip_comments(path.read_text(encoding="utf8"))))
        if generated:
            parts.append(f"/* {path.name} */\n" + "".join(generated))
    return "".join(parts)

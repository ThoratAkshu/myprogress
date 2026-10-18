from django import template

register = template.Library()


@register.filter
def letter(number):
    """1 → A, 2 → B: the label in front of each choice."""
    try:
        return "ABCDEFGH"[int(number) - 1]
    except (ValueError, IndexError):
        return ""


@register.filter
def item(collection, key):
    """collection[key] for a dict or a list, or "" if it isn't there."""
    try:
        return collection[key]
    except (KeyError, IndexError, TypeError):
        return ""

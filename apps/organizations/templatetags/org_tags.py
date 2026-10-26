from django import template
register = template.Library()
@register.filter
def get_item(mapping, key):
    """Look up a dictionary value by key in a template."""
    return (mapping or {}).get(key)
@register.filter
def rupees(amount):
    """A fee with Indian digit grouping: 1200000 → ₹12,00,000."""
    if amount in (None, ""):
        return ""
    digits = str(int(amount))
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail])

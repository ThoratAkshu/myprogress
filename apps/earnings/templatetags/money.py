from django import template
from apps.earnings.services import rupees
register = template.Library()
@register.filter
def inr(amount):
    """₹1,250 or ₹12.50."""
    return rupees(amount)
@register.filter
def ordinal(number):
    """1st, 2nd, 3rd, 21st."""
    number = int(number)
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"

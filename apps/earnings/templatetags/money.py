from django import template
from apps.earnings.services import rupees
register = template.Library()
@register.filter
def inr(amount):
    """₹1,250 or ₹12.50."""
    return rupees(amount)

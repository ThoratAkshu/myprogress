from django import template
from apps.learning.formatting import render_article
from apps.learning.media import youtube_embed_url
register = template.Library()
@register.filter
def article(value):
    return render_article(value)
@register.filter
def youtube_embed(value):
    return youtube_embed_url(value)

from django.contrib import admin
from .models import ContactRequest, PortfolioView, Shortlist, ShortlistEntry
admin.site.register(Shortlist)
admin.site.register(ShortlistEntry)
admin.site.register(ContactRequest)
admin.site.register(PortfolioView)

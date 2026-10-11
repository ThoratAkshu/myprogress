from django.urls import path
from .views import audit_view, creator_detail_view, creators_view, finance_login_view, finance_logout_view, overview_view, payout_paid_view, payout_reject_view, payouts_csv_view, payouts_view, settings_view, treasury_view
app_name = "finance"
urlpatterns = [
    path("", overview_view, name="overview"),
    path("login/", finance_login_view, name="login"),
    path("logout/", finance_logout_view, name="logout"),
    path("payouts/", payouts_view, name="payouts"),
    path("payouts/pending.csv", payouts_csv_view, name="payouts_csv"),
    path("payouts/<int:payout_id>/paid/", payout_paid_view, name="payout_paid"),
    path("payouts/<int:payout_id>/reject/", payout_reject_view, name="payout_reject"),
    path("treasury/", treasury_view, name="treasury"),
    path("rules/", settings_view, name="settings"),
    path("creators/", creators_view, name="creators"),
    path("creators/<int:user_id>/", creator_detail_view, name="creator"),
    path("audit/", audit_view, name="audit"),
]

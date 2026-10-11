from django.urls import path
from .views import audit_view, close_month_view, creator_detail_view, creators_view, finance_login_view, finance_logout_view, overview_view, payout_paid_view, payout_reject_view, payouts_csv_view, payouts_view, prepare_run_view, razorpayx_webhook_view, send_run_view, settings_view, sync_payments_view, treasury_view
app_name = "finance"
urlpatterns = [
    path("", overview_view, name="overview"),
    path("login/", finance_login_view, name="login"),
    path("logout/", finance_logout_view, name="logout"),
    path("payments/", payouts_view, name="payouts"),
    path("payments/close-month/", close_month_view, name="close_month"),
    path("payments/check/", sync_payments_view, name="sync_payments"),
    path("payments/runs/<int:run_id>/prepare/", prepare_run_view, name="prepare_run"),
    path("payments/runs/<int:run_id>/send/", send_run_view, name="send_run"),
    path("payments/runs/<int:run_id>/payments.csv", payouts_csv_view, name="payouts_csv"),
    path("payments/<int:payout_id>/paid/", payout_paid_view, name="payout_paid"),
    path("payments/<int:payout_id>/return/", payout_reject_view, name="payout_reject"),
    path("webhooks/razorpayx/", razorpayx_webhook_view, name="razorpayx_webhook"),
    path("treasury/", treasury_view, name="treasury"),
    path("rules/", settings_view, name="settings"),
    path("creators/", creators_view, name="creators"),
    path("creators/<int:user_id>/", creator_detail_view, name="creator"),
    path("audit/", audit_view, name="audit"),
]

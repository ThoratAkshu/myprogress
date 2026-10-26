from django.urls import path
from .views import state_view, blob_view, collaborators_view, leave_view, transfer_view, commit_view, issue_comment_view, issue_create_view, issue_detail_view, issue_list_view, issue_state_view, pull_create_view, pull_merge_view, raw_view
app_name = "code"
urlpatterns = [
    path("state/", state_view, name="state"),
    path("blob/", blob_view, name="blob"),
    path("raw/", raw_view, name="raw"),
    path("commits/<str:sha>/", commit_view, name="commit"),
    path("issues/", issue_list_view, {"kind": "issue"}, name="issues"),
    path("issues/new/", issue_create_view, name="issue_create"),
    path("issues/<int:number>/", issue_detail_view, name="issue"),
    path("issues/<int:number>/comment/", issue_comment_view, name="issue_comment"),
    path("issues/<int:number>/state/", issue_state_view, name="issue_state"),
    path("pulls/", issue_list_view, {"kind": "pull"}, name="pulls"),
    path("pulls/new/", pull_create_view, name="pull_create"),
    path("pulls/<int:number>/", issue_detail_view, name="pull"),
    path("pulls/<int:number>/merge/", pull_merge_view, name="pull_merge"),
    path("collaborators/", collaborators_view, name="collaborators"),
    path("leave/", leave_view, name="leave"),
    path("transfer/", transfer_view, name="transfer"),
]

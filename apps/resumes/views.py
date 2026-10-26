"""Your resume, for students and professionals, and a candidate's resume, for recruiters and organizations hiring."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from apps.accounts.decorators import role_required
from apps.accounts.models import Profile
from apps.recruiting.models import PortfolioView
from . import services
from .forms import ResumeSettingsForm
@login_required(login_url="landing:home")
def my_resume_view(request):
    """Choices on the left, the resume on the right. Ticking a box saves at once and redraws the resume (resume.js);
    the Save button saves the text fields."""
    owner = request.user
    Profile.objects.get_or_create(user=owner)
    resume = services.build_resume(owner, owner, request.build_absolute_uri)
    form = ResumeSettingsForm(request.POST or None, instance=services.settings_for(owner), projects=list(owner.projects.order_by("-updated_at")), generated_summary=resume["generated_summary"])
    if request.method == "POST" and form.is_valid():
        form.save()
        if request.headers.get("X-Requested-With") == "fetch":
            return render(request, "resumes/_sheet.html", {"resume": services.build_resume(owner, owner, request.build_absolute_uri)})
        messages.success(request, "Resume saved.")
        return redirect("resumes:mine")
    return render(request, "resumes/mine.html", {"form": form, "resume": resume}, status=400 if form.errors else 200)
@role_required("recruiter", "organization")
def candidate_resume_view(request, handle):
    """A candidate's resume from their public work. It counts as a view of their profile, as opening it would."""
    profile = get_object_or_404(Profile.objects.select_related("user"), handle=handle)
    if not services.recruiter_can_see(profile.user, request.user):
        raise Http404
    try:
        PortfolioView.objects.get_or_create(profile=profile, viewer=request.user, viewed_on=timezone.localdate(), defaults={"viewer_role": request.user.profile.role})
    except IntegrityError:
        pass
    return render(request, "resumes/candidate.html", {"resume": services.build_resume(profile.user, request.user, request.build_absolute_uri), "candidate": profile})

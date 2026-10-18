"""Who someone is, asked when they sign up and editable in their channel settings.

Students and working professionals say which they are, and where they study or what they do. Recruiters name the
company they hire for and sign up with its email, so the people they contact know who's asking. Organizations say
what kind they are and what they teach; that becomes their institute."""
from datetime import date
from urllib.parse import urlsplit
from django import forms
from .models import FREE_EMAIL_DOMAINS, Profile

# Throwaway inboxes: an account on one can't be recovered, and nobody can tell who's behind it.
DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "sharklasers.com", "10minutemail.com", "tempmail.com", "temp-mail.org",
    "tempmail.dev", "yopmail.com", "trashmail.com", "getnada.com", "dispostable.com", "maildrop.cc", "mintemail.com", "throwawaymail.com",
    "fakeinbox.com", "mailnesia.com", "emailondeck.com", "moakt.com", "tempr.email", "discard.email", "spamgourmet.com",
}
PERSONAL_EMAIL_DOMAINS = FREE_EMAIL_DOMAINS | {
    "outlook.in", "hotmail.co.uk", "hotmail.in", "live.in", "yahoo.co.uk", "yahoo.in", "rocketmail.com", "pm.me", "tutanota.com",
    "gmx.de", "gmx.net", "mail.ru", "qq.com", "163.com", "126.com", "web.de", "inbox.com",
}


def domain_of(email):
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def host_of(url):
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_company(email_domain, host):
    """An email at acme.com fits acme.com, careers.acme.com, and the other way round (mail.acme.com)."""
    return bool(email_domain and host) and (email_domain == host or email_domain.endswith(f".{host}") or host.endswith(f".{email_domain}"))


def email_problem(email, role):
    """Why this address can't be used for this kind of account, or ""."""
    domain = domain_of(email)
    if domain in DISPOSABLE_EMAIL_DOMAINS:
        return f"{domain} addresses are temporary. Use an email you'll keep, so you can always get back into your account."
    if role == "recruiter" and domain in PERSONAL_EMAIL_DOMAINS:
        return f"Recruiters sign up with their work email, so the people they contact know which company is asking. {domain} is a personal email provider."
    return ""


def add_fields(form, role):
    """The questions for this kind of account. They're optional to the form; check() decides what's required."""
    if role in {"developer", "any"}:
        form.fields["occupation"] = forms.ChoiceField(choices=Profile.OCCUPATIONS, required=False, widget=forms.RadioSelect, label="You are")
        form.fields["institution"] = forms.CharField(max_length=120, required=False, label="College or school", widget=forms.TextInput(attrs={"placeholder": "Pune University"}))
        form.fields["graduation_year"] = forms.IntegerField(min_value=1950, max_value=date.today().year + 8, required=False, label="Graduation year")
    if role in {"developer", "recruiter", "any"}:
        form.fields["job_title"] = forms.CharField(max_length=100, required=False, label="Job title", widget=forms.TextInput(attrs={"placeholder": "Backend developer" if role == "developer" else "Talent acquisition lead"}))
        form.fields["company_name"] = forms.CharField(max_length=120, required=False, label="Company", widget=forms.TextInput(attrs={"placeholder": "Acme Technologies"}))
    if role in {"recruiter", "any"}:
        form.fields["company_website"] = forms.URLField(max_length=200, required=False, assume_scheme="https", label="Company website", widget=forms.URLInput(attrs={"placeholder": "https://acme.com"}))


def check(form, role, email):
    """Add errors for what this kind of account still has to say, and return the profile values to save (the
    answers that don't apply to them are cleared)."""
    data = form.cleaned_data
    values = {"occupation": "", "institution": "", "graduation_year": None, "job_title": "", "company_name": "", "company_website": ""}
    text = lambda name: " ".join((data.get(name) or "").split())
    if role == "developer":
        occupation = data.get("occupation") or ""
        if occupation == "student":
            values.update(occupation=occupation, institution=text("institution"), graduation_year=data.get("graduation_year"))
            if not values["institution"]:
                form.add_error("institution", "Tell us your college or school.")
        elif occupation == "professional":
            values.update(occupation=occupation, job_title=text("job_title"), company_name=text("company_name"))
            if not values["job_title"]:
                form.add_error("job_title", "Tell us what you do, like Backend developer or Data analyst.")
        else:
            form.add_error("occupation", "Choose whether you're a student or a working professional.")
    elif role == "recruiter":
        values.update(job_title=text("job_title"), company_name=text("company_name"), company_website=data.get("company_website") or "")
        if not values["company_name"]:
            form.add_error("company_name", "Name the company you hire for.")
        domain = domain_of(email)
        if values["company_website"] and domain not in PERSONAL_EMAIL_DOMAINS and not same_company(domain, host_of(values["company_website"])):
            form.add_error("company_website", f"Your email is at {domain}, so the company website should be on {domain} too. Leave it empty if the company uses another site.")
    return values


def headline(role, values):
    """A first headline from what they told us, like LinkedIn's "Student at …"; they can change it any time."""
    if role == "developer" and values["occupation"] == "student":
        text = f"Student at {values['institution']}"
    elif role == "developer":
        text = f"{values['job_title']} at {values['company_name']}" if values["company_name"] else values["job_title"]
    elif role == "recruiter":
        text = f"{values['job_title'] or 'Recruiter'} at {values['company_name']}"
    else:
        text = ""
    return text[:160]

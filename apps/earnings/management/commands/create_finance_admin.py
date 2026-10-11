from getpass import getpass
from django.contrib.auth.models import Permission, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from apps.earnings.services import log
class Command(BaseCommand):
    help = "Give an account access to the finance console at /finance/ (creates the account if it doesn't exist)."
    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--revoke", action="store_true", help="Remove finance access instead")
    def handle(self, email, revoke=False, **options):
        email = email.strip().lower()
        permission = Permission.objects.get(codename="access_finance", content_type__app_label="earnings")
        user = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).first()
        if revoke:
            if not user:
                raise CommandError(f"No account uses {email}.")
            user.user_permissions.remove(permission)
            log(None, "access_revoked", f"Finance access removed from {email} from the command line")
            self.stdout.write(self.style.SUCCESS(f"{email} can no longer use the finance console."))
            return
        if not user:
            password = getpass(f"Password for the new account {email}: ")
            if password != getpass("Repeat the password: "):
                raise CommandError("The passwords don't match.")
            try:
                validate_password(password)
            except ValidationError as error:
                raise CommandError(" ".join(error.messages))
            user = User.objects.create_user(username=email, email=email, password=password)
            self.stdout.write(f"Created the account {email}.")
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        user.user_permissions.add(permission)
        log(None, "access_granted", f"Finance access given to {email} from the command line")
        self.stdout.write(self.style.SUCCESS(f"{email} can now sign in at /finance/login/."))

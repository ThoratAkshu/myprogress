import secrets
from django.db import migrations, models
from django.utils.text import slugify
def assign_handles(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    taken = set(Profile.objects.exclude(handle__isnull=True).values_list("handle", flat=True))
    for profile in Profile.objects.select_related("user").filter(handle__isnull=True):
        base = slugify(f"{profile.user.first_name} {profile.user.last_name}")[:32].strip("-") or f"developer-{secrets.token_hex(3)}"
        handle = base
        counter = 2
        while handle in taken:
            handle = f"{base}-{counter}"
            counter += 1
        taken.add(handle)
        profile.handle = handle
        profile.save(update_fields=["handle"])
class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_follow")]
    operations = [
        migrations.AddField(model_name="profile", name="handle", field=models.SlugField(blank=True, help_text="Public portfolio address: /u/<handle>/", max_length=40, null=True, unique=True)),
        migrations.RunPython(assign_handles, migrations.RunPython.noop),
    ]

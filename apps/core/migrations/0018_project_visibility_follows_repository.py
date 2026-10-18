from django.db import migrations


def align(apps, schema_editor):
    """A project and its code now share one visibility. Until now they were set apart (projects started public,
    repositories private), so each project takes its repository's: the side that was chosen on purpose, and the
    one that keeps private code private."""
    Project = apps.get_model("core", "Project")
    Repository = apps.get_model("core", "Repository")
    for visibility in ("public", "private"):
        project_ids = Repository.objects.filter(visibility=visibility).values("project_id")
        Project.objects.filter(pk__in=project_ids).update(is_public=visibility == "public")


class Migration(migrations.Migration):
    dependencies = [("core", "0017_repository_company_and_more")]
    operations = [migrations.RunPython(align, migrations.RunPython.noop)]

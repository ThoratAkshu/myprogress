from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [("core", "0004_git_hosting")]
    operations = [migrations.AddField(model_name="repository", name="languages", field=models.JSONField(blank=True, default=dict, help_text="Bytes of code per language on the default branch"))]

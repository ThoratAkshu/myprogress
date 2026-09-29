from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.AddField(model_name="learningpost", name="earnings", field=models.DecimalField(decimal_places=2, default=0, max_digits=10)), migrations.AddField(model_name="learningpost", name="thumbnail", field=models.ImageField(blank=True, upload_to="learning/")), migrations.AddField(model_name="learningpost", name="video_url", field=models.URLField(blank=True)), migrations.AddField(model_name="learningpost", name="views", field=models.PositiveIntegerField(default=0))]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0082_announcement'),
    ]

    operations = [
        migrations.AddField(
            model_name='practicetestattempt',
            name='annotations',
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name='practicetestattempt',
            name='break_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

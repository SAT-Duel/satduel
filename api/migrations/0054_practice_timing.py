from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0053_drop_legacy_stat_columns'),
    ]

    operations = [
        migrations.AddField(
            model_name='practicestats',
            name='active_question_served_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='practiceattempt',
            name='time_taken',
            field=models.FloatField(blank=True, null=True),
        ),
    ]

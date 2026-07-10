# Step 1 of 3 (practice stats split): create the per-subject stats table.
# 0052 seeds it from the legacy columns; 0053 drops those columns.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0050_practiceattempt_subject'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PracticeStats',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject', models.CharField(choices=[('english', 'English'), ('math', 'Math')], max_length=10)),
                ('elo', models.IntegerField(default=1200)),
                ('answered', models.IntegerField(default=0)),
                ('correct', models.IntegerField(default=0)),
                ('active_question', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='api.question')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='practice_stats', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name='practicestats',
            constraint=models.UniqueConstraint(fields=('user', 'subject'), name='unique_practice_stats_per_subject'),
        ),
    ]

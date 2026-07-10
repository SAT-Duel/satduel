# Step 3 of 3 (practice stats split): drop the legacy columns that 0052
# migrated into PracticeStats, and tighten UserStatistics to one row per user
# (0052 merged the duplicates that the old plain ForeignKey allowed).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0052_seed_practicestats'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='practiceattempt',
            new_name='api_practic_user_id_91adbf_idx',
            old_name='api_practic_user_id_9678a4_idx',
        ),
        migrations.RemoveField(model_name='profile', name='active_math_question'),
        migrations.RemoveField(model_name='profile', name='active_practice_question'),
        migrations.RemoveField(model_name='profile', name='math_elo_rating'),
        migrations.RemoveField(model_name='profile', name='problems_solved'),
        migrations.RemoveField(model_name='profile', name='sp_elo_rating'),
        migrations.RemoveField(model_name='userstatistics', name='correct_number'),
        migrations.RemoveField(model_name='userstatistics', name='current_streak'),
        migrations.RemoveField(model_name='userstatistics', name='incorrect_number'),
        migrations.RemoveField(model_name='userstatistics', name='last_login_date'),
        migrations.RemoveField(model_name='userstatistics', name='login_streak'),
        migrations.AlterField(
            model_name='userstatistics',
            name='user',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='infinitequestionstatistics', to=settings.AUTH_USER_MODEL),
        ),
    ]

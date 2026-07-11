from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def move_active_questions_to_lanes(apps, schema_editor):
    PracticeActiveQuestion = apps.get_model('api', 'PracticeActiveQuestion')
    PracticeStats = apps.get_model('api', 'PracticeStats')
    rows = [
        PracticeActiveQuestion(
            user_id=stats.user_id,
            lane=f'{stats.subject}:any',
            question_id=stats.active_question_id,
        )
        for stats in PracticeStats.objects.exclude(active_question_id=None)
    ]
    PracticeActiveQuestion.objects.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api', '0054_practice_timing'),
    ]

    operations = [
        migrations.CreateModel(
            name='PracticeActiveQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lane', models.CharField(max_length=128)),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='api.question')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='practice_active_questions', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name='practiceactivequestion',
            constraint=models.UniqueConstraint(fields=('user', 'lane'), name='unique_active_question_per_lane'),
        ),
        migrations.RunPython(move_active_questions_to_lanes, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='practicestats',
            name='active_question',
        ),
        migrations.RemoveField(
            model_name='practicestats',
            name='active_question_served_at',
        ),
        migrations.RemoveField(
            model_name='practiceattempt',
            name='time_taken',
        ),
    ]

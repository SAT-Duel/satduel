# Rebuild practice progress from the PracticeAttempt log.
#
# 1. Seed PracticeTypeStats: per (user, question_type), how many DISTINCT
#    questions the user attempted and how many of those they got right.
# 2. Reset PracticeStats.answered/correct to the attempt-log counts. Users
#    whose early activity predates the attempt log (migration 0052 folded
#    those legacy totals into their English row) lose that untracked head
#    start on purpose — counters restart from real, per-question history.
#    Elo is untouched.

from django.db import migrations
from django.db.models import Count, Q


def backfill(apps, schema_editor):
    PracticeAttempt = apps.get_model('api', 'PracticeAttempt')
    PracticeStats = apps.get_model('api', 'PracticeStats')
    PracticeTypeStats = apps.get_model('api', 'PracticeTypeStats')

    # --- Per-type progress ---------------------------------------------
    PracticeTypeStats.objects.all().delete()
    type_rows = (
        PracticeAttempt.objects
        .exclude(question__question_type__isnull=True)
        .exclude(question__question_type='')
        .values('user_id', 'question__question_type')
        .annotate(
            solved=Count('question_id', distinct=True),
            correct=Count('question_id', filter=Q(correct=True), distinct=True),
        )
    )
    PracticeTypeStats.objects.bulk_create(
        [
            PracticeTypeStats(
                user_id=row['user_id'],
                question_type=row['question__question_type'],
                solved=row['solved'],
                correct=row['correct'],
            )
            for row in type_rows
        ],
        batch_size=500,
    )

    # --- Per-subject lifetime counters ---------------------------------
    PracticeStats.objects.update(answered=0, correct=0)
    subject_rows = (
        PracticeAttempt.objects
        .values('user_id', 'subject')
        .annotate(
            answered=Count('id'),
            correct=Count('id', filter=Q(correct=True)),
        )
    )
    for row in subject_rows:
        PracticeStats.objects.update_or_create(
            user_id=row['user_id'],
            subject=row['subject'],
            defaults={'answered': row['answered'], 'correct': row['correct']},
        )


def noop(apps, schema_editor):
    # The old inflated counters are gone for good; nothing to restore.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0061_practicetypestats'),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]

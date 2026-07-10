# Step 2 of 3 (practice stats split): merge duplicate UserStatistics rows,
# then seed PracticeStats from the legacy columns.
#
# Legacy attribution: everything counted in UserStatistics before the
# PracticeAttempt log existed was answered when the site only had English
# questions, so the English row absorbs the legacy totals. UserStatistics kept
# counting after PracticeAttempt was introduced too (every graded answer,
# including practice), so per user the English seed is
# max(UserStatistics totals, English PracticeAttempt counts) — never a sum,
# which would double-count. Math history starts with the PracticeAttempt log
# (math questions didn't exist before it).

from collections import defaultdict

from django.db import migrations
from django.db.models import Count, Q


def merge_duplicate_userstatistics(apps, schema_editor):
    UserStatistics = apps.get_model('api', 'UserStatistics')

    rows_by_user = defaultdict(list)
    for row in UserStatistics.objects.order_by('id'):
        rows_by_user[row.user_id].append(row)

    for rows in rows_by_user.values():
        if len(rows) == 1:
            continue
        keeper, extras = rows[0], rows[1:]
        for extra in extras:
            keeper.correct_number += extra.correct_number
            keeper.incorrect_number += extra.incorrect_number
            keeper.coins += extra.coins
            keeper.current_streak = max(keeper.current_streak, extra.current_streak)
            keeper.login_streak = max(keeper.login_streak, extra.login_streak)
            keeper.normal_multiplier = max(keeper.normal_multiplier, extra.normal_multiplier)
            if extra.last_login_date and (
                keeper.last_login_date is None or extra.last_login_date > keeper.last_login_date
            ):
                keeper.last_login_date = extra.last_login_date
            for pet_id, level in (extra.user_pet_levels or {}).items():
                existing = keeper.user_pet_levels.get(pet_id, 0)
                keeper.user_pet_levels[pet_id] = max(existing, level)
        keeper.save()
        UserStatistics.objects.filter(id__in=[extra.id for extra in extras]).delete()


def seed_practice_stats(apps, schema_editor):
    Profile = apps.get_model('api', 'Profile')
    UserStatistics = apps.get_model('api', 'UserStatistics')
    PracticeAttempt = apps.get_model('api', 'PracticeAttempt')
    PracticeStats = apps.get_model('api', 'PracticeStats')

    profiles = {p.user_id: p for p in Profile.objects.all()}
    legacy = {
        s.user_id: (s.correct_number, s.incorrect_number)
        for s in UserStatistics.objects.all()
    }
    attempts = {
        (row['user_id'], row['subject']): (row['answered'], row['correct_count'])
        for row in PracticeAttempt.objects.values('user_id', 'subject').annotate(
            answered=Count('id'),
            correct_count=Count('id', filter=Q(correct=True)),
        )
    }

    user_ids = set(profiles) | set(legacy) | {user_id for user_id, _ in attempts}
    rows = []
    for user_id in user_ids:
        profile = profiles.get(user_id)
        us_correct, us_incorrect = legacy.get(user_id, (0, 0))
        pa_eng_answered, pa_eng_correct = attempts.get((user_id, 'english'), (0, 0))
        pa_math_answered, pa_math_correct = attempts.get((user_id, 'math'), (0, 0))

        english_answered = max(us_correct + us_incorrect, pa_eng_answered)
        english_correct = min(max(us_correct, pa_eng_correct), english_answered)

        rows.append(PracticeStats(
            user_id=user_id,
            subject='english',
            elo=profile.sp_elo_rating if profile else 1200,
            answered=english_answered,
            correct=english_correct,
            active_question_id=profile.active_practice_question_id if profile else None,
        ))
        rows.append(PracticeStats(
            user_id=user_id,
            subject='math',
            elo=profile.math_elo_rating if profile else 1200,
            answered=pa_math_answered,
            correct=min(pa_math_correct, pa_math_answered),
            active_question_id=profile.active_math_question_id if profile else None,
        ))

    PracticeStats.objects.bulk_create(rows, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0051_practicestats'),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_userstatistics, migrations.RunPython.noop),
        migrations.RunPython(seed_practice_stats, migrations.RunPython.noop),
    ]

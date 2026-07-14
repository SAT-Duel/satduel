"""
Infinite-practice endpoints: adaptive question selection, the free-tier daily
quota, and the revised single-player Elo.

Tier rules
----------
Free:    FREE_DAILY_LIMIT graded answers per day, random topics only.
Premium: unlimited answers, may filter practice by topic.

Elo rules (revision of the old behaviour, which updated ratings on every
check_answer call from any surface):
- Only practice-mode answers move Elo, and only the FIRST attempt a user ever
  makes at a given question (repeat sightings are for review, not rating).
- Users get a provisional K-factor (32) for their first 30 attempts, then 16.
- Question ratings move slowly (K=8) since they aggregate many users.
- Ratings are clamped to [100, 3000].
"""
import random

from django.conf import settings
from django.db.models import Count, F, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api import generation
from api.models import (
    PracticeActiveQuestion,
    PracticeAttempt,
    PracticeStats,
    PracticeTypeStats,
    Question,
)
from api.views.serializers import QuestionSerializer

# question_types are the official College Board skill names in the AI
# generator's taxonomy — reused so the two never drift apart.
DEFAULT_QUESTION_TYPES = [
    s['name'] for d in generation.ENGLISH_DOMAINS for s in d['skills']
]
MATH_QUESTION_TYPES = [
    s['name'] for d in generation.MATH_DOMAINS for s in d['skills']
]

SUBJECT_TYPES = {
    'english': DEFAULT_QUESTION_TYPES,
    'math': MATH_QUESTION_TYPES,
}
SUBJECTS = list(SUBJECT_TYPES)


def resolve_subject(name):
    return name if name in SUBJECT_TYPES else 'english'


def subject_of(question):
    """Which subject a question belongs to, from its question_type."""
    return 'math' if question.question_type in MATH_QUESTION_TYPES else 'english'


def subject_filter(subject):
    return Q(subject=resolve_subject(subject))


def get_practice_stats(user, subject):
    """The user's per-subject stats row (rating, counters, active question)."""
    stats, _ = PracticeStats.objects.get_or_create(user=user, subject=resolve_subject(subject))
    return stats


def practice_stats_breakdown(user):
    """Per-subject lifetime counters (includes legacy pre-PracticeAttempt
    progress, which the migration folded into the English row)."""
    rows = {row.subject: row for row in PracticeStats.objects.filter(user=user)}
    payload = {}
    for subject in SUBJECTS:
        row = rows.get(subject)
        answered = row.answered if row else 0
        correct = row.correct if row else 0
        payload[f'{subject}_answered'] = answered
        payload[f'{subject}_correct'] = correct
        payload[f'{subject}_accuracy'] = round(correct / answered * 100) if answered else None
        payload[f'{subject}_elo'] = row.elo if row else 1200
    payload['practice_answered'] = sum(payload[f'{s}_answered'] for s in SUBJECTS)
    payload['practice_correct'] = sum(payload[f'{s}_correct'] for s in SUBJECTS)
    payload['practice_accuracy'] = (
        round(payload['practice_correct'] / payload['practice_answered'] * 100)
        if payload['practice_answered'] else None
    )
    payload['current_streak'] = practice_current_streak(user)
    return payload


# Old name, kept so callers read naturally at both call sites.
practice_attempt_breakdown = practice_stats_breakdown


def record_practice_answer(user, question, correct, subject, selected_choice):
    """Log the attempt and bump the subject's lifetime counters atomically."""
    first_attempt = not PracticeAttempt.objects.filter(user=user, question=question).exists()
    PracticeAttempt.objects.create(
        user=user, question=question, correct=correct, subject=subject,
        selected_choice=selected_choice,
    )
    stats = get_practice_stats(user, subject)
    stats.answered = F('answered') + 1
    if correct:
        stats.correct = F('correct') + 1
    stats.save(update_fields=['answered', 'correct'])

    # Question-bank progress counts DISTINCT questions, so only the first
    # attempt at a question moves the per-type counters (same rule as Elo).
    if first_attempt and question.question_type:
        type_stats, _ = PracticeTypeStats.objects.get_or_create(
            user=user, question_type=question.question_type,
        )
        type_stats.solved = F('solved') + 1
        fields = ['solved']
        if correct:
            type_stats.correct = F('correct') + 1
            fields.append('correct')
        type_stats.save(update_fields=fields)


def practice_type_progress(user, subjects=None):
    """Question-bank progress per type: solved (distinct attempted) vs total.

    Returns {subject: [{'type', 'solved', 'correct', 'total'}, ...]} in the
    taxonomy's teaching order. Totals come from the live Question table, so
    solved is clamped in case questions were deleted after being attempted.
    """
    subjects = [s for s in (subjects or SUBJECTS) if s in SUBJECT_TYPES]
    types = [t for s in subjects for t in SUBJECT_TYPES[s]]
    totals = {
        row['question_type']: row['total']
        for row in Question.objects.filter(question_type__in=types)
        .values('question_type').annotate(total=Count('id'))
    }
    stats = {
        row.question_type: row
        for row in PracticeTypeStats.objects.filter(user=user, question_type__in=types)
    }
    payload = {}
    for subject in subjects:
        entries = []
        for question_type in SUBJECT_TYPES[subject]:
            total = totals.get(question_type, 0)
            row = stats.get(question_type)
            solved = min(row.solved, total) if row else 0
            correct = min(row.correct, solved) if row else 0
            entries.append({
                'type': question_type,
                'solved': solved,
                'correct': correct,
                'total': total,
            })
        payload[subject] = entries
    return payload


def practice_current_streak(user):
    streak = 0
    for correct in PracticeAttempt.objects.filter(user=user).order_by('-created_at', '-id').values_list('correct', flat=True):
        if not correct:
            break
        streak += 1
    return streak

USER_K_PROVISIONAL = 32
USER_K_STABLE = 16
QUESTION_K = 8
PROVISIONAL_ATTEMPTS = 30

RATING_MIN, RATING_MAX = 100, 3000


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------

def get_quota(user):
    """Return (used_today, limit, has_premium). limit is None for premium."""
    profile = getattr(user, 'profile', None)
    has_premium = bool(profile and profile.has_premium)
    start, end = _local_day_bounds_utc(profile, _local_today(profile))
    used = PracticeAttempt.objects.filter(
        user=user, created_at__gte=start, created_at__lt=end,
    ).count()
    limit = None if has_premium else settings.FREE_DAILY_LIMIT
    return used, limit, has_premium


def quota_payload(user):
    used, limit, has_premium = get_quota(user)
    profile = getattr(user, 'profile', None)
    _, reset_at = _local_day_bounds_utc(profile, _local_today(profile))
    return {
        'used': used,
        'limit': limit,
        'remaining': None if limit is None else max(0, limit - used),
        'is_premium': has_premium,
        'reset_at': reset_at.isoformat(),
        'timezone': str(_user_tz(profile)),
    }


# ---------------------------------------------------------------------------
# Elo (Elo-Davidson expected score, per-side K)
# ---------------------------------------------------------------------------

def _expected_score(rating_a, rating_b, kappa=1, s=400):
    r = rating_a - rating_b
    exponent = 10 ** (r / s)
    return (exponent + kappa / 2) / (10 ** (-r / s) + kappa + exponent)


def _clamp(rating):
    return max(RATING_MIN, min(RATING_MAX, int(rating)))


def apply_practice_elo(user, question, correct):
    """First-attempt-only rating update between a user and a question."""
    subject = subject_of(question)
    stats = get_practice_stats(user, subject)
    previous_rating = stats.elo

    already_attempted = PracticeAttempt.objects.filter(user=user, question=question).exists()
    if already_attempted:
        return {
            'rated': False, 'subject': subject,
            'previous_rating': previous_rating, 'new_rating': previous_rating, 'delta': 0,
        }

    total_attempts = PracticeAttempt.objects.filter(user=user).filter(subject_filter(subject)).count()
    user_k = USER_K_PROVISIONAL if total_attempts < PROVISIONAL_ATTEMPTS else USER_K_STABLE

    expected = _expected_score(previous_rating, question.sp_elo_rating)
    result = 1.0 if correct else 0.0

    new_rating = _clamp(previous_rating + user_k * (result - expected))
    stats.elo = new_rating
    stats.save(update_fields=['elo'])

    question.sp_elo_rating = _clamp(question.sp_elo_rating - QUESTION_K * (result - expected))
    question.save(update_fields=['sp_elo_rating'])
    return {
        'rated': True, 'subject': subject,
        'previous_rating': previous_rating, 'new_rating': new_rating,
        'delta': new_rating - previous_rating,
    }


# ---------------------------------------------------------------------------
# Question selection
# ---------------------------------------------------------------------------

def pick_practice_question(user, subject, question_type=None):
    """Pick an unattempted question near the user's rating.

    The caller distinguishes an empty topic from a completed one so practice
    never silently recycles a question the student already answered.
    """
    types = SUBJECT_TYPES[subject]
    user_rating = get_practice_stats(user, subject).elo

    base = Question.objects.all()
    if question_type and question_type != 'any' and question_type in types:
        base = base.filter(question_type=question_type)
    else:
        base = base.filter(question_type__in=types)

    if not base.exists():
        return None, 'no_questions'

    attempted_ids = set(
        PracticeAttempt.objects.filter(user=user).values_list('question_id', flat=True)
    )
    fresh = base.exclude(id__in=attempted_ids)
    if not fresh.exists():
        return None, 'completed_topic'

    # Widen the rating window until we find fresh questions.
    for window in (250, 500, 1000, None):
        qs = fresh
        if window is not None:
            qs = qs.filter(
                sp_elo_rating__gte=user_rating - window,
                sp_elo_rating__lte=user_rating + window,
            )
        fresh_ids = list(qs.values_list('id', flat=True))
        if fresh_ids:
            return Question.objects.get(id=random.choice(fresh_ids)), None

    return None, 'completed_topic'


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def next_question(request):
    """Serve the next adaptive practice question, enforcing tier rules."""
    question_type = request.GET.get('type')
    subject = resolve_subject(request.GET.get('subject'))
    quota = quota_payload(request.user)

    if question_type and question_type != 'any' and not quota['is_premium']:
        return Response(
            {'error': 'premium_required',
             'detail': 'Topic selection is a premium feature. Free practice serves random topics.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if quota['remaining'] is not None and quota['remaining'] <= 0:
        return Response(
            {'error': 'daily_limit', 'quota': quota,
             'detail': 'You have used your free questions for today. Upgrade for unlimited practice.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    selected_type = question_type if question_type in SUBJECT_TYPES[subject] else None
    lane = f'{subject}:{selected_type or "any"}'
    active = PracticeActiveQuestion.objects.filter(user=request.user, lane=lane).first()
    if active:
        return Response({
            'question': QuestionSerializer(active.question).data,
            'quota': quota, 'subject': subject,
        })

    question, empty_state = pick_practice_question(request.user, subject, selected_type)
    if question is None:
        topic = selected_type or 'all topics'
        if empty_state == 'completed_topic':
            detail = f'You answered every {subject} practice problem in {topic}.'
        else:
            detail = f'No {subject} practice questions are available in {topic} yet.'
        return Response({
            'error': empty_state,
            'detail': detail,
            'subject': subject,
            'topic': selected_type or 'any',
            'quota': quota,
        }, status=status.HTTP_404_NOT_FOUND)

    active, _ = PracticeActiveQuestion.objects.get_or_create(
        user=request.user,
        lane=lane,
        defaults={'question': question},
    )

    return Response({
        'question': QuestionSerializer(active.question).data,
        'quota': quota, 'subject': subject,
    })


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def practice_status(request):
    """Quota + tier + rating + day-streak snapshot for practice surfaces."""
    stats = practice_stats_breakdown(request.user)
    return Response({
        'quota': quota_payload(request.user),
        'sp_elo_rating': stats['english_elo'],
        'math_elo_rating': stats['math_elo'],
        'stats': stats,
        'topics': SUBJECT_TYPES,
        'type_progress': practice_type_progress(request.user),
        'daily': daily_snapshot(request.user),
    })


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def practice_history(request):
    """Return the user's past practice answers, newest first."""
    subject = request.GET.get('subject')
    if subject not in SUBJECTS:
        subject = None
    try:
        offset = max(0, int(request.GET.get('offset', 0)))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = min(50, max(1, int(request.GET.get('limit', 20))))
    except (TypeError, ValueError):
        limit = 20

    # Do not expose a known answer while the same question is currently live
    # in a duel or tournament.
    from api.models import TournamentParticipation, TrackedQuestion
    tournament_questions = TournamentParticipation.objects.filter(
        user=request.user, status='Active',
    ).values_list('tournament__questions', flat=True)
    duel_questions = TrackedQuestion.objects.filter(
        user=request.user, room__status='Battling', status='Blank',
    ).values_list('question_id', flat=True)

    attempts = PracticeAttempt.objects.filter(user=request.user).exclude(
        question_id__in=tournament_questions,
    ).exclude(
        question_id__in=duel_questions,
    )
    if subject:
        attempts = attempts.filter(subject=subject)
    attempts = attempts.select_related('question').order_by('-created_at', '-id')
    page = list(attempts[offset:offset + limit + 1])
    has_more = len(page) > limit

    return Response({
        'attempts': [{
            'id': attempt.id,
            'subject': attempt.subject,
            'correct': attempt.correct,
            'selected_choice': attempt.selected_choice,
            'created_at': attempt.created_at.isoformat(),
            'question': {
                'id': attempt.question_id,
                'question': attempt.question.question,
                'choices': [
                    attempt.question.choice_a, attempt.question.choice_b,
                    attempt.question.choice_c, attempt.question.choice_d,
                ],
                'difficulty': attempt.question.difficulty,
                'question_type': attempt.question.question_type,
                'correct_choice_label': attempt.question.answer,
                'correct_answer': attempt.question.answer_text,
                'explanation': attempt.question.explanation,
            },
        } for attempt in page[:limit]],
        'has_more': has_more,
        'next_offset': offset + limit if has_more else None,
    })


# ---------------------------------------------------------------------------
# Day streak (practice-completion based)
#
# Completing DAILY_PRACTICE_GOAL practice answers within the user's LOCAL day
# extends the streak. Updated at answer-time and evaluated lazily at read-time,
# so no midnight cron job is needed: a missed day simply reads as a streak of 0.
# ---------------------------------------------------------------------------
import datetime

import pytz


def _user_tz(profile):
    try:
        return pytz.timezone(profile.timezone) if profile else pytz.UTC
    except Exception:
        return pytz.UTC


def _local_today(profile):
    return timezone.now().astimezone(_user_tz(profile)).date()


def _local_day_bounds_utc(profile, local_date):
    """UTC datetimes spanning the given local calendar day."""
    tz = _user_tz(profile)
    start = tz.localize(datetime.datetime.combine(local_date, datetime.time.min))
    end = tz.localize(datetime.datetime.combine(
        local_date + datetime.timedelta(days=1), datetime.time.min,
    ))
    return start.astimezone(pytz.UTC), end.astimezone(pytz.UTC)


def _attempts_on(user, profile, local_date):
    start, end = _local_day_bounds_utc(profile, local_date)
    return PracticeAttempt.objects.filter(
        user=user, created_at__gte=start, created_at__lt=end,
    ).count()


def effective_streak(profile, today=None):
    """Stored streak counts only if the last completion was today or yesterday."""
    if profile is None or profile.last_practice_completed is None:
        return 0
    today = today or _local_today(profile)
    if profile.last_practice_completed >= today - datetime.timedelta(days=1):
        return profile.practice_streak
    return 0


def update_daily_streak(user):
    """Called after each practice attempt. Extends the streak the moment the
    user's answer count for their local day reaches the goal."""
    profile = getattr(user, 'profile', None)
    goal = settings.DAILY_PRACTICE_GOAL
    if profile is None:
        return {'count': 0, 'goal': goal, 'completed_today': False,
                'streak': 0, 'longest': 0, 'streak_extended': False}

    today = _local_today(profile)
    count = _attempts_on(user, profile, today)
    _, day_ends_at = _local_day_bounds_utc(profile, today)
    completed = count >= goal
    extended = False

    if completed and profile.last_practice_completed != today:
        yesterday = today - datetime.timedelta(days=1)
        if profile.last_practice_completed == yesterday:
            profile.practice_streak += 1
        else:
            profile.practice_streak = 1
        profile.longest_practice_streak = max(
            profile.longest_practice_streak, profile.practice_streak,
        )
        profile.last_practice_completed = today
        profile.save(update_fields=[
            'practice_streak', 'longest_practice_streak', 'last_practice_completed',
        ])
        extended = True

    return {
        'count': count,
        'goal': goal,
        'completed_today': profile.last_practice_completed == today,
        'streak': effective_streak(profile, today),
        'longest': profile.longest_practice_streak,
        'streak_extended': extended,
        'day_ends_at': day_ends_at.isoformat(),
        'timezone': str(_user_tz(profile)),
    }


def week_strip(user, profile):
    """Last 7 local days, oldest first: which days hit the goal."""
    today = _local_today(profile)
    goal = settings.DAILY_PRACTICE_GOAL
    start_date = today - datetime.timedelta(days=6)
    start_utc, _ = _local_day_bounds_utc(profile, start_date)

    tz = _user_tz(profile)
    counts = {}
    stamps = PracticeAttempt.objects.filter(
        user=user, created_at__gte=start_utc,
    ).values_list('created_at', flat=True)
    for stamp in stamps:
        local_date = stamp.astimezone(tz).date()
        counts[local_date] = counts.get(local_date, 0) + 1

    days = []
    for offset in range(7):
        d = start_date + datetime.timedelta(days=offset)
        days.append({
            'date': d.isoformat(),
            'weekday': d.strftime('%a'),
            'count': counts.get(d, 0),
            'completed': counts.get(d, 0) >= goal,
            'is_today': d == today,
        })
    return days


def practice_activity(user, days=365):
    """Daily answered-question totals for the profile activity grid."""
    profile = getattr(user, 'profile', None)
    today = _local_today(profile)
    start_date = today - datetime.timedelta(days=days - 1)
    start_utc, _ = _local_day_bounds_utc(profile, start_date)
    _, end_utc = _local_day_bounds_utc(profile, today)
    tz = _user_tz(profile)
    counts = {}
    attempts = PracticeAttempt.objects.filter(
        user=user, created_at__gte=start_utc, created_at__lt=end_utc,
    ).values_list('created_at', 'subject')
    for stamp, subject in attempts:
        local_date = stamp.astimezone(tz).date()
        day = counts.setdefault(local_date, {'count': 0, 'english': 0, 'math': 0})
        day['count'] += 1
        day[subject] += 1

    return [
        {'date': date.isoformat(), **counts.get(date, {'count': 0, 'english': 0, 'math': 0})}
        for date in (start_date + datetime.timedelta(days=offset) for offset in range(days))
    ]


def daily_snapshot(user):
    """Full streak block for dashboards: today's progress + week strip."""
    profile = getattr(user, 'profile', None)
    goal = settings.DAILY_PRACTICE_GOAL
    if profile is None:
        return {'count': 0, 'goal': goal, 'completed_today': False,
                'streak': 0, 'longest': 0, 'week': []}
    today = _local_today(profile)
    count = _attempts_on(user, profile, today)
    _, day_ends_at = _local_day_bounds_utc(profile, today)
    return {
        'count': count,
        'goal': goal,
        'completed_today': profile.last_practice_completed == today,
        'streak': effective_streak(profile, today),
        'longest': profile.longest_practice_streak,
        'week': week_strip(user, profile),
        'day_ends_at': day_ends_at.isoformat(),
        'timezone': str(_user_tz(profile)),
    }

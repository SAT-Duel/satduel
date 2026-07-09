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
from django.db.models import Count, Q
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
from api.models import PracticeAttempt, Profile, Question
from api.views.serializers import QuestionSerializer

DEFAULT_QUESTION_TYPES = [
    'Cross-Text Connections', 'Text Structure and Purpose', 'Words in Context',
    'Rhetorical Synthesis', 'Transitions', 'Central Ideas and Details',
    'Command of Evidence', 'Inferences', 'Boundaries', 'Form, Structure, and Sense',
]

# Math question_types are the official College Board skill names in the AI
# generator's taxonomy — reused so the two never drift apart.
MATH_QUESTION_TYPES = list(generation.SKILL_INDEX)

# Everything subject-specific (which types, which Elo field, which locked
# question) lives here so the endpoints stay subject-agnostic.
SUBJECTS = {
    'english': {
        'types': DEFAULT_QUESTION_TYPES,
        'elo_field': 'sp_elo_rating',
        'active_field': 'active_practice_question',
    },
    'math': {
        'types': MATH_QUESTION_TYPES,
        'elo_field': 'math_elo_rating',
        'active_field': 'active_math_question',
    },
}


def resolve_subject(name):
    return name if name in SUBJECTS else 'english'


def subject_of(question):
    """Which subject a question belongs to, from its question_type."""
    return 'math' if question.question_type in MATH_QUESTION_TYPES else 'english'


def subject_filter(subject):
    return Q(subject=resolve_subject(subject))


def practice_attempt_breakdown(user):
    """Practice-only counts, split by SAT subject."""
    stats = PracticeAttempt.objects.filter(user=user).aggregate(
        math_answered=Count('id', filter=subject_filter('math')),
        math_correct=Count('id', filter=subject_filter('math') & Q(correct=True)),
        english_answered=Count('id', filter=subject_filter('english')),
        english_correct=Count('id', filter=subject_filter('english') & Q(correct=True)),
    )
    stats['practice_answered'] = stats['math_answered'] + stats['english_answered']
    stats['practice_correct'] = stats['math_correct'] + stats['english_correct']
    stats['current_streak'] = practice_current_streak(user)
    return stats


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
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    used = PracticeAttempt.objects.filter(user=user, created_at__gte=today_start).count()
    limit = None if has_premium else settings.FREE_DAILY_LIMIT
    return used, limit, has_premium


def quota_payload(user):
    used, limit, has_premium = get_quota(user)
    return {
        'used': used,
        'limit': limit,
        'remaining': None if limit is None else max(0, limit - used),
        'is_premium': has_premium,
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
    """First-attempt-only rating update between a user and a question. Moves the
    Elo field for the question's subject (English or Math)."""
    subject = subject_of(question)
    elo_field = SUBJECTS[subject]['elo_field']
    profile = Profile.objects.get(user=user)
    previous_rating = getattr(profile, elo_field)

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
    setattr(profile, elo_field, new_rating)
    profile.save(update_fields=[elo_field])

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
    """Pick a question near the user's rating, preferring ones never attempted."""
    config = SUBJECTS[subject]
    profile = getattr(user, 'profile', None)
    user_rating = getattr(profile, config['elo_field']) if profile else 1200

    base = Question.objects.all()
    if question_type and question_type != 'any' and question_type in config['types']:
        base = base.filter(question_type=question_type)
    else:
        base = base.filter(question_type__in=config['types'])

    attempted_ids = set(
        PracticeAttempt.objects.filter(user=user).values_list('question_id', flat=True)
    )

    # Widen the rating window until we find fresh questions.
    for window in (250, 500, 1000, None):
        qs = base
        if window is not None:
            qs = qs.filter(
                sp_elo_rating__gte=user_rating - window,
                sp_elo_rating__lte=user_rating + window,
            )
        fresh_ids = list(qs.exclude(id__in=attempted_ids).values_list('id', flat=True))
        if fresh_ids:
            return Question.objects.get(id=random.choice(fresh_ids))

    # Everything's been attempted: recycle from the full pool.
    all_ids = list(base.values_list('id', flat=True))
    if not all_ids:
        return None
    return Question.objects.get(id=random.choice(all_ids))


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
    active_field = SUBJECTS[subject]['active_field']
    quota = quota_payload(request.user)
    profile = getattr(request.user, 'profile', None)

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

    # Each subject holds its own locked question, so switching subjects and back
    # resumes where you left off.
    active_question = getattr(profile, active_field) if profile else None
    if active_question:
        return Response({
            'question': QuestionSerializer(active_question).data,
            'quota': quota, 'subject': subject,
        })

    question = pick_practice_question(request.user, subject, question_type)
    if question is None:
        return Response({'error': 'No questions available.'}, status=status.HTTP_404_NOT_FOUND)

    if profile:
        setattr(profile, active_field, question)
        profile.save(update_fields=[active_field])

    return Response({
        'question': QuestionSerializer(question).data,
        'quota': quota, 'subject': subject,
    })


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def practice_status(request):
    """Quota + tier + rating + day-streak snapshot for practice surfaces."""
    profile = getattr(request.user, 'profile', None)
    return Response({
        'quota': quota_payload(request.user),
        'sp_elo_rating': profile.sp_elo_rating if profile else None,
        'math_elo_rating': profile.math_elo_rating if profile else None,
        'stats': practice_attempt_breakdown(request.user),
        'topics': {'english': DEFAULT_QUESTION_TYPES, 'math': MATH_QUESTION_TYPES},
        'daily': daily_snapshot(request.user),
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
    end = start + datetime.timedelta(days=1)
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


def daily_snapshot(user):
    """Full streak block for dashboards: today's progress + week strip."""
    profile = getattr(user, 'profile', None)
    goal = settings.DAILY_PRACTICE_GOAL
    if profile is None:
        return {'count': 0, 'goal': goal, 'completed_today': False,
                'streak': 0, 'longest': 0, 'week': []}
    today = _local_today(profile)
    count = _attempts_on(user, profile, today)
    return {
        'count': count,
        'goal': goal,
        'completed_today': profile.last_practice_completed == today,
        'streak': effective_streak(profile, today),
        'longest': profile.longest_practice_streak,
        'week': week_strip(user, profile),
    }

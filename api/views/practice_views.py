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

from api.models import PracticeAttempt, Profile, Question
from api.views.serializers import QuestionSerializer

DEFAULT_QUESTION_TYPES = [
    'Cross-Text Connections', 'Text Structure and Purpose', 'Words in Context',
    'Rhetorical Synthesis', 'Transitions', 'Central Ideas and Details',
    'Command of Evidence', 'Inferences', 'Boundaries', 'Form, Structure, and Sense',
]

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
    """First-attempt-only rating update between a user and a question."""
    already_attempted = PracticeAttempt.objects.filter(user=user, question=question).exists()
    if already_attempted:
        return False

    profile = Profile.objects.get(user=user)
    total_attempts = PracticeAttempt.objects.filter(user=user).count()
    user_k = USER_K_PROVISIONAL if total_attempts < PROVISIONAL_ATTEMPTS else USER_K_STABLE

    expected = _expected_score(profile.sp_elo_rating, question.sp_elo_rating)
    result = 1.0 if correct else 0.0

    profile.sp_elo_rating = _clamp(profile.sp_elo_rating + user_k * (result - expected))
    profile.save(update_fields=['sp_elo_rating'])

    question.sp_elo_rating = _clamp(question.sp_elo_rating - QUESTION_K * (result - expected))
    question.save(update_fields=['sp_elo_rating'])
    return True


# ---------------------------------------------------------------------------
# Question selection
# ---------------------------------------------------------------------------

def pick_practice_question(user, question_type=None):
    """Pick a question near the user's rating, preferring ones never attempted."""
    profile = getattr(user, 'profile', None)
    user_rating = profile.sp_elo_rating if profile else 1200

    base = Question.objects.all()
    if question_type and question_type != 'any':
        base = base.filter(question_type=question_type)
    else:
        base = base.filter(question_type__in=DEFAULT_QUESTION_TYPES)

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

    question = pick_practice_question(request.user, question_type)
    if question is None:
        return Response({'error': 'No questions available.'}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        'question': QuestionSerializer(question).data,
        'quota': quota,
    })


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def practice_status(request):
    """Quota + tier + rating snapshot for the practice page header."""
    profile = getattr(request.user, 'profile', None)
    return Response({
        'quota': quota_payload(request.user),
        'sp_elo_rating': profile.sp_elo_rating if profile else None,
        'topics': DEFAULT_QUESTION_TYPES,
    })

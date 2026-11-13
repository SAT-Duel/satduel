"""Duel challenges: a finished duel's ten questions, sent to friends as a link.

A live duel needs two people online at the same moment. A challenge does not.
The creator has already played the set, so their score is frozen; whoever opens
the link plays the same questions on the same clock and is ranked against it.

Nothing here moves Elo. The two sides did not play under the same conditions,
and a link can be replayed from a second account.
"""
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import (
    DuelChallenge, DuelChallengeAttempt, Question, Room, TrackedQuestion, default_challenge_expiry,
)
from api.views.serializers import QuestionSerializer

# A final answer can leave the browser inside the window and land just after it.
ANSWER_GRACE = timezone.timedelta(seconds=5)
MY_CHALLENGES_LIMIT = 10


def _challenge_or_404(code):
    return get_object_or_404(
        DuelChallenge.objects.select_related('creator__profile'),
        code=str(code).strip().upper(),
    )


def _player(user):
    profile = user.profile
    return {
        'id': user.id,
        'username': user.username,
        'avatar': profile.avatar,
        'avatar_icon': profile.avatar_icon,
    }


def _viewer_attempt(challenge, user):
    """The viewer's run, settled if its clock ran out while nobody was looking."""
    if not user.is_authenticated:
        return None
    attempt = DuelChallengeAttempt.objects.filter(challenge=challenge, user=user).first()
    if attempt:
        attempt.challenge = challenge
        attempt.close_if_done()
    return attempt


def _scoreboard(challenge, viewer):
    """Creator plus every finished run, best score first, earliest finish breaking ties.

    Runs still in progress are left off until their own clock ends, at which
    point close_if_done() settles them.
    """
    rows = [{
        **_player(challenge.creator),
        'score': challenge.creator_score,
        'results': challenge.creator_results,
        'is_creator': True,
        'is_viewer': viewer.is_authenticated and viewer.id == challenge.creator_id,
        'finished_at': challenge.created_at,
    }]
    attempts = challenge.attempts.select_related('user__profile').order_by('started_at')
    for attempt in attempts:
        attempt.challenge = challenge
        attempt.close_if_done()
        if not attempt.is_finished:
            continue
        rows.append({
            **_player(attempt.user),
            'score': attempt.score,
            'results': [attempt.result_for(question_id) for question_id in challenge.question_ids],
            'is_creator': False,
            'is_viewer': viewer.is_authenticated and viewer.id == attempt.user_id,
            'finished_at': attempt.finished_at,
        })
    rows.sort(key=lambda row: (-row['score'], row['finished_at']))
    return rows


def _summary(challenge, viewer):
    attempt = _viewer_attempt(challenge, viewer)
    is_creator = viewer.is_authenticated and viewer.id == challenge.creator_id
    if attempt is None:
        status = 'none'
    elif attempt.is_finished:
        status = 'finished'
    else:
        status = 'playing'

    payload = {
        'code': challenge.code,
        'creator': _player(challenge.creator),
        'creator_score': challenge.creator_score,
        'question_count': len(challenge.question_ids),
        'duration_seconds': challenge.duration_seconds,
        'created_at': challenge.created_at,
        'expires_at': challenge.expires_at,
        'expired': challenge.is_expired,
        'viewer': {
            'authenticated': viewer.is_authenticated,
            'is_creator': is_creator,
            'status': status,
            'score': attempt.score if attempt and attempt.is_finished else None,
            'ends_at': attempt.deadline if attempt and not attempt.is_finished else None,
        },
    }
    # Per-question results stay hidden from anyone who could still use them: a
    # row of ticks and crosses tells a player which questions are the hard ones.
    if is_creator or status == 'finished':
        payload['scoreboard'] = _scoreboard(challenge, viewer)
    else:
        payload['finished_players'] = sum(
            1 for row in challenge.attempts.all() if row.finished_at is not None
        )
    return payload


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def create_challenge(request):
    """Turn a duel the caller has finished into a shareable challenge."""
    room_id = request.data.get('room_id')
    if not room_id:
        return Response({'error': 'Missing room_id'}, status=400)
    room = get_object_or_404(Room, Q(user1=request.user) | Q(user2=request.user), id=room_id)
    if room.status != 'Ended':
        return Response({'error': 'Finish the duel before challenging a friend with it.'}, status=409)

    tracked = list(TrackedQuestion.objects.filter(room=room, user=request.user).order_by('id'))
    if not tracked:
        return Response({'error': 'This duel has no questions to share.'}, status=409)

    defaults = {
        'test_prep_id': room.test_prep_id,
        'question_ids': [entry.question_id for entry in tracked],
        'creator_results': [entry.status for entry in tracked],
        'creator_score': sum(1 for entry in tracked if entry.status == 'Correct'),
        'duration_seconds': room.battle_duration,
    }
    try:
        with transaction.atomic():
            challenge, created = DuelChallenge.objects.get_or_create(
                creator=request.user, source_room=room, defaults=defaults,
            )
    except IntegrityError:
        # Two taps raced; the other request made it.
        challenge, created = DuelChallenge.objects.get(creator=request.user, source_room=room), False

    if not created and challenge.is_expired:
        # Sharing an old duel again reopens its link rather than minting a second one.
        challenge.expires_at = default_challenge_expiry()
        challenge.save(update_fields=['expires_at'])

    return Response(_summary(challenge, request.user), status=201 if created else 200)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([AllowAny])
def challenge_detail(request, code):
    """What a link shows before, during and after play.

    Open to signed-out visitors: the invite has to explain itself before it
    asks anyone to make an account.
    """
    challenge = _challenge_or_404(code)
    return Response(_summary(challenge, request.user))


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def start_challenge(request, code):
    """Begin (or resume) the caller's run and hand over the questions."""
    challenge = _challenge_or_404(code)
    if challenge.creator_id == request.user.id:
        return Response({'error': 'This is your own challenge. Send the link to a friend.'}, status=409)

    attempt = DuelChallengeAttempt.objects.filter(challenge=challenge, user=request.user).first()
    if attempt is None:
        if challenge.is_expired:
            return Response({'error': 'This challenge has expired.'}, status=410)
        try:
            with transaction.atomic():
                attempt = DuelChallengeAttempt.objects.create(challenge=challenge, user=request.user)
        except IntegrityError:
            attempt = DuelChallengeAttempt.objects.get(challenge=challenge, user=request.user)

    attempt.challenge = challenge
    attempt.close_if_done()
    if attempt.is_finished:
        return Response({'error': 'You have already played this challenge.'}, status=409)

    by_id = {question.id: question for question in Question.objects.filter(id__in=challenge.question_ids)}
    ordered = [by_id[question_id] for question_id in challenge.question_ids if question_id in by_id]
    return Response({
        'questions': QuestionSerializer(ordered, many=True).data,
        'results': {
            str(question.id): attempt.result_for(question.id) for question in ordered
        },
        'ends_at': attempt.deadline,
        'duration_seconds': challenge.duration_seconds,
    })


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def answer_challenge(request, code):
    """Grade one answer server-side. Each question can be answered once."""
    question_id = request.data.get('question_id')
    selected_choice = request.data.get('selected_choice')
    if not question_id or not selected_choice:
        return Response({'error': 'Missing question_id or selected_choice.'}, status=400)
    try:
        question_id = int(question_id)
    except (TypeError, ValueError):
        return Response({'error': 'Invalid question_id.'}, status=400)

    attempt = get_object_or_404(
        DuelChallengeAttempt.objects.select_for_update().select_related('challenge'),
        challenge__code=str(code).strip().upper(), user=request.user,
    )
    now = timezone.now()
    if attempt.is_finished:
        return Response({'error': 'This challenge is already finished.'}, status=409)
    if now > attempt.deadline + ANSWER_GRACE:
        attempt.close_if_done(now)
        return Response({'error': 'Time is up.', 'finished': True}, status=409)
    if question_id not in attempt.challenge.question_ids:
        return Response({'error': 'That question is not part of this challenge.'}, status=400)
    if str(question_id) in attempt.answers:
        return Response({'error': 'This question is already answered.'}, status=409)

    question = get_object_or_404(Question, id=question_id)
    correct = question.answer_text == selected_choice
    attempt.answers[str(question_id)] = {'choice': str(selected_choice)[:1000], 'correct': correct}
    attempt.save(update_fields=['answers'])
    attempt.close_if_done(now)
    return Response({
        'status': 'success',
        'result': 'correct' if correct else 'incorrect',
        'finished': attempt.is_finished,
    })


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def finish_challenge(request, code):
    """Close the caller's run now: the clock ran out, or they chose to stop.

    Unanswered questions count as blank. Returns the same payload as the
    detail view, which by now includes the scoreboard.
    """
    attempt = get_object_or_404(
        DuelChallengeAttempt.objects.select_for_update().select_related('challenge__creator__profile'),
        challenge__code=str(code).strip().upper(), user=request.user,
    )
    attempt.close_if_done()
    if not attempt.is_finished:
        attempt.finished_at = timezone.now()
        attempt.score = sum(1 for answer in attempt.answers.values() if answer.get('correct'))
        attempt.save(update_fields=['finished_at', 'score'])
    return Response(_summary(attempt.challenge, request.user))


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def my_challenges(request):
    """The caller's recent challenges, sent and played, for the duel page."""
    sent = []
    created = (
        DuelChallenge.objects.filter(creator=request.user)
        .prefetch_related('attempts__user__profile')[:MY_CHALLENGES_LIMIT]
    )
    for challenge in created:
        finished = []
        for attempt in challenge.attempts.all():
            attempt.challenge = challenge
            attempt.close_if_done()
            if attempt.is_finished:
                finished.append(attempt)
        best = max(finished, key=lambda attempt: attempt.score, default=None)
        sent.append({
            'code': challenge.code,
            'created_at': challenge.created_at,
            'expires_at': challenge.expires_at,
            'expired': challenge.is_expired,
            'question_count': len(challenge.question_ids),
            'your_score': challenge.creator_score,
            'players': len(finished),
            'best': {**_player(best.user), 'score': best.score} if best else None,
        })

    played = []
    attempts = (
        DuelChallengeAttempt.objects.filter(user=request.user)
        .select_related('challenge__creator__profile')
        .order_by('-started_at')[:MY_CHALLENGES_LIMIT]
    )
    for attempt in attempts:
        attempt.close_if_done()
        challenge = attempt.challenge
        played.append({
            'code': challenge.code,
            'started_at': attempt.started_at,
            'question_count': len(challenge.question_ids),
            'status': 'finished' if attempt.is_finished else 'playing',
            'your_score': attempt.score if attempt.is_finished else None,
            'creator': _player(challenge.creator),
            'creator_score': challenge.creator_score,
        })

    return Response({'sent': sent, 'played': played})

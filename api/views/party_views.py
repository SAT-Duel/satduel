"""Party Mode: Kahoot-style live quiz rooms.

Clients poll `party_state` about once a second; the room's `advance()` derives
phase transitions from timestamps, so no worker or websocket is needed.
"""
import random

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import (
    PARTY_COUNTDOWN_SECONDS,
    PartyPlayer,
    PartyRoom,
    Question,
)
from api.views.views import ENGLISH_QUESTION_TYPES, MATH_QUESTION_TYPES

# Free-tier vs premium ceilings for room settings.
CAPS = {
    'free': {'max_players': 6, 'num_questions': 20},
    'premium': {'max_players': 50, 'num_questions': 50},
}
DIFFICULTY_RANGES = {'easy': (1, 3), 'medium': (2, 4), 'hard': (3, 5)}
SUBJECT_TYPES = {
    'math': MATH_QUESTION_TYPES,
    'english': ENGLISH_QUESTION_TYPES,
    'mixed': MATH_QUESTION_TYPES + ENGLISH_QUESTION_TYPES,
}
JOINABLE = ('lobby', 'countdown', 'question', 'leaderboard')


def _caps_for(user):
    return CAPS['premium'] if user.profile.has_premium else CAPS['free']


def _new_code():
    for _ in range(30):
        code = f"{random.randint(0, 999999):06d}"
        if not PartyRoom.objects.filter(code=code).exclude(status='finished').exists():
            return code
    raise RuntimeError('Could not allocate a party code')


def _clamp(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _player_entry(player, index_key):
    profile = player.user.profile
    answer = player.answers.get(index_key, {})
    return {
        'id': player.user_id,
        'username': player.user.username,
        'avatar': profile.avatar,
        'avatar_icon': profile.avatar_icon,
        'score': player.score,
        'answered': index_key in player.answers,
        'last_points': answer.get('points', 0),
        'last_correct': answer.get('correct'),
    }


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def create_party(request):
    caps = _caps_for(request.user)
    data = request.data
    subject = data.get('subject') if data.get('subject') in SUBJECT_TYPES else 'mixed'
    difficulty = data.get('difficulty') if data.get('difficulty') in DIFFICULTY_RANGES else 'medium'

    # One live room per host: a new room supersedes any the user abandoned.
    PartyRoom.objects.filter(host=request.user).exclude(status='finished').update(status='finished')
    # ponytail: opportunistic GC of day-old rooms; a cron only if the table ever matters.
    PartyRoom.objects.filter(created_at__lt=timezone.now() - timezone.timedelta(days=1)).delete()

    room = PartyRoom.objects.create(
        host=request.user,
        code=_new_code(),
        max_players=_clamp(data.get('max_players'), 2, caps['max_players'], min(6, caps['max_players'])),
        num_questions=_clamp(data.get('num_questions'), 1, caps['num_questions'], 10),
        seconds_per_question=_clamp(data.get('seconds_per_question'), 10, 300, 90),
        subject=subject,
        difficulty=difficulty,
    )
    PartyPlayer.objects.create(room=room, user=request.user)
    return Response({'id': room.id, 'code': room.code}, status=201)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def join_party(request):
    code = str(request.data.get('code', '')).strip()
    room = PartyRoom.objects.filter(code=code).exclude(status='finished').order_by('-id').first()
    if room:
        room.sync_presence()  # an abandoned lobby closes here instead of matching
    if not room or room.status == 'finished':
        return Response({'error': 'No room found with that code.'}, status=404)

    if room.players.filter(user=request.user).exists():
        return Response({'id': room.id})  # rejoin
    if room.status != 'lobby':
        return Response({'error': 'That game has already started.'}, status=400)
    if room.players.count() >= room.max_players:
        return Response({'error': 'That room is full.'}, status=400)

    PartyPlayer.objects.get_or_create(room=room, user=request.user)
    return Response({'id': room.id})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def start_party(request, room_id):
    room = get_object_or_404(PartyRoom, id=room_id, host=request.user)
    if room.status != 'lobby':
        return Response({'error': 'The game has already started.'}, status=400)

    lo, hi = DIFFICULTY_RANGES[room.difficulty]
    ids = list(
        Question.objects.filter(
            question_type__in=SUBJECT_TYPES[room.subject],
            difficulty__gte=lo,
            difficulty__lte=hi,
        ).values_list('id', flat=True)
    )
    if not ids:
        return Response({'error': 'No questions available for these settings.'}, status=400)

    room.question_ids = random.sample(ids, min(room.num_questions, len(ids)))
    room.num_questions = len(room.question_ids)
    room.status = 'countdown'
    room.phase_started_at = timezone.now()
    room.save()
    return Response({'status': 'countdown'})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def answer_party_question(request, room_id):
    with transaction.atomic():
        room = get_object_or_404(PartyRoom.objects.select_for_update(), id=room_id)
        room.advance()
        if room.status != 'question':
            return Response({'error': 'Not accepting answers right now.'}, status=400)

        player = get_object_or_404(PartyPlayer, room=room, user=request.user)
        key = str(room.current_index)
        if key in player.answers:
            return Response({'error': 'Already answered.'}, status=400)

        choice = str(request.data.get('choice', '')).upper()
        if choice not in ('A', 'B', 'C', 'D'):
            return Response({'error': 'Invalid choice.'}, status=400)

        question = Question.objects.get(id=room.current_question_id())
        elapsed = (timezone.now() - room.phase_started_at).total_seconds()
        elapsed = max(0.0, min(elapsed, room.seconds_per_question))
        correct = choice == question.answer
        # Kahoot-style: a correct answer is worth 500-1000, scaling with speed.
        points = 500 + round(500 * (1 - elapsed / room.seconds_per_question)) if correct else 0

        player.answers[key] = {'choice': choice, 'correct': correct, 'points': points}
        player.score += points
        player.save()
        room.advance()  # everyone may have answered now
    return Response({'answered': True})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def next_party_question(request, room_id):
    room = get_object_or_404(PartyRoom, id=room_id, host=request.user)
    if room.status != 'leaderboard':
        return Response({'error': 'Nothing to advance right now.'}, status=400)

    if room.current_index + 1 >= len(room.question_ids):
        room.status = 'finished'
    else:
        room.current_index += 1
        room.status = 'question'
    room.phase_started_at = timezone.now()
    room.save(update_fields=['status', 'current_index', 'phase_started_at'])
    return Response({'status': room.status})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def leave_party(request, room_id):
    room = get_object_or_404(PartyRoom, id=room_id)
    room.players.filter(user=request.user).delete()
    # Empty room closes; a departing host hands off to the next player.
    room.sync_presence()
    return Response({'left': True})


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def party_state(request, room_id):
    room = get_object_or_404(PartyRoom, id=room_id)
    player = room.players.filter(user=request.user).first()
    if not player:
        return Response({'error': 'You are not in this room.'}, status=403)
    player.save(update_fields=['last_seen'])  # auto_now heartbeat
    room.advance()

    now = timezone.now()
    key = str(room.current_index)
    players = [
        _player_entry(p, key)
        for p in room.players.select_related('user__profile').all()
    ]
    players.sort(key=lambda p: -p['score'])

    state = {
        'id': room.id,
        'code': room.code,
        'status': room.status,
        'started': bool(room.question_ids),  # lets the UI tell "host closed the lobby" from "game over"
        'is_host': room.host_id == request.user.id,
        'host_username': room.host.username,
        'settings': {
            'max_players': room.max_players,
            'num_questions': room.num_questions,
            'seconds_per_question': room.seconds_per_question,
            'subject': room.subject,
            'difficulty': room.difficulty,
        },
        'players': players,
        'question_number': room.current_index + 1,
        'total_questions': room.num_questions if room.question_ids else room.num_questions,
    }

    if room.status == 'countdown':
        ends = room.phase_started_at + timezone.timedelta(seconds=PARTY_COUNTDOWN_SECONDS)
        state['seconds_left'] = max(0.0, (ends - now).total_seconds())
    elif room.status == 'question':
        question = Question.objects.get(id=room.current_question_id())
        state['seconds_left'] = max(0.0, (room.question_deadline() - now).total_seconds())
        state['question'] = {
            'id': question.id,
            'question': question.question,
            'choices': [question.choice_a, question.choice_b, question.choice_c, question.choice_d],
        }
        state['your_answer'] = player.answers.get(key, {}).get('choice')
    elif room.status == 'leaderboard':
        question = Question.objects.get(id=room.current_question_id())
        answer = player.answers.get(key, {})
        state['reveal'] = {
            'correct_choice': question.answer,
            'correct_text': question.answer_text,
            'your_choice': answer.get('choice'),
            'correct': answer.get('correct', False),
            'points_earned': answer.get('points', 0),
            'is_last': room.current_index + 1 >= len(room.question_ids),
        }

    return Response(state)

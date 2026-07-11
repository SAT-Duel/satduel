import random

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from api.bot_duels import advance_bot, available_bot_user
from api.models import DuelEmote, Room, TrackedQuestion
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from api.views.serializers import RoomSerializer, TrackedQuestionSerializer, TrackedQuestionResultSerializer

DUEL_EMOJIS = ('👍', '🔥', '😂', '😮')


def _room_for_user(room_id, user):
    return get_object_or_404(Room, Q(user1=user) | Q(user2=user), id=room_id)


def _player_payload(user):
    profile = user.profile
    return {
        'id': user.id,
        'username': user.username,
        'avatar': profile.avatar,
        'avatar_icon': profile.avatar_icon,
        'elo_rating': profile.elo_rating,
    }


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def match(request):
    with transaction.atomic():
        user_in_room = Room.objects.filter(
            Q(user1=request.user, status__in=['Searching', 'Battling']) |
            Q(user2=request.user, status__in=['Searching', 'Battling'])
        ).first()

        if user_in_room:
            return Response({'error': 'You are already matching or in a room'}, status=400)

        room = (
            Room.objects.select_for_update()
            .filter(user2__isnull=True, status='Searching')
            .exclude(user1=request.user)
            .first()
        )

        if room:
            room.user2 = request.user
            room.status = 'Battling'
            room.save()
            return Response({'id': room.id, 'full': 'true'}, status=200)
        room = Room.objects.create(user1=request.user, status='Searching')

    serializer = RoomSerializer(room)
    return Response(serializer.data, status=200)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_match_questions(request):
    data = request.data
    user = request.user
    room_id = data.get('room_id')
    if not room_id:
        return Response({'error': 'Missing room_id'}, status=400)
    try:
        room = Room.objects.get(id=room_id)
    except Room.DoesNotExist:
        return Response({'error': 'Room does not exist'}, status=404)

    tracked_questions = TrackedQuestion.objects.filter(user=user, room=room).order_by('id')
    serializer = TrackedQuestionSerializer(tracked_questions, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def update_match_question(request):
    data = request.data
    tracked_question_id = data.get('tracked_question_id')
    selected_choice = data.get('selected_choice')
    if not tracked_question_id or not selected_choice:
        return Response({'error': 'Missing tracked_question_id or selected_choice.'}, status=400)
    track_question = get_object_or_404(
        TrackedQuestion.objects.select_related('question'),
        id=tracked_question_id,
        user=request.user,
        room__status='Battling',
    )
    if track_question.status != 'Blank':
        return Response({'error': 'This question is already answered.'}, status=409)
    if TrackedQuestion.objects.filter(
        room=track_question.room,
        user=request.user,
        id__lt=track_question.id,
        status='Blank',
    ).exists():
        return Response({'error': 'Answer the current question first.'}, status=409)

    correct = track_question.question.answer_text == selected_choice
    track_question.status = 'Correct' if correct else 'Incorrect'
    track_question.save(update_fields=['status'])
    return Response({'status': 'success', 'result': 'correct' if correct else 'incorrect'})


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_room_status(request):
    room_id = request.query_params.get('room_id')
    if not room_id:
        return Response({'error': 'Missing room_id'}, status=400)
    with transaction.atomic():
        room = get_object_or_404(
            Room.objects.select_for_update(),
            Q(user1=request.user) | Q(user2=request.user),
            id=room_id,
        )

        if room.is_full():
            return Response({'status': 'full'})

        elapsed = (timezone.now() - room.created_at).total_seconds()
        should_add_opponent = elapsed >= 10 or (elapsed >= 5 and random.random() < 0.35)
        if room.status == 'Searching' and should_add_opponent:
            bot = available_bot_user(exclude_user=request.user)
            if bot:
                room.user2 = bot
                room.status = 'Battling'
                room.save(update_fields=['user2', 'status'])
                return Response({'status': 'full'})
    return Response({'status': 'waiting'})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_opponent_progres(request):
    data = request.data
    room_id = data.get('room_id')
    room = _room_for_user(room_id, request.user)
    user = request.user
    opponent = room.user1 if user != room.user1 else room.user2
    if opponent and opponent.profile.is_bot:
        # ponytail: polling advances bots; add a worker only when realtime scale needs one.
        advance_bot(room, opponent)
    opponent_tracked_questions = TrackedQuestion.objects.filter(user=opponent, room=room).order_by('id')
    serializer = TrackedQuestionSerializer(opponent_tracked_questions, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def rejoin_match(request):
    battling_room = Room.objects.filter(
        Q(user1=request.user, status='Battling') | Q(user2=request.user, status='Battling'),
    ).first()
    searching_room = Room.objects.filter(
        Q(user1=request.user, status='Searching'),
    ).first()
    if battling_room:
        return Response({'battle_room_id': battling_room.id, 'searching_room_id': None})
    if searching_room:
        return Response({'battle_room_id': None, 'searching_room_id': searching_room.id})
    return Response({'error': 'No room found'}, status=404)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_end_time(request):
    data = request.data
    room_id = data.get('room_id')
    room = _room_for_user(room_id, request.user)
    if room.battle_start_time is None:
        room.battle_start_time = timezone.now()
        room.save(update_fields=['battle_start_time'])
    end_time = room.battle_start_time + timezone.timedelta(seconds=room.battle_duration)

    return Response({
        'end_time': end_time.isoformat(),
        'battle_duration': room.battle_duration})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def end_match(request):
    data = request.data
    room_id = data.get('room_id')
    room = _room_for_user(room_id, request.user)
    if room.status == 'Ended':
        return Response({'status': 'success'})
    for player in (room.user1, room.user2):
        if player.profile.is_bot:
            advance_bot(room, player)
    both_finished = not TrackedQuestion.objects.filter(room=room, status='Blank').exists()
    if not both_finished and not room.is_battle_ended():
        return Response({'error': 'The duel is still in progress.'}, status=409)
    room.user1_score = TrackedQuestion.objects.filter(room=room, user=room.user1, status='Correct').count()
    room.user2_score = TrackedQuestion.objects.filter(room=room, user=room.user2, status='Correct').count()
    room.status = 'Ended'
    room.save(update_fields=['user1_score', 'user2_score', 'status'])

    return Response({'status': 'success'})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_results(request):
    data = request.data
    room_id = data.get('room_id')
    room = _room_for_user(room_id, request.user)
    tracked_questions_user1 = TrackedQuestion.objects.filter(user=room.user1, room=room).order_by('id')
    tracked_questions_user2 = TrackedQuestion.objects.filter(user=room.user2, room=room).order_by('id')
    serializer_user1 = TrackedQuestionResultSerializer(tracked_questions_user1, many=True)
    serializer_user2 = TrackedQuestionResultSerializer(tracked_questions_user2, many=True)
    current_is_user1 = room.user1_id == request.user.id
    current_user = room.user1 if current_is_user1 else room.user2
    opponent = room.user2 if current_is_user1 else room.user1
    current_prefix = 'user1' if current_is_user1 else 'user2'
    opponent_prefix = 'user2' if current_is_user1 else 'user1'
    current_results = serializer_user1.data if current_is_user1 else serializer_user2.data
    opponent_results = serializer_user2.data if current_is_user1 else serializer_user1.data

    def result_player(user, prefix, score, results):
        before = getattr(room, f'{prefix}_elo_before')
        after = getattr(room, f'{prefix}_elo_after')
        return {
            **_player_payload(user),
            'score': score,
            'elo_before': before,
            'elo_after': after,
            'elo_change': after - before if before is not None and after is not None else None,
            'results': results,
        }

    outcome = 'draw' if room.winner_id is None else 'win' if room.winner_id == request.user.id else 'loss'
    return Response({
        'outcome': outcome,
        'current_user': result_player(
            current_user, current_prefix,
            room.user1_score if current_is_user1 else room.user2_score,
            current_results,
        ),
        'opponent': result_player(
            opponent, opponent_prefix,
            room.user2_score if current_is_user1 else room.user1_score,
            opponent_results,
        ),
        'created_at': room.created_at,
        # Keep the legacy arrays while older clients age out.
        'user1_results': serializer_user1.data,
        'user2_results': serializer_user2.data,
    })


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def cancel_match(request):
    data = request.data
    room_id = data.get('room_id')
    room = get_object_or_404(Room, id=room_id, user1=request.user, status='Searching')
    room.delete()
    return Response({'status': 'success'})


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_match_history(request, user_id=None):
    """Ended duels for a user, newest first. Was defined twice with an N+1
    on the nested user serializers; now single, select_related, capped."""
    if user_id:
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)
    else:
        user = request.user

    try:
        limit = min(100, max(1, int(request.GET.get('limit', 20))))
    except ValueError:
        limit = 20

    rooms = (
        Room.objects
        .filter(Q(user1=user) | Q(user2=user), status='Ended')
        .select_related('user1__profile', 'user2__profile', 'winner')
        .order_by('-created_at')[:limit]
    )
    serializer = RoomSerializer(rooms, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_match_info(request):
    data = request.data
    room_id = data.get('room_id')
    room = _room_for_user(room_id, request.user)
    if room.user1 == request.user:
        opponent = room.user2
        user = room.user1
    else:
        opponent = room.user1
        user = room.user2
    return Response({'opponent': _player_payload(opponent), 'currentUser': _player_payload(user)})


@api_view(['GET', 'POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def duel_emotes(request):
    room_id = request.data.get('room_id') if request.method == 'POST' else request.query_params.get('room_id')
    room = _room_for_user(room_id, request.user)
    opponent = room.user1 if request.user == room.user2 else room.user2
    now = timezone.now()

    if request.method == 'POST':
        if room.status != 'Battling':
            return Response({'error': 'This duel has ended.'}, status=409)
        emoji = request.data.get('emoji')
        if emoji not in DUEL_EMOJIS:
            return Response({'error': 'Invalid emote.'}, status=400)
        last_sent = DuelEmote.objects.filter(room=room, sender=request.user).order_by('-created_at').first()
        if last_sent and last_sent.created_at > now - timezone.timedelta(seconds=1):
            return Response({'error': 'Slow down.'}, status=429)
        DuelEmote.objects.create(room=room, sender=request.user, emoji=emoji, visible_at=now)
        if opponent and opponent.profile.is_bot:
            DuelEmote.objects.create(
                room=room,
                sender=opponent,
                emoji=random.choice(DUEL_EMOJIS),
                visible_at=now + timezone.timedelta(seconds=random.uniform(1.5, 3.5)),
            )

    if opponent and opponent.profile.is_bot:
        latest_bot = DuelEmote.objects.filter(room=room, sender=opponent).order_by('-visible_at').first()
        if (not latest_bot or latest_bot.visible_at < now - timezone.timedelta(seconds=8)) and random.random() < 0.25:
            DuelEmote.objects.create(
                room=room,
                sender=opponent,
                emoji=random.choice(DUEL_EMOJIS),
                visible_at=now + timezone.timedelta(seconds=random.uniform(0.5, 2)),
            )

    emotes = list(
        DuelEmote.objects.filter(room=room, visible_at__lte=now)
        .order_by('-visible_at', '-id')
        .values('id', 'sender_id', 'emoji', 'visible_at')[:20]
    )
    return Response({'emotes': list(reversed(emotes))})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def set_winner(request):
    _room_for_user(request.data.get('room_id'), request.user)
    return Response({'status': 'success'})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def set_score(request):
    _room_for_user(request.data.get('room_id'), request.user)
    return Response({'status': 'success'})

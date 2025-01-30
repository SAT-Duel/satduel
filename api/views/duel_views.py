from django.contrib.auth.models import User
from rest_framework.response import Response
from api.models import Room, TrackedQuestion
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.db.models import Q
from api.views.serializers import RoomSerializer, TrackedQuestionSerializer, UserSerializer, \
    TrackedQuestionResultSerializer

from django.utils import timezone


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def match(request):
    user_in_room = Room.objects.filter(
        Q(user1=request.user, status__in=['Searching', 'Battling']) |
        Q(user2=request.user, status__in=['Searching', 'Battling'])
    ).first()

    if user_in_room:
        return Response({'error': 'You are already matching or in a room'}, status=400)

    room = Room.objects.filter(user2__isnull=True, status='Searching').first()

    if room:
        room.user2 = request.user
        room.status = 'Battling'
        room.save()
        return Response({'id': room.id, 'full': 'true'}, status=200)
    else:
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
    result = data.get('result')
    track_question = TrackedQuestion.objects.get(id=tracked_question_id)
    if result == "correct":
        track_question.status = "Correct"
    else:
        track_question.status = "Incorrect"
    track_question.save()
    return Response({'status': 'success'})


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_room_status(request):
    room_id = request.query_params.get('room_id')
    if not room_id:
        print('missing rid')
        return Response({'error': 'Missing room_id'}, status=400)
    try:
        room = Room.objects.get(id=room_id)
    except Room.DoesNotExist:
        return Response({'error': 'Room does not exist'}, status=404)

    if room.is_full():
        return Response({'status': 'full'})
    return Response({'status': 'waiting'})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_opponent_progres(request):
    data = request.data
    room_id = data.get('room_id')
    room = Room.objects.get(id=room_id)
    user = request.user
    opponent = room.user1 if user != room.user1 else room.user2
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
def get_end_time(request):
    data = request.data
    room_id = data.get('room_id')
    room = Room.objects.get(id=room_id)

    if not room:
        return Response({'error': 'No active battle found'}, status=404)
    if room.battle_start_time == None:
        room.battle_start_time = timezone.now()
        room.save()
    end_time = room.battle_start_time + timezone.timedelta(seconds=room.battle_duration)

    return Response({
        'end_time': end_time.isoformat(),
        'battle_duration': room.battle_duration})


@api_view(['POST'])
def end_match(request):
    data = request.data
    room_id = data.get('room_id')
    room = Room.objects.get(id=room_id)

    if not room:
        return Response({'error': 'No active battle found'}, status=404)

    room.status = 'Ended'
    room.save()

    return Response({'status': 'success'})


@api_view(['POST'])
def get_results(request):
    data = request.data
    room_id = data.get('room_id')
    room = Room.objects.get(id=room_id)
    tracked_questions_user1 = TrackedQuestion.objects.filter(user=room.user1, room=room).order_by('id')
    tracked_questions_user2 = TrackedQuestion.objects.filter(user=room.user2, room=room).order_by('id')
    serializer_user1 = TrackedQuestionResultSerializer(tracked_questions_user1, many=True)
    serializer_user2 = TrackedQuestionResultSerializer(tracked_questions_user2, many=True)

    combined_data = {
        'user1_results': serializer_user1.data,
        'user2_results': serializer_user2.data
    }

    return Response(combined_data)


@api_view(['POST'])
def cancel_match(request):
    data = request.data
    room_id = data.get('room_id')
    room = Room.objects.get(id=room_id)
    if not room:
        return Response({'error': 'No active battle found'}, status=404)
    room.delete()
    return Response({'status': 'success'})


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_match_history(request, user_id=None):
    if user_id:
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)
        rooms = Room.objects.filter(Q(user1=user) | Q(user2=user), status='Ended').order_by('-created_at')
    else:
        user = request.user
        rooms = Room.objects.filter(Q(user1=user) | Q(user2=user), status='Ended').order_by('-created_at')

    serializer = RoomSerializer(rooms, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_match_history(request, user_id=None):
    if user_id:
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)
        rooms = Room.objects.filter(Q(user1=user) | Q(user2=user), status='Ended').order_by('-created_at')
    else:
        user = request.user
        rooms = Room.objects.filter(Q(user1=user) | Q(user2=user), status='Ended').order_by('-created_at')

    serializer = RoomSerializer(rooms, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_match_info(request):
    data = request.data
    room_id = data.get('room_id')
    room = Room.objects.get(id=room_id)
    if not room:
        return Response({'error': 'No active battle found'}, status=404)
    if room.user1 == request.user:
        opponent = room.user2
        user = room.user1
    else:
        opponent = room.user1
        user = room.user2
    opponent_data = UserSerializer(opponent)
    user_data = UserSerializer(user)
    return Response({'opponent': opponent_data.data, 'currentUser': user_data.data})


@api_view(['POST'])
def set_winner(request):
    data = request.data
    room_id = data.get('room_id')
    winner = data.get('winner')
    room = Room.objects.get(id=room_id)
    if winner == 'Tie':
        # new_elo1, new_elo2 = get_new_elo(0.5, old_elo1, old_elo2)
        return Response({'status': 'success'})
    if room.user1.username == winner:
        # new_elo1, new_elo2 = get_new_elo(1, old_elo1, old_elo2)
        room.winner = room.user1
    else:
        # new_elo1, new_elo2 = get_new_elo(0, old_elo1, old_elo2)
        room.winner = room.user2
    room.status = 'Ended'
    room.save()
    return Response({'status': 'success'})


@api_view(['POST'])
def set_score(request):
    data = request.data
    room_id = data.get('room_id')
    user1_score = data.get('user1_score')
    user2_score = data.get('user2_score')
    room = Room.objects.get(id=room_id)
    room.user1_score = user1_score
    room.user2_score = user2_score
    room.save()
    return Response({'status': 'success'})

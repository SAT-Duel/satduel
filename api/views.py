from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.response import Response
from api.models import Question, Profile, Room, TrackedQuestion, FriendRequest
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.db.models import Q

from api.serializers import QuestionSerializer, ProfileSerializer, RoomSerializer, TrackedQuestionSerializer, \
    ProfileBiographySerializer, UserSerializer, FriendRequestSerializer


@api_view(['GET'])
def get_random_questions(request):
    try:
        num_questions = int(request.GET.get('num', 5))
    except ValueError:
        return Response({'error': 'Invalid number format'}, status=400)

    random_questions = Question.get_random_questions(num_questions)
    serializer = QuestionSerializer(random_questions, many=True)
    return Response(serializer.data)


@api_view(['POST'])
def check_answer(request):
    data = request.data
    question_id = data.get('question_id')
    selected_choice = data.get('selected_choice')

    if not question_id or not selected_choice:
        return Response({'error': 'Missing question_id or selected_choice'}, status=400)

    try:
        question = Question.objects.get(id=question_id)
    except Question.DoesNotExist:
        return Response({'error': 'Question does not exist'}, status=404)

    correct = (question.answer_text == selected_choice)
    return Response({'result': 'correct' if correct else 'incorrect'})


@api_view(['POST'])
def get_answer(request):
    data = request.data
    question_id = data.get('question_id')
    try:
        question = Question.objects.get(id=question_id)
    except Question.DoesNotExist:
        return Response({'error': 'Question does not exist'}, status=404)
    return Response(
        {'answer': question.answer_text, 'explanation': question.explanation, 'answer_choice': question.answer})


@api_view(['GET', 'POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def profile_view(request):
    profile = Profile.objects.get(user=request.user)
    if request.method == 'GET':
        serializer = ProfileSerializer(profile)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = ProfileSerializer(profile, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def match(request):
    user_in_room = Room.objects.filter(user1=request.user, status__in=['Searching', 'Battling']).first()

    if user_in_room:
        return Response({'error': 'You are already matching or in a room'}, status=400)

    room = Room.objects.filter(user2__isnull=True, status='Searching').first()

    if room:
        room.user2 = request.user
        room.status = 'Battling'
        room.save()
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

    tracked_questions = TrackedQuestion.objects.filter(user=user, room=room)
    serializer = TrackedQuestionSerializer(tracked_questions, many=True)
    return Response(serializer.data)

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def rejoin_match(request):
    room = Room.objects.filter(
        Q(user1=request.user, status='Battling') | Q(user2=request.user, status='Battling'),
    ).first()
    print(room)
    if room:
        return Response({'room_id': room.id})
    return Response({'error': 'No room found'}, status=404)

@api_view(['POST'])
def get_question(request):
    data = request.data
    question_id = data.get('question_id')
    try:
        question = Question.objects.get(id=question_id)
    except Question.DoesNotExist:
        return Response({'error': 'Question does not exist'}, status=404)
    serializer = QuestionSerializer(question)
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
    opponent_tracked_questions = TrackedQuestion.objects.filter(user=opponent, room=room)
    serializer = TrackedQuestionSerializer(opponent_tracked_questions, many=True)
    return Response(serializer.data)


@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def update_biography(request):
    try:
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ProfileBiographySerializer(profile, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def search_users(request):
    query = request.query_params.get('q', '')
    users = User.objects.filter(username__icontains=query)
    serializer = UserSerializer(users, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def send_friend_request(request):
    from_user = request.user
    to_user_id = request.data.get('to_user_id')
    try:
        to_user = User.objects.get(id=to_user_id)
        if FriendRequest.objects.filter(from_user=from_user, to_user=to_user, status='pending').exists():
            return Response({'detail': 'Friend request already sent.'}, status=status.HTTP_400_BAD_REQUEST)
        if from_user == to_user:
            return Response({'detail': 'You cannot send friend request to yourself.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if from_user.profile.friends.filter(id=to_user_id).exists():
            return Response({'detail': 'You are already friends.'}, status=status.HTTP_400_BAD_REQUEST)
        FriendRequest.objects.create(from_user=from_user, to_user=to_user)
        return Response({'detail': 'Friend request sent.'}, status=status.HTTP_201_CREATED)
    except User.DoesNotExist:
        return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def respond_friend_request(request, request_id):
    try:
        friend_request = FriendRequest.objects.get(id=request_id)
        status_response = request.data.get('status')
        if status_response == 'accepted':
            friend_request.accept()
        elif status_response == 'rejected':
            friend_request.reject()
        else:
            return Response({'detail': 'Invalid status.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': f'Friend request {status_response}.'}, status=status.HTTP_200_OK)
    except FriendRequest.DoesNotExist:
        return Response({'detail': 'Friend request not found.'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def list_friend_requests(request):
    friend_requests = FriendRequest.objects.filter(to_user=request.user, status='pending')
    serializer = FriendRequestSerializer(friend_requests, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def list_friends(request):
    user = request.user
    friends = user.profile.friends.all()
    profiles = Profile.objects.filter(user__in=friends)
    serializer = ProfileSerializer(profiles, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def view_profile(request, user_id):
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=404)
    serializer = ProfileSerializer(user.profile)
    return Response(serializer.data)



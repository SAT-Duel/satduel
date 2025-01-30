from random import sample
from venv import logger
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.response import Response
from api.models import Profile, Room, TrackedQuestion, FriendRequest, PersonalizedQuest
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.db.models import Q
from api.views.serializers import QuestionSerializer, ProfileSerializer, RoomSerializer, TrackedQuestionSerializer, \
    ProfileBiographySerializer, UserSerializer, FriendRequestSerializer, TrackedQuestionResultSerializer, \
    InfiniteQuestionsSerializer
from django.db.models import F
from django.utils import timezone
from ..models import Question, UserStatistics
from rest_framework import status


@api_view(['GET'])
def get_random_questions(request):
    try:
        num_questions = int(request.GET.get('num', 5))
    except ValueError:
        return Response({'error': 'Invalid number format'}, status=400)

    random_questions = Question.get_random_questions(num_questions)
    serializer = QuestionSerializer(random_questions, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def list_questions(request):
    question_type = request.GET.get('type', 'any')
    difficulty = request.GET.get('difficulty', 'any')
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 15))
    random_flag = request.GET.get('random', 'false').lower() == 'true'

    # Default question types if 'any' is selected
    default_question_types = [
        'Cross-Text Connections', 'Text Structure and Purpose', 'Words in Context',
        'Rhetorical Synthesis', 'Transitions', 'Central Ideas and Details',
        'Command of Evidence', 'Inferences', 'Boundaries', 'Form, Structure, and Sense'
    ]

    # Filter questions based on type and difficulty
    if question_type != 'any':
        questions = Question.objects.filter(question_type=question_type).order_by('id')
    else:
        questions = Question.objects.filter(question_type__in=default_question_types).order_by('id')

    if difficulty != 'any':
        questions = questions.filter(difficulty=int(difficulty)).order_by('id')

    # Handle 'random' parameter to select random questions
    if random_flag:
        questions_list = list(questions)  # Convert queryset to list
        questions_list = sample(questions_list, min(page_size, len(questions_list)))  # Random sample
        paginator = Paginator(questions_list, page_size)
    else:
        paginator = Paginator(questions, page_size)

    questions_paginated = paginator.get_page(page)
    serializer = QuestionSerializer(questions_paginated, many=True)

    return Response({
        'questions': serializer.data,
        'total': paginator.count,
    })


@api_view(['POST'])
def edit_question(request, question_id):
    question = get_object_or_404(Question, id=question_id)
    data = request.data
    question.question = data['question']
    question.choice_a = data['choice_a']
    question.choice_b = data['choice_b']
    question.choice_c = data['choice_c']
    question.choice_d = data['choice_d']
    question.answer = data['answer']
    question.difficulty = data['difficulty']
    question.question_type = data['question_type']
    question.explanation = data['explanation']
    question.save()
    return JsonResponse({'status': 'success'})


@api_view(['POST'])
def create_question(request):
    data = request.data
    question = Question.objects.create(
        question=data['question'],
        choice_a=data['choice_a'],
        choice_b=data['choice_b'],
        choice_c=data['choice_c'],
        choice_d=data['choice_d'],
        answer=data['answer'],
        difficulty=data['difficulty'],
        question_type=data['question_type'],
        explanation=data['explanation']
    )
    question.save()
    return JsonResponse({'status': 'success'})


@api_view(['GET'])
def get_question(request, question_id):
    try:
        question = Question.objects.get(id=question_id)
        if question.sp_elo_rating == 0:
            question.save()  # This will trigger the save() logic and initialize sp_elo_rating
    except Question.DoesNotExist:
        return Response({'error': 'Question does not exist'}, status=404)
    serializer = QuestionSerializer(question)
    return Response(serializer.data)


def update_user_quest_progress(user, answer_is_correct):
    """Update quest progress when user answers a question correctly."""
    if not answer_is_correct:
        return

    # Get all active, uncompleted quests
    active_quests = PersonalizedQuest.objects.filter(
        user=user,
        completed=False,
        reward_claimed=False,
        end_time__gt=timezone.now()
    )

    for quest in active_quests:
        quest.progress += 1

        # Check if quest is completed
        if quest.progress >= quest.target:
            quest.progress = quest.target
            quest.completed = True

        quest.save()


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def check_answer(request):
    """Check if the submitted answer is correct."""
    try:
        data = request.data
        question_id = data.get('question_id')
        selected_choice = data.get('selected_choice')

        if not question_id or not selected_choice:
            return Response(
                {'error': 'Missing question_id or selected_choice'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            question = Question.objects.get(id=question_id)
        except Question.DoesNotExist:
            return Response(
                {'error': 'Question does not exist'},
                status=status.HTTP_404_NOT_FOUND
            )

        correct = (question.answer_text == selected_choice)

        # Update user statistics
        user = request.user
        user_stats, created = UserStatistics.objects.get_or_create(user=user)
        update_singleplayer_elo(user.profile, question, correct)

        if correct:
            user_stats.correct_number = F('correct_number') + 1
            user_stats.current_streak = F('current_streak') + 1
            # Update quest progress only for correct answers
            update_user_quest_progress(user, correct)
        else:
            user_stats.incorrect_number = F('incorrect_number') + 1
            user_stats.current_streak = 0

        user_stats.save()
        user_stats.refresh_from_db()

        return Response({
            'result': 'correct' if correct else 'incorrect',
            'status': status.HTTP_200_OK
        })

    except Exception as e:
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def update_singleplayer_elo(user_profile: Profile, question: Question, user_correct: bool):
    """
    Update both the user's singleplayer Elo (sp_elo_rating)
    and the question's Elo (sp_elo_rating) based on whether the user
    got the question correct (user_correct=True) or not.
    """

    # user Elo BEFORE
    user_elo_before = user_profile.sp_elo_rating
    # question Elo BEFORE
    question_elo_before = question.sp_elo_rating

    # Use your Elo-Davidson or standard Elo formula:
    # result for user = 1 if correct, else 0
    user_result = 1.0 if user_correct else 0.0
    question_result = 1.0 - user_result  # If user is correct, question "loses"

    # We can reuse your existing f(...) function:
    new_user_elo, new_question_elo = f(
        result=user_result,
        elo1=user_elo_before,
        elo2=question_elo_before,
        kappa=1,
        k=16  # or your chosen K-factor
    )

    # Assign and save
    user_profile.sp_elo_rating = int(new_user_elo)
    user_profile.save()

    question.sp_elo_rating = int(new_question_elo)
    question.save()


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


@api_view(['GET', 'POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def infinite_questions_profile_view(request):
    user = request.user
    alcumus_profile, created = UserStatistics.objects.get_or_create(user=user)

    if request.method == 'GET':
        serializer = InfiniteQuestionsSerializer(alcumus_profile)
        print(serializer.data)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = InfiniteQuestionsSerializer(alcumus_profile, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)


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


def sigma(r, kappa, s=400):
    """
    Calculate the sigma function used in the Elo-Davidson model.
    """
    exponent = 10 ** (r / s)
    return exponent / (10 ** (-r / s) + kappa + exponent)


def g_function(r, kappa, s=400):
    """
    Calculate the g(r; kappa) function.
    """
    exponent = 10 ** (r / s)
    return (exponent + kappa / 2) / (10 ** (-r / s) + kappa + exponent)


def f(result, elo1, elo2, kappa=1, k=32):
    """
    Update Elo ratings based on the result using the Elo-Davidson model.

    Parameters:
    result (float): 1 for win, 0.5 for draw, 0 for loss (Player 1's perspective).
    elo1 (float): Player 1's Elo rating before the game.
    elo2 (float): Player 2's Elo rating before the game.
    kappa (float): Parameter controlling draw probability. Default is 1.
    k (float): Learning rate or K-factor. Default is 32.

    Returns:
    new_elo1 (float): Player 1's updated Elo rating.
    new_elo2 (float): Player 2's updated Elo rating.
    """
    # Rating difference
    r_ab = elo1 - elo2

    # Expected score for player 1
    E1 = g_function(r_ab, kappa)
    E2 = 1 - E1  # Expected score for player 2

    # Update ratings
    new_elo1 = elo1 + k * (result - E1)
    new_elo2 = elo2 + k * ((1 - result) - E2)

    return new_elo1, new_elo2


def get_new_elo(result, elo1, elo2):
    result = result  # Draw
    elo1 = elo1  # Player 1's initial rating
    elo2 = elo2  # Player 2's initial rating
    kappa = 1  # Default draw adjustment parameter
    k = 16  # K-factor - adjust for how much it fluctuates after a result

    new_elo1, new_elo2 = f(result, elo1, elo2, kappa, k)
    return new_elo1, new_elo2


@api_view(['POST'])
def set_winner(request):
    data = request.data
    room_id = data.get('room_id')
    winner = data.get('winner')
    room = Room.objects.get(id=room_id)

    # profile1 = get_object_or_404(Profile, user=room.user1)
    # profile2 = get_object_or_404(Profile, user=room.user2)
    #
    # old_elo1 = profile1.elo_rating
    # old_elo2 = profile2.elo_rating
    #
    # print(old_elo1, old_elo2)

    if winner == 'Tie':
        # new_elo1, new_elo2 = get_new_elo(0.5, old_elo1, old_elo2)
        return Response({'status': 'success'})
    if room.user1.username == winner:
        # new_elo1, new_elo2 = get_new_elo(1, old_elo1, old_elo2)
        room.winner = room.user1
    else:
        # new_elo1, new_elo2 = get_new_elo(0, old_elo1, old_elo2)
        room.winner = room.user2

    # profile1.elo_rating = new_elo1
    # profile2.elo_rating = new_elo2
    # print(new_elo1, new_elo2, old_elo1, old_elo2)
    # profile1.save()
    # profile2.save()

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


@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def update_ranking(request, user_id):
    try:
        # Fetch the profile of the authenticated user
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)

        # Get the new streak value from the request data
    new_streak = request.data.get('max_streak')

    if new_streak is None:
        return Response({'error': 'max_streak is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Compare the new streak with the current max streak
    if new_streak > profile.max_streak:
        profile.max_streak = new_streak
        profile.save()
        return Response(ProfileSerializer(profile).data, status=status.HTTP_200_OK)

    return Response({'max_streak': profile.max_streak}, status=status.HTTP_200_OK)


@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def update_streak(request):
    try:
        # Fetch the profile of the authenticated user
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)

        # Get the new streak value from the request data
    new_streak = request.data.get('max_streak')

    if new_streak is None:
        return Response({'error': 'max_streak is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Compare the new streak with the current max streak
    if new_streak > profile.max_streak:
        profile.max_streak = new_streak
        profile.save()
        return Response(ProfileSerializer(profile).data, status=status.HTTP_200_OK)

    return Response({'max_streak': profile.max_streak}, status=status.HTTP_200_OK)


@api_view(['GET'])
def view_profile(request, user_id):
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=404)
    serializer = ProfileSerializer(user.profile)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_user_streak(request):
    user = request.user
    try:
        user_statistics = UserStatistics.objects.get(user=user)
        login_streak = user_statistics.login_streak
        return Response({"login_streak": login_streak})
    except UserStatistics.DoesNotExist:
        return Response({"error": "User statistics not found."}, status=404)


@ensure_csrf_cookie
def set_csrf_token(request):
    return JsonResponse({'detail': 'CSRF cookie set'})

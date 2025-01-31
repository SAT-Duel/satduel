from random import sample
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from api.models import Profile, PersonalizedQuest
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from api.views.serializers import QuestionSerializer
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


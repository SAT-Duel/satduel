from random import sample
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework_simplejwt.authentication import JWTAuthentication
from api.views.serializers import QuestionSerializer, QuestionAdminSerializer
from django.db import models
from ..models import Question
from rest_framework import status

ENGLISH_QUESTION_TYPES = [
    'Cross-Text Connections', 'Text Structure and Purpose', 'Words in Context',
    'Rhetorical Synthesis', 'Transitions', 'Central Ideas and Details',
    'Command of Evidence', 'Inferences', 'Boundaries', 'Form, Structure, and Sense'
]

MATH_QUESTION_TYPES = [
    'Linear equations in one variable',
    'Linear functions',
    'Linear equations in two variables',
    'Systems of two linear equations in two variables',
    'Linear inequalities in one or two variables',
    'Equivalent expressions',
    'Nonlinear equations in one variable and systems of equations in two variables',
    'Nonlinear functions',
    'Ratios, rates, proportional relationships, and units',
    'Percentages',
    'One-variable data: distributions and measures of center and spread',
    'Two-variable data: models and scatterplots',
    'Probability and conditional probability',
    'Inference from sample statistics and margin of error',
    'Evaluating statistical claims: observational studies and experiments',
    'Area and volume',
    'Lines, angles, and triangles',
    'Right triangles and trigonometry',
    'Circles',
]


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
    subject = request.GET.get('subject', 'english').lower()
    question_type = request.GET.get('type', 'any')
    difficulty = request.GET.get('difficulty', 'any')
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 15))
    random_flag = request.GET.get('random', 'false').lower() == 'true'

    default_question_types = MATH_QUESTION_TYPES if subject == 'math' else ENGLISH_QUESTION_TYPES

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
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminUser])
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
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminUser])
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
@authentication_classes([JWTAuthentication])
def get_question(request, question_id):
    try:
        question = Question.objects.get(id=question_id)
        if question.sp_elo_rating == 0:
            question.save()  # This will trigger the save() logic and initialize sp_elo_rating
    except Question.DoesNotExist:
        return Response({'error': 'Question does not exist'}, status=404)
    # Staff get answer/explanation (needed by the admin editor); everyone else
    # gets the public payload without them.
    if request.user.is_authenticated and request.user.is_staff:
        serializer = QuestionAdminSerializer(question)
    else:
        serializer = QuestionSerializer(question)
    return Response(serializer.data)


@api_view(['POST'])
def check_answer(request):
    """Grade a submitted answer.

    mode='practice' (authenticated): counts toward the daily free-tier quota,
    records a PracticeAttempt, and moves Elo on the user's first attempt at
    the question. Other calls (practice tests, diagnostic, review) just grade —
    they no longer batter the practice rating.
    """
    from api.views.practice_views import (
        apply_practice_elo, practice_stats_breakdown, practice_type_progress,
        quota_payload, record_practice_answer, subject_of,
    )
    from api.models import PracticeActiveQuestion
    from api.views.practice_views import SUBJECT_TYPES

    data = request.data
    question_id = data.get('question_id')
    selected_choice = data.get('selected_choice')
    mode = data.get('mode', '')

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
    is_practice = mode == 'practice' and request.user.is_authenticated
    payload = {'result': 'correct' if correct else 'incorrect', 'status': status.HTTP_200_OK}

    if is_practice:
        subject = subject_of(question)
        active_subject_questions = PracticeActiveQuestion.objects.filter(
            user=request.user,
            question__question_type__in=SUBJECT_TYPES[subject],
        )
        if active_subject_questions.exists() and not active_subject_questions.filter(question=question).exists():
            return Response(
                {'error': 'active_question_required',
                 'detail': 'Answer your current practice question before moving on.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        quota = quota_payload(request.user)
        if quota['remaining'] is not None and quota['remaining'] <= 0:
            return Response(
                {'error': 'daily_limit', 'quota': quota},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        from api.views.practice_views import practice_current_streak, update_daily_streak
        rating_update = apply_practice_elo(request.user, question, correct)
        record_practice_answer(request.user, question, correct, subject, selected_choice)
        payload['rated'] = rating_update['rated']
        payload['quota'] = quota_payload(request.user)
        payload['sp_elo_rating'] = rating_update['new_rating']
        payload['sp_elo_rating_previous'] = rating_update['previous_rating']
        payload['sp_elo_rating_delta'] = rating_update['delta']
        # Daily-goal streak: answering DAILY_PRACTICE_GOAL questions in a local
        # day completes it and extends the flame.
        payload['daily'] = update_daily_streak(request.user)
        payload['subject'] = subject
        payload['type_progress'] = practice_type_progress(request.user, [subject])
        active_subject_questions.filter(question=question).delete()

        # Best correct-answer run, shown on the streak leaderboard.
        profile = getattr(request.user, 'profile', None)
        if correct and profile:
            streak = practice_current_streak(request.user)
            if streak > profile.max_streak:
                profile.max_streak = streak
                profile.save(update_fields=['max_streak'])

    if request.user.is_authenticated:
        stats = practice_stats_breakdown(request.user)
        payload['practice_stats'] = {
            'correct_number': stats['practice_correct'],
            'incorrect_number': stats['practice_answered'] - stats['practice_correct'],
            'answered': stats['practice_answered'],
            **stats,
        }

    return Response(payload)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_answer(request):
    """Reveal a question's answer/explanation.

    Requires login, and refuses while the requester is actively competing on
    this question (open tournament participation or a live duel) so it can't
    be used to cheat mid-game.
    """
    data = request.data
    question_id = data.get('question_id')
    try:
        question = Question.objects.get(id=question_id)
    except Question.DoesNotExist:
        return Response({'error': 'Question does not exist'}, status=404)

    from api.models import TournamentParticipation, Room, TrackedQuestion
    in_active_tournament = TournamentParticipation.objects.filter(
        user=request.user,
        status='Active',
        tournament__questions=question,
    ).exists()
    active_duel = Room.objects.filter(
        status='Battling',
        questions=question,
    ).filter(models.Q(user1=request.user) | models.Q(user2=request.user)).exists()
    unanswered_duel_question = active_duel and TrackedQuestion.objects.filter(
        user=request.user,
        question=question,
        room__status='Battling',
        status='Blank',
    ).exists()
    if in_active_tournament or unanswered_duel_question:
        return Response(
            {'error': 'Answers are hidden while you are competing on this question.'},
            status=status.HTTP_403_FORBIDDEN,
        )

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
    """Day-streak snapshot (practice-completion based, not logins)."""
    from api.views.practice_views import daily_snapshot
    return Response(daily_snapshot(request.user))

import random
from django.contrib.auth.models import User
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.shortcuts import get_object_or_404
import string

from api.models import Tournament, TournamentParticipation, Question, TournamentQuestion, Profile
from api.views.serializers import TournamentSerializer, TournamentParticipationSerializer, TournamentQuestionSerializer, \
    ProfileSerializer, TPSubmitAnswerSerializer


@api_view(['GET', 'POST'])
def tournament_list(request):
    if request.method == 'GET':
        current_time = timezone.now()
        tournaments = Tournament.objects.filter(private=False, end_time__gt=current_time)
        serializer = TournamentSerializer(tournaments, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = TournamentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
def tournament_detail(request, pk):
    tournament = get_object_or_404(Tournament, pk=pk)
    if request.method == 'GET':
        serializer = TournamentSerializer(tournament)
        return Response(serializer.data)
    elif request.method == 'PUT':
        serializer = TournamentSerializer(tournament, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    elif request.method == 'DELETE':
        tournament.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def join_tournament(request, pk):
    tournament = get_object_or_404(Tournament, pk=pk)
    user = request.user
    duration = tournament.duration

    if TournamentParticipation.objects.filter(user=user, tournament=tournament).exists():
        participation = TournamentParticipation.objects.get(user=user, tournament=tournament)
        serializer = TournamentParticipationSerializer(participation)
        return Response(serializer.data, status=status.HTTP_200_OK)

    participation = TournamentParticipation.objects.create(
        user=user,
        tournament=tournament,
        start_time=timezone.now(),
        end_time=timezone.now() + duration,
        status='Active'
    )

    questions = tournament.questions.all()
    for question in questions:
        TournamentQuestion.objects.create(
            participation=participation,
            question=question,
            status='Blank'
        )

    serializer = TournamentParticipationSerializer(participation)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_participation(request, pk):
    user = request.user
    tournament = get_object_or_404(Tournament, pk=pk)
    participation = get_object_or_404(TournamentParticipation, user=user, tournament=tournament)
    serializer = TournamentParticipationSerializer(participation)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def get_tournament_questions(request, pk):
    user = request.user
    tournament = Tournament.objects.get(id=pk)
    participation = TournamentParticipation.objects.get(user=user, tournament=tournament)

    tournament_questions = TournamentQuestion.objects.filter(participation=participation).order_by('id')
    serializer = TournamentQuestionSerializer(tournament_questions, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def tournament_leaderboard(request, pk):
    tournament = get_object_or_404(Tournament, pk=pk)
    participations = TournamentParticipation.objects.filter(tournament=tournament).order_by('-score',
                                                                                            'last_correct_submission')
    serializer = TPSubmitAnswerSerializer(participations, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_answer(request, pk):
    tournament = get_object_or_404(Tournament, pk=pk)
    user = request.user
    participation = get_object_or_404(TournamentParticipation, user=user, tournament=tournament)
    data = request.data
    question_id = data.get('question_id')
    tournament_question_id = data.get('tournament_question_id')
    selected_choice = data.get('selected_choice')

    if not question_id or not selected_choice:
        return Response({"error": "Question ID and answer are required"}, status=status.HTTP_400_BAD_REQUEST)

    question = get_object_or_404(Question, id=question_id)
    tournament_question = get_object_or_404(TournamentQuestion, id=tournament_question_id)

    is_correct = question.answer_text == selected_choice
    time_taken = timezone.now() - participation.start_time

    tournament_question.status = 'Correct' if is_correct else 'Incorrect'
    tournament_question.time_taken = time_taken
    tournament_question.save()

    # Update the score of the user
    if is_correct:
        participation.score += 1
        participation.last_correct_submission = timezone.now() - participation.start_time
        participation.save()

    serializer = TournamentQuestionSerializer(tournament_question)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def finish_participation(request, pk):
    tournament = get_object_or_404(Tournament, pk=pk)
    user = request.user
    participation = get_object_or_404(TournamentParticipation, user=user, tournament=tournament)
    participation.status = 'Completed'
    participation.save()
    serializer = TournamentParticipationSerializer(participation)
    return Response(serializer.data)


def generate_unique_join_code():
    """Generate a unique 6-character alphanumeric join code."""
    code_length = 6
    characters = string.ascii_uppercase + string.digits
    while True:
        join_code = ''.join(random.choices(characters, k=code_length))
        if not Tournament.objects.filter(join_code=join_code).exists():
            return join_code

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_tournament(request):
    data = request.data
    questions_data = data['questions']

    join_code = generate_unique_join_code() if data['private'] else None

    tournament = Tournament.objects.create(
        name=data['name'],
        description=data['description'],
        start_time=data['start_time'],
        end_time=data['end_time'],
        private=data['private'],
        join_code=join_code,
    )

    for question in questions_data:
        question = Question.objects.create(
            question=question['question'],
            choice_a=question['choice_a'],
            choice_b=question['choice_b'],
            choice_c=question['choice_c'],
            choice_d=question['choice_d'],
            answer=question['answer'],
            difficulty=question['difficulty'],
            question_type=question.get('question_type', ''),  # Default empty string if not provided
            explanation=question.get('explanation', ''),  # Default empty string if not provided
        )
        tournament.questions.add(question)
    tournament.save()
    user = User.objects.get(id=request.user.id)
    user.my_tournaments.add(tournament)
    serializer = TournamentSerializer(tournament)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_tournament_admin(request):
    data = request.data
    join_code = generate_unique_join_code() if data.get('private', False) else None

    # Extract and validate the data
    question_ids = data['question_ids']
    tournament = Tournament.objects.create(
        name=data['name'],
        description=data['description'],
        start_time=data['start_time'],
        end_time=data['end_time'],
        private=data.get('private', False),
        duration=data.get('duration', 30),
        join_code=join_code,
    )

    # Associate the selected questions with the tournament
    questions = Question.objects.filter(id__in=question_ids)
    tournament.questions.set(questions)
    tournament.save()
    profile = Profile.objects.get(user=request.user)
    profile.my_tournaments.add(tournament)
    return JsonResponse({'join_code': tournament.join_code}, status=201)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tournament_history(request, id=None):
    if id:
        user = User.objects.get(id=id)
        participations = TournamentParticipation.objects.filter(user=user, status="Completed").order_by('-start_time')
        serializer = TournamentParticipationSerializer(participations, many=True)
        return Response(serializer.data)
    else:
        user = request.user
        participations = TournamentParticipation.objects.filter(user=user, status="Completed").order_by('-start_time')
        serializer = TournamentParticipationSerializer(participations, many=True)
        return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def join_from_code(request):
    data = request.data
    join_code = data.get('join_code', '').strip()
    try:
        tournament = Tournament.objects.get(join_code=join_code)
    except Tournament.DoesNotExist:
        return Response({"error": "Invalid join code. Please try again."}, status=status.HTTP_400_BAD_REQUEST)

    return Response({"id": tournament.id}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_tournaments(request):
    user = request.user
    profile = user.profile  # Assuming you have a one-to-one relationship
    tournaments = profile.my_tournaments.all()
    serializer = TournamentSerializer(tournaments, many=True)
    return Response(serializer.data)
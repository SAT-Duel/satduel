from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.shortcuts import get_object_or_404

from api.models import Tournament, TournamentParticipation, Question, TournamentQuestion, Profile
from api.serializers import TournamentSerializer, TournamentParticipationSerializer, TournamentQuestionSerializer, \
    ProfileSerializer


@api_view(['GET', 'POST'])
def tournament_list(request):
    if request.method == 'GET':
        tournaments = Tournament.objects.all()
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

    if TournamentParticipation.objects.filter(user=user, tournament=tournament).exists():
        return Response({"error": "Already joined this tournament"}, status=status.HTTP_400_BAD_REQUEST)

    participation = TournamentParticipation.objects.create(
        user=user,
        tournament=tournament,
        start_time=timezone.now()
    )

    questions = Tournament.questions.all()

    serializer = TournamentParticipationSerializer(participation)
    return Response(serializer.data, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def get_tournament_questions(request, pk):
    user = request.user
    tournament = Tournament.objects.get(id=pk)

    tournament_questions = TournamentQuestion.objects.filter(user=user, tournament=tournament).order_by(id)
    serializer = TournamentQuestionSerializer(tournament_questions)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tournament_leaderboard(request, pk):
    tournament = get_object_or_404(Tournament, pk=pk)
    participations = TournamentParticipation.objects.filter(tournament=tournament).order_by('-score')
    serializer = TournamentParticipationSerializer(participations, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_answer(request, pk):
    participation = get_object_or_404(TournamentParticipation, pk=pk)
    question_id = request.data.get('question_id')
    answer = request.data.get('answer')

    if not question_id or not answer:
        return Response({"error": "Question ID and answer are required"}, status=status.HTTP_400_BAD_REQUEST)

    question = get_object_or_404(Question, id=question_id)
    is_correct = question.answer == answer
    time_taken = timezone.now() - participation.start_time

    tournament_answer = TournamentQuestion.objects.create(
        participation=participation,
        question=question,
        answer=answer,
        is_correct=is_correct,
        time_taken=time_taken
    )

    if is_correct:
        participation.score += 1
        participation.save()

    serializer = TournamentQuestionSerializer(tournament_answer)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def finish_participation(request, pk):
    participation = get_object_or_404(TournamentParticipation, pk=pk)
    participation.end_time = timezone.now()
    participation.save()
    serializer = TournamentParticipationSerializer(participation)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_rating(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    new_rating = request.data.get('rating')

    if new_rating is None:
        return Response({"error": "New rating is required"}, status=status.HTTP_400_BAD_REQUEST)

    profile.rating = new_rating
    profile.save()

    serializer = ProfileSerializer(profile)
    return Response(serializer.data)
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import UserStatistics, PowerSprintStatistics, SurvivalStatistics
from api.serializers import InfiniteQuestionsSerializer, PowerSprintStatisticsSerializer, \
    SurvivalStatisticsSerializer

from random import randint, choice

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_infinite_question_stats(request):
    user = request.user
    stats, created = UserStatistics.objects.get_or_create(user=user)
    serializer = InfiniteQuestionsSerializer(stats)
    print(serializer.data)
    return Response(serializer.data)

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def set_infinite_question_stats(request):
    user = request.user
    data = request.data
    print(data)
    try:
        correct = int(data.get('correct_number', 0))
        incorrect = int(data.get('incorrect', 0))
        current_streak = int(data.get('current_streak', 0))
        xp = int(data.get('xp', 0))
        level = int(data.get('level', 0))
        coins = int(data.get('coins', 0))
        multiplier = float(data.get('multiplier', 1.00))
    except ValueError:
        return Response({'status': 'error', 'message': 'Invalid data types'}, status=400)

    # Update the statistics in the database
    stats, created = UserStatistics.objects.update_or_create(
        user=user,
        defaults={
            'correct_number': correct,
            'incorrect_number': incorrect,
            'current_streak': current_streak,
            'xp': xp,
            'level': level,
            'coins': coins,
            'multiplier': multiplier
        }
    )

    # Return only the status; lootbox logic is handled in the frontend
    return Response({
            'status': 'success'
        }, status=200)

@api_view(['GET'])
def get_power_sprint_stats(request):
    user = request.user
    stats = PowerSprintStatistics.objects.get(user=user)
    serializer = PowerSprintStatisticsSerializer(stats)
    return Response(serializer.data)

@api_view(['POST'])
def set_power_sprint_stats(request):
    user = request.user
    stats, created = PowerSprintStatistics.objects.get_or_create(user=user)
    serializer = PowerSprintStatisticsSerializer(stats, data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=400)

@api_view(['GET'])
def get_survival_stats(request):
    user = request.user
    stats = SurvivalStatistics.objects.get(user=user)
    serializer = SurvivalStatisticsSerializer(stats)
    return Response(serializer.data)

@api_view(['POST'])
def set_survival_stats(request):
    user = request.user
    stats, created = SurvivalStatistics.objects.get_or_create(user=user)
    serializer = SurvivalStatisticsSerializer(stats, data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=400)
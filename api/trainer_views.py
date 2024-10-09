from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import UserStatistics, PowerSprintStatistics, SurvivalStatistics
from api.serializers import InfiniteQuestionsSerializer, PowerSprintStatisticsSerializer, \
    SurvivalStatisticsSerializer

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_infinite_question_stats(request):
    user = request.user
    stats, created = UserStatistics.objects.get_or_create(user=user)

    # Use the total multiplier, which includes both the default and pet multipliers
    stats_data = InfiniteQuestionsSerializer(stats).data
    stats_data['multiplier'] = stats.total_multiplier()  # Set the total multiplier

    return Response(stats_data)

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
        # Don't get the multiplier from the data, calculate the total multiplier instead
    except ValueError:
        return Response({'status': 'error', 'message': 'Invalid data types'}, status=400)

    # Fetch the user's statistics and calculate the total multiplier
    stats, created = UserStatistics.objects.update_or_create(
        user=user,
        defaults={
            'correct_number': correct,
            'incorrect_number': incorrect,
            'current_streak': current_streak,
            'xp': xp,
            'level': level,
            'coins': coins,
        }
    )

    # Return only the status; lootbox logic is handled in the frontend
    return Response({
        'status': 'success',
        'multiplier': round(stats.total_multiplier(), 2)  # Send the total multiplier in the response
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

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import UserStatistics, PowerSprintStatistics, SurvivalStatistics
from api.views.practice_views import practice_stats_breakdown
from api.views.serializers import PowerSprintStatisticsSerializer, \
    SurvivalStatisticsSerializer

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_infinite_question_stats(request):
    user = request.user
    economy, _ = UserStatistics.objects.get_or_create(user=user)

    stats_data = practice_stats_breakdown(user)
    stats_data['correct_number'] = stats_data['practice_correct']
    stats_data['incorrect_number'] = stats_data['practice_answered'] - stats_data['practice_correct']
    stats_data['coins'] = economy.coins
    stats_data['multiplier'] = economy.total_multiplier()

    return Response(stats_data)

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

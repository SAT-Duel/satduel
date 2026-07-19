from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import UserStatistics
from api.views.practice_views import practice_stats_breakdown


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

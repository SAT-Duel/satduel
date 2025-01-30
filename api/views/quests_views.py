from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils import timezone
from api.models import UserStatistics, PersonalizedQuest
from .serializers import PersonalizedQuestSerializer


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_user_quests(request):
    """Get active quests for the user."""
    user = request.user
    active_quests = PersonalizedQuest.objects.filter(
        user=user,
        end_time__gt=timezone.now(),
        reward_claimed=False
    )

    serializer = PersonalizedQuestSerializer(active_quests, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def claim_quest_reward(request):
    """Claim reward for completed quest."""
    quest_id = request.data.get('quest_id')
    try:
        quest = PersonalizedQuest.objects.get(
            id=quest_id,
            user=request.user,
            completed=True,
            reward_claimed=False
        )
    except PersonalizedQuest.DoesNotExist:
        return Response(
            {'error': 'Quest not found or already claimed'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Update user statistics
    user_stats = UserStatistics.objects.get(user=request.user)
    user_stats.coins += quest.reward_coins
    user_stats.save()

    quest.reward_claimed = True
    quest.save()

    return Response({
        'message': 'Reward claimed successfully',
        'coins_earned': quest.reward_coins
    })

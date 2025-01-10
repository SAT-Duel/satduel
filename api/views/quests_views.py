from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils import timezone
from api.models import Quest, UserQuest, UserStatistics
from .serializers import QuestSerializer, UserQuestSerializer
from .serializers import UserQuestSerializer
from datetime import timedelta

def is_same_day(dt1, dt2):
    return dt1.date() == dt2.date()

def is_same_week(dt1, dt2):
    # Assuming the week starts on Monday
    return dt1.isocalendar()[1] == dt2.isocalendar()[1] and dt1.year == dt2.year


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_user_quests(request):
    user = request.user

    # Get all active quests for the user, including completed quests if reward has not been claimed
    user_quests = UserQuest.objects.filter(user=user, quest__is_active=True)

    # Process each quest to reset progress if needed
    for user_quest in user_quests:
        now = timezone.now()
        reset_quest = False

        # Reset conditions for different quest types
        if user_quest.is_completed and not user_quest.is_reward_claimed:
            if user_quest.quest.quest_type == 'daily' and not is_same_day(user_quest.last_completed, now):
                reset_quest = True
            elif user_quest.quest.quest_type == 'weekly' and not is_same_week(user_quest.last_completed, now):
                reset_quest = True

        # Reset if applicable
        if reset_quest:
            user_quest.progress = 0
            user_quest.is_completed = False
            user_quest.is_reward_claimed = False
            user_quest.last_completed = None
            user_quest.save()

    # Serialize and return quests, including those where reward has not yet been claimed
    serializer = UserQuestSerializer(user_quests, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def update_quest_progress(request):
    user = request.user
    quest_id = request.data.get('quest_id')
    progress_increment = request.data.get('progress_increment', 1)

    try:
        quest = Quest.objects.get(id=quest_id, is_active=True)
        user_quest, created = UserQuest.objects.get_or_create(user=user, quest=quest)
    except Quest.DoesNotExist:
        return Response({'detail': 'Quest not found or inactive.'}, status=status.HTTP_404_NOT_FOUND)

    if user_quest.is_completed:
        return Response({'detail': 'Quest already completed.'}, status=status.HTTP_400_BAD_REQUEST)

    user_quest.progress += progress_increment

    if user_quest.progress >= quest.target:
        user_quest.progress = quest.target
        user_quest.is_completed = True

        # Reward the user
        user_stats, _ = UserStatistics.objects.get_or_create(user=user)
        user_stats.xp += quest.reward_xp
        user_stats.coins += quest.reward_coins
        user_stats.save()

        # TODO: Handle reward_items if applicable

    user_quest.save()
    serializer = UserQuestSerializer(user_quest)
    return Response(serializer.data)

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def claim_quest_reward(request):
    user = request.user
    quest_id = request.data.get('quest_id')

    try:
        user_quest = UserQuest.objects.get(user=user, quest_id=quest_id, is_completed=True, is_reward_claimed=False)
    except UserQuest.DoesNotExist:
        return Response({'detail': 'Quest not completed or reward already claimed.'}, status=status.HTTP_404_NOT_FOUND)

    # Update user statistics
    user_stats, created = UserStatistics.objects.get_or_create(user=user)
    user_stats.xp += user_quest.quest.reward_xp
    user_stats.coins += user_quest.quest.reward_coins
    user_stats.save()

    # Mark the reward as claimed
    user_quest.is_reward_claimed = True
    user_quest.save()

    return Response({'detail': 'Reward claimed successfully.'})

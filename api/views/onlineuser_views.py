from django.http import JsonResponse
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.bot_duels import rotating_bot_users
from ..models import OnlineUser, TestPrepUserStats


def _player_payload(user, elo_rating, is_current_user=False):
    profile = user.profile
    return {
        'id': user.id,
        'username': user.username,
        'avatar': profile.avatar,
        'avatar_icon': profile.avatar_icon,
        'elo_rating': elo_rating,
        'is_current_user': is_current_user,
    }


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def update_online_status(request):
    user = request.user
    try:
        online_user, created = OnlineUser.objects.get_or_create(user=user)
        online_user.last_seen = timezone.now()
        online_user.save()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def remove_online_user(request):
    user = request.user
    try:
        OnlineUser.objects.filter(user=user).delete()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_online_users(request):
    test_prep = request.user.profile.active_test_prep_id
    threshold = timezone.now() - timezone.timedelta(seconds=15)
    real_users = [
        online.user for online in
        OnlineUser.objects.filter(last_seen__gte=threshold, user__profile__is_bot=False)
        .exclude(user=request.user)
        .select_related('user__profile')
    ]
    bot_users = rotating_bot_users()
    users = [request.user, *real_users, *bot_users]
    if test_prep == 'sat':
        ratings = {user.id: user.profile.elo_rating for user in users}
    else:
        ratings = dict(TestPrepUserStats.objects.filter(
            user__in=users, test_prep_id=test_prep,
        ).values_list('user_id', 'duel_elo'))
    users_list = (
        [_player_payload(request.user, ratings.get(request.user.id, 1500), is_current_user=True)]
        + [_player_payload(user, ratings.get(user.id, 1500)) for user in real_users + bot_users]
    )
    return JsonResponse({'users': users_list})

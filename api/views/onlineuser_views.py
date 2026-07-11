from django.http import JsonResponse
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.bot_duels import rotating_bot_users
from ..models import OnlineUser


def _player_payload(user, is_current_user=False):
    profile = user.profile
    return {
        'id': user.id,
        'username': user.username,
        'avatar': profile.avatar,
        'avatar_icon': profile.avatar_icon,
        'elo_rating': profile.elo_rating,
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
    threshold = timezone.now() - timezone.timedelta(seconds=15)
    real_users = [
        online.user for online in
        OnlineUser.objects.filter(last_seen__gte=threshold, user__profile__is_bot=False)
        .exclude(user=request.user)
        .select_related('user__profile')
    ]
    bot_users = rotating_bot_users()
    users_list = (
        [_player_payload(request.user, is_current_user=True)]
        + [_player_payload(user) for user in real_users + bot_users]
    )
    return JsonResponse({'users': users_list})

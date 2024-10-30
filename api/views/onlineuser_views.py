from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from ..models import OnlineUser


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
def get_online_users(request):
    threshold = timezone.now() - timezone.timedelta(seconds=15)  # Adjust the threshold as needed
    online_users = OnlineUser.objects.filter(last_seen__gte=threshold).select_related('user')
    users_list = [{'username': ou.user.username, 'status': 'Online'} for ou in online_users]
    return JsonResponse({'users': users_list})

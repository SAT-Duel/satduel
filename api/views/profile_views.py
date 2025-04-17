from venv import logger
from django.contrib.auth.models import User
from rest_framework.response import Response
from api.models import Profile, FriendRequest
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from api.views.serializers import ProfileSerializer, \
    ProfileBiographySerializer, UserSerializer, FriendRequestSerializer, \
    InfiniteQuestionsSerializer
from ..models import UserStatistics
from rest_framework import status


@api_view(['GET', 'PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def profile_view(request):
    try:
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = ProfileSerializer(profile)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        # Pass data directly without restructuring
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def update_biography(request):
    try:
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ProfileBiographySerializer(profile, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def update_ranking(request, user_id):
    try:
        # Fetch the profile of the authenticated user
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)

        # Get the new streak value from the request data
    new_streak = request.data.get('max_streak')

    if new_streak is None:
        return Response({'error': 'max_streak is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Compare the new streak with the current max streak
    if new_streak > profile.max_streak:
        profile.max_streak = new_streak
        profile.save()
        return Response(ProfileSerializer(profile).data, status=status.HTTP_200_OK)

    return Response({'max_streak': profile.max_streak}, status=status.HTTP_200_OK)


@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def update_streak(request):
    try:
        # Fetch the profile of the authenticated user
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)

        # Get the new streak value from the request data
    new_streak = request.data.get('max_streak')

    if new_streak is None:
        return Response({'error': 'max_streak is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Compare the new streak with the current max streak
    if new_streak > profile.max_streak:
        profile.max_streak = new_streak
        profile.save()
        return Response(ProfileSerializer(profile).data, status=status.HTTP_200_OK)

    return Response({'max_streak': profile.max_streak}, status=status.HTTP_200_OK)


@api_view(['GET'])
def search_users(request):
    query = request.query_params.get('q', '')
    users = User.objects.filter(username__icontains=query)
    serializer = UserSerializer(users, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def send_friend_request(request):
    from_user = request.user
    to_user_id = request.data.get('to_user_id')
    try:
        to_user = User.objects.get(id=to_user_id)
        if FriendRequest.objects.filter(from_user=from_user, to_user=to_user, status='pending').exists():
            return Response({'detail': 'Friend request already sent.'}, status=status.HTTP_400_BAD_REQUEST)
        if from_user == to_user:
            return Response({'detail': 'You cannot send friend request to yourself.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if from_user.profile.friends.filter(id=to_user_id).exists():
            return Response({'detail': 'You are already friends.'}, status=status.HTTP_400_BAD_REQUEST)
        FriendRequest.objects.create(from_user=from_user, to_user=to_user)
        return Response({'detail': 'Friend request sent.'}, status=status.HTTP_201_CREATED)
    except User.DoesNotExist:
        return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def respond_friend_request(request, request_id):
    try:
        friend_request = FriendRequest.objects.get(id=request_id)
        status_response = request.data.get('status')
        if status_response == 'accepted':
            friend_request.accept()
        elif status_response == 'rejected':
            friend_request.reject()
        else:
            return Response({'detail': 'Invalid status.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': f'Friend request {status_response}.'}, status=status.HTTP_200_OK)
    except FriendRequest.DoesNotExist:
        return Response({'detail': 'Friend request not found.'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def list_friend_requests(request):
    friend_requests = FriendRequest.objects.filter(to_user=request.user, status='pending')
    serializer = FriendRequestSerializer(friend_requests, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def list_friends(request):
    user = request.user
    friends = user.profile.friends.all()
    profiles = Profile.objects.filter(user__in=friends)
    serializer = ProfileSerializer(profiles, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def view_profile(request, user_id):
    try:
        user = User.objects.get(id=user_id)
        profile = Profile.objects.get(user=user)

        statistics = None
        if user.infinitequestionstatistics:
            statistics = UserStatistics.objects.get(user=user)

        # Aggregate all data
        data = {
            'profile': ProfileSerializer(profile).data,
            'statistics': InfiniteQuestionsSerializer(statistics).data if statistics else None,
        }

        return Response(data)

    except User.DoesNotExist:
        return Response(
            {'error': 'User not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error fetching profile: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def infinite_questions_profile_view(request):
    user = request.user
    alcumus_profile, created = UserStatistics.objects.get_or_create(user=user)

    if request.method == 'GET':
        serializer = InfiniteQuestionsSerializer(alcumus_profile)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = InfiniteQuestionsSerializer(alcumus_profile, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def update_first_login(request):
    """Update user's first login status"""
    try:
        profile = Profile.objects.get(user=request.user)
        profile.is_first_login = False
        profile.save()
        return Response({'status': 'success'})
    except Profile.DoesNotExist:
        return Response(
            {'error': 'Profile not found'},
            status=status.HTTP_404_NOT_FOUND
        )

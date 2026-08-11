from datetime import timedelta
import re

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.response import Response
from api.models import DEFAULT_TEST_PREP, DirectMessage, Profile, FriendRequest, PracticeStats, TestPrepUserStats
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from api.views.serializers import ProfileSerializer, \
    DuelUserSerializer, UserSerializer, FriendRequestSerializer
from rest_framework import status
from api.views.practice_views import practice_activity, practice_stats_breakdown

USERNAME_CHANGE_COOLDOWN = timedelta(days=30)
USERNAME_RULE = re.compile(r'^[a-zA-Z0-9_]{1,15}$')

LEADERBOARD_METRICS = {
    'duel': {
        'field': 'exam_elo',
        'ordering': ('-exam_elo', '-english_elo', 'user__username'),
    },
    'practice': {
        'field': 'english_elo',
        'ordering': ('-english_elo', '-exam_elo', 'user__username'),
    },
    'practice_math': {
        'field': 'math_elo',
        'ordering': ('-math_elo', '-exam_elo', 'user__username'),
    },
    'streak': {
        'field': 'exam_max_streak',
        'ordering': ('-exam_max_streak', '-english_elo', '-exam_elo', 'user__username'),
    },
}


def _stats_subquery(field, subject, default, test_prep=DEFAULT_TEST_PREP):
    return Coalesce(
        Subquery(
            PracticeStats.objects.filter(
                user=OuterRef('user_id'), test_prep_id=test_prep, subject=subject,
            ).values(field)[:1],
            output_field=IntegerField(),
        ),
        default,
    )


def _annotated_profiles(include_bots=False, test_prep=DEFAULT_TEST_PREP):
    """Profiles with per-subject practice stats attached for ranking/display."""
    profiles = Profile.objects.select_related('user')
    if not include_bots:
        profiles = profiles.filter(is_bot=False)
    if test_prep != DEFAULT_TEST_PREP:
        profiles = profiles.filter(
            Q(active_test_prep_id=test_prep) | Q(user__test_prep_stats__test_prep_id=test_prep),
        ).distinct()
    if test_prep == DEFAULT_TEST_PREP:
        exam_elo = F('elo_rating')
        exam_max_streak = F('max_streak')
    else:
        exam_elo = Coalesce(Subquery(
            TestPrepUserStats.objects.filter(
                user=OuterRef('user_id'), test_prep_id=test_prep,
            ).values('duel_elo')[:1], output_field=IntegerField(),
        ), Value(1500))
        exam_max_streak = Coalesce(Subquery(
            TestPrepUserStats.objects.filter(
                user=OuterRef('user_id'), test_prep_id=test_prep,
            ).values('max_streak')[:1], output_field=IntegerField(),
        ), Value(0))
    return profiles.annotate(
        exam_elo=exam_elo,
        exam_max_streak=exam_max_streak,
        english_elo=_stats_subquery('elo', 'english', 1200, test_prep),
        math_elo=_stats_subquery('elo', 'math', 1200, test_prep),
        english_answered_count=_stats_subquery('answered', 'english', 0, test_prep),
        math_answered_count=_stats_subquery('answered', 'math', 0, test_prep),
    )


def _practice_statistics_payload(user):
    breakdown = practice_stats_breakdown(user)
    breakdown['correct_number'] = breakdown['practice_correct']
    breakdown['incorrect_number'] = breakdown['practice_answered'] - breakdown['practice_correct']
    breakdown['activity'] = practice_activity(user)
    return breakdown


def _username_change_available_at(profile):
    if not profile.username_changed_at:
        return None
    return profile.username_changed_at + USERNAME_CHANGE_COOLDOWN


def _current_profile_payload(profile):
    profile.promote_grade_for_school_year()
    data = dict(ProfileSerializer(profile).data)
    available_at = _username_change_available_at(profile)
    data['account'] = {
        'has_usable_password': profile.user.has_usable_password(),
        'username_change_available_at': available_at.isoformat() if available_at else None,
    }
    data['onboarding'] = {
        'required': profile.onboarding_required,
        'grade_selected': profile.grade_selected,
        'username_finalized': profile.username_finalized,
        'sat_exam_date': profile.sat_exam_date.isoformat() if profile.sat_exam_date else None,
        'sat_exam_date_selected': profile.sat_exam_date_selected,
        'marketing_opt_in': profile.marketing_opt_in,
        'terms_accepted': profile.terms_accepted_at is not None,
    }
    return data


def _leaderboard_entry(profile, rank, metric):
    field = LEADERBOARD_METRICS[metric]['field']

    return {
        'rank': rank,
        'metric': metric,
        'metric_value': getattr(profile, field),
        'user': {
            'id': profile.user.id,
            'username': profile.user.username,
            'first_name': profile.user.first_name,
            'last_name': profile.user.last_name,
        },
        'country': profile.country,
        'grade': profile.grade,
        'avatar': profile.avatar,
        'avatar_icon': profile.avatar_icon,
        'elo_rating': profile.exam_elo,
        'sp_elo_rating': profile.english_elo,
        'math_elo_rating': profile.math_elo,
        'max_streak': profile.exam_max_streak,
        'questions_answered': profile.english_answered_count + profile.math_answered_count,
        'english_answered': profile.english_answered_count,
        'math_answered': profile.math_answered_count,
        'is_premium': profile.has_premium,
    }


def _leaderboard_limit(value):
    try:
        return min(max(int(value), 1), 100)
    except (TypeError, ValueError):
        return 50


@api_view(['GET', 'PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def profile_view(request):
    try:
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(_current_profile_payload(profile))

    elif request.method == 'PATCH':
        # Pass data directly without restructuring
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(_current_profile_payload(profile), status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def update_username(request):
    username = str(request.data.get('username', '')).strip()
    if not USERNAME_RULE.fullmatch(username):
        return Response(
            {'error': 'Use 1–15 letters, numbers, or underscores.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        profile = Profile.objects.select_for_update().select_related('user').get(user=request.user)
    except Profile.DoesNotExist:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)

    if username == request.user.username:
        return Response({'error': 'Choose a different username.'}, status=status.HTTP_400_BAD_REQUEST)

    available_at = _username_change_available_at(profile)
    if available_at and available_at > timezone.now():
        return Response({
            'error': f'You can change your username again on {available_at.date():%B %d, %Y}.',
            'username_change_available_at': available_at.isoformat(),
        }, status=status.HTTP_429_TOO_MANY_REQUESTS)

    if User.objects.filter(username__iexact=username).exclude(pk=request.user.pk).exists():
        return Response({'error': 'That username is already taken.'}, status=status.HTTP_400_BAD_REQUEST)

    request.user.username = username
    request.user.save(update_fields=['username'])
    profile.username_changed_at = timezone.now()
    profile.save(update_fields=['username_changed_at'])
    available_at = _username_change_available_at(profile)
    return Response({
        'username': username,
        'username_change_available_at': available_at.isoformat(),
    })


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def leaderboard_view(request):
    metric = request.query_params.get('metric', 'duel')
    if metric not in LEADERBOARD_METRICS:
        return Response({'error': 'Invalid leaderboard metric.'}, status=status.HTTP_400_BAD_REQUEST)

    limit = _leaderboard_limit(request.query_params.get('limit'))
    ordering = LEADERBOARD_METRICS[metric]['ordering']
    test_prep = request.user.profile.active_test_prep_id
    ranked_profiles = list(_annotated_profiles(
        include_bots=metric == 'duel', test_prep=test_prep,
    ).order_by(*ordering))

    current_entry = None
    entries = []
    for rank, profile in enumerate(ranked_profiles, start=1):
        entry = _leaderboard_entry(profile, rank, metric)
        if rank <= limit:
            entries.append(entry)
        if profile.user_id == request.user.id:
            current_entry = entry

    return Response({
        'metric': metric,
        'test_prep': test_prep,
        'entries': entries,
        'current_user': current_entry,
        'total_users': len(ranked_profiles),
        'limit': limit,
    })


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
    users = User.objects.filter(username__icontains=query).exclude(id=request.user.id).select_related('profile')[:20]
    serializer = DuelUserSerializer(users, many=True)
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
        friend_request = FriendRequest.objects.get(
            id=request_id,
            to_user=request.user,
            status='pending',
        )
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
    incoming = FriendRequest.objects.filter(to_user=request.user, status='pending').select_related('from_user', 'to_user')
    incoming_data = FriendRequestSerializer(incoming, many=True).data
    if request.query_params.get('scope') != 'all':
        return Response(incoming_data)

    outgoing = FriendRequest.objects.filter(from_user=request.user, status='pending').select_related('from_user', 'to_user')
    return Response({
        'incoming': incoming_data,
        'outgoing': FriendRequestSerializer(outgoing, many=True).data,
    })


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def cancel_friend_request(request, request_id):
    deleted, _ = FriendRequest.objects.filter(
        id=request_id,
        from_user=request.user,
        status='pending',
    ).delete()
    if not deleted:
        return Response({'detail': 'Pending friend request not found.'}, status=status.HTTP_404_NOT_FOUND)
    return Response({'detail': 'Friend request cancelled.'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def list_friends(request):
    user = request.user
    friends = user.profile.friends.all()
    profiles = Profile.objects.filter(user__in=friends)
    serializer = ProfileSerializer(profiles, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def remove_friend(request):
    """Drop a friendship and permanently delete the pair's chat history."""
    user = request.user
    friend_id = request.data.get('friend_id')
    try:
        friend = User.objects.get(id=friend_id)
    except User.DoesNotExist:
        return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

    if friend == user:
        return Response({'detail': 'You cannot remove yourself.'}, status=status.HTTP_400_BAD_REQUEST)
    if not user.profile.friends.filter(id=friend.id).exists():
        return Response({'detail': 'You are not friends with this user.'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        user.profile.friends.remove(friend)
        friend.profile.friends.remove(user)
        FriendRequest.objects.filter(
            Q(from_user=user, to_user=friend) | Q(from_user=friend, to_user=user)
        ).delete()
        DirectMessage.objects.filter(
            Q(sender=user, recipient=friend) | Q(sender=friend, recipient=user)
        ).delete()

    return Response({'detail': 'Friend removed.'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def view_profile(request, user_id):
    try:
        user = User.objects.get(id=user_id)
        profile = Profile.objects.get(user=user)

        data = {
            'profile': ProfileSerializer(profile).data,
            'statistics': _practice_statistics_payload(user),
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


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def infinite_questions_profile_view(request):
    return Response(_practice_statistics_payload(request.user))

"""Direct messages between friends.

Threads are derived from the DirectMessage rows for a pair of users rather than
stored as conversation objects. There is no websocket layer in this project, so
the client polls: the thread endpoint takes an `after` cursor and returns only
newer rows, which keeps an open chat cheap.
"""
from django.contrib.auth.models import User
from django.db.models import Case, Count, F, IntegerField, Max, Q, When
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import DirectMessage, FriendRequest, Profile
from api.views.serializers import DirectMessageSerializer, ProfileSerializer

# How many messages a thread returns without a cursor. Older messages load on
# demand via `before`.
THREAD_PAGE_SIZE = 50


def _thread_queryset(user, other):
    return DirectMessage.objects.filter(
        Q(sender=user, recipient=other) | Q(sender=other, recipient=user)
    )


def _are_friends(user, other):
    return user.profile.friends.filter(id=other.id).exists()


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def conversations(request):
    """Every friend, newest conversation first, with a preview and unread count.

    Friends with no messages yet are included so the messages page doubles as
    the place to start a chat.
    """
    user = request.user
    friends = list(user.profile.friends.all())
    if not friends:
        return Response([])

    friend_ids = [friend.id for friend in friends]
    profiles = {
        profile.user_id: profile
        for profile in Profile.objects.filter(user_id__in=friend_ids).select_related('user')
    }

    # Collapse both directions onto "the other person" so one aggregate gives
    # the newest message id and the unread tally for every conversation.
    other_id = Case(
        When(sender=user, then=F('recipient_id')),
        default=F('sender_id'),
        output_field=IntegerField(),
    )
    summaries = (
        DirectMessage.objects
        .filter(Q(sender=user, recipient_id__in=friend_ids) | Q(sender_id__in=friend_ids, recipient=user))
        .annotate(other_id=other_id)
        .values('other_id')
        .annotate(
            last_id=Max('id'),
            unread=Count('id', filter=Q(recipient=user, read_at__isnull=True)),
        )
    )
    summary_by_friend = {row['other_id']: row for row in summaries}
    latest = {
        message.id: message
        for message in DirectMessage.objects.filter(
            id__in=[row['last_id'] for row in summary_by_friend.values()]
        )
    }

    payload = []
    for friend_id in friend_ids:
        profile = profiles.get(friend_id)
        if profile is None:
            continue
        summary = summary_by_friend.get(friend_id)
        message = latest.get(summary['last_id']) if summary else None
        payload.append({
            'friend': ProfileSerializer(profile).data,
            'last_message': DirectMessageSerializer(message).data if message else None,
            'unread_count': summary['unread'] if summary else 0,
            '_sort_at': message.created_at if message else None,
        })

    # Active conversations float to the top; the rest stay alphabetical.
    payload.sort(
        key=lambda entry: (
            entry['_sort_at'] is None,
            -entry['_sort_at'].timestamp() if entry['_sort_at'] else 0,
            entry['friend']['user']['username'].lower(),
        )
    )
    for entry in payload:
        entry.pop('_sort_at')
    return Response(payload)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def thread(request, user_id):
    """Messages exchanged with one user.

    `after` returns only newer messages (the polling path). `before` pages
    backwards through history. Opening the thread marks their messages read.
    """
    user = request.user
    try:
        other = User.objects.select_related('profile').get(id=user_id)
    except User.DoesNotExist:
        return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

    if other == user:
        return Response({'detail': 'You cannot message yourself.'}, status=status.HTTP_400_BAD_REQUEST)

    queryset = _thread_queryset(user, other)
    after = request.query_params.get('after')
    before = request.query_params.get('before')

    if after:
        messages = list(queryset.filter(id__gt=after))
        has_more = False
    else:
        if before:
            queryset = queryset.filter(id__lt=before)
        # Slice from the end, then flip back to chronological for the client.
        page = list(queryset.order_by('-created_at', '-id')[:THREAD_PAGE_SIZE + 1])
        has_more = len(page) > THREAD_PAGE_SIZE
        messages = list(reversed(page[:THREAD_PAGE_SIZE]))

    # Reading the thread clears the unread badge for these messages.
    unread_ids = [m.id for m in messages if m.recipient_id == user.id and m.read_at is None]
    if unread_ids:
        now = timezone.now()
        DirectMessage.objects.filter(id__in=unread_ids).update(read_at=now)
        for message in messages:
            if message.id in unread_ids:
                message.read_at = now

    return Response({
        'friend': ProfileSerializer(other.profile).data,
        'is_friend': _are_friends(user, other),
        'messages': DirectMessageSerializer(messages, many=True).data,
        'has_more': has_more,
    })


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def send_message(request):
    user = request.user
    to_user_id = request.data.get('to_user_id')
    content = (request.data.get('content') or '').strip()

    if not content:
        return Response({'detail': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(content) > DirectMessage.MAX_LENGTH:
        return Response(
            {'detail': f'Messages are limited to {DirectMessage.MAX_LENGTH} characters.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        other = User.objects.select_related('profile').get(id=to_user_id)
    except User.DoesNotExist:
        return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

    if other == user:
        return Response({'detail': 'You cannot message yourself.'}, status=status.HTTP_400_BAD_REQUEST)
    if not _are_friends(user, other):
        return Response({'detail': 'You can only message your friends.'}, status=status.HTTP_403_FORBIDDEN)

    message = DirectMessage.objects.create(sender=user, recipient=other, content=content)
    return Response(DirectMessageSerializer(message).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def unread_count(request):
    """Small notification summary for the profile and friends entry points."""
    count = DirectMessage.objects.filter(recipient=request.user, read_at__isnull=True).count()
    friend_request_count = FriendRequest.objects.filter(to_user=request.user, status='pending').count()
    return Response({
        'unread_count': count,
        'friend_request_count': friend_request_count,
    })

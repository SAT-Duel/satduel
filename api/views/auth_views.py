"""
Unified authentication endpoints.

Both password login and Google login funnel through here and return the SAME
shape: {access, refresh, user}. This replaces the old two-request dance where
the frontend hit /api/login/ (session) and then /api/token/ (JWT) separately.

Google uses the Google Identity Services "id_token" (credential) flow: the
browser obtains a signed id_token from Google and posts it here; we verify it
against our OAuth client ID and issue our own JWTs. Accounts are linked by
verified email so a user can use Google and password interchangeably.
"""
import re

from django.conf import settings
from django.contrib.auth.models import User, update_last_login
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from api.models import Profile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokens_for_user(user):
    """Return (access, refresh) JWT strings for a user."""
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token), str(refresh)


def _user_payload(user, is_first_login):
    profile = getattr(user, 'profile', None)
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'is_admin': user.is_staff,
        'is_first_login': is_first_login,
        'role': profile.role if profile else 'STUDENT',
        'is_premium': bool(profile and profile.has_premium),
        'avatar': profile.avatar if profile else 'violet',
        'avatar_icon': profile.avatar_icon if profile else 'initial',
    }


def _has_verified_email(user):
    return EmailAddress.objects.filter(user=user, verified=True).exists()


def _generate_username(email):
    """Derive a unique, valid username from an email local-part."""
    base = re.sub(r'[^a-zA-Z0-9_]', '', email.split('@')[0])[:15] or 'user'
    username = base
    suffix = 0
    while User.objects.filter(username=username).exists():
        suffix += 1
        tail = str(suffix)
        username = f'{base[:15 - len(tail)]}{tail}'
    return username


def _issue_login_response(user, extra=None):
    """Compute first-login flag, bump last_login, and build the token response."""
    is_first_login = user.last_login is None
    update_last_login(None, user)
    access, refresh = _tokens_for_user(user)
    payload = _user_payload(user, is_first_login)
    if extra:
        payload.update(extra)
    return Response(
        {'access': access, 'refresh': refresh, 'user': payload},
        status=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# Password login
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    """Authenticate with username-or-email + password, return JWTs + user."""
    identifier = request.data.get('username') or request.data.get('email')
    password = request.data.get('password')

    if not identifier or not password:
        return Response(
            {'error': 'Username/email and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # The allauth backend resolves email logins; ModelBackend resolves usernames.
    from django.contrib.auth import authenticate
    user = authenticate(request, username=identifier, password=password)

    if user is None:
        return Response(
            {'error': 'Invalid username/email or password.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not _has_verified_email(user):
        return Response(
            {'error': 'Please verify your email address before logging in.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    timezone_str = request.data.get('timezone')
    profile = getattr(user, 'profile', None)
    if timezone_str and profile:
        profile.timezone = timezone_str
        profile.save(update_fields=['timezone'])

    return _issue_login_response(user)


# ---------------------------------------------------------------------------
# Google login
# ---------------------------------------------------------------------------

@transaction.atomic
def _get_or_create_google_user(email, first_name, last_name):
    """
    Resolve a Google identity to a local user, linking by verified email.

    Returns (user, created). Handles the 13 legacy duplicate-email accounts by
    preferring one with a verified EmailAddress, then the oldest.
    """
    verified = (
        EmailAddress.objects
        .filter(email__iexact=email, verified=True)
        .select_related('user')
        .order_by('user_id')
        .first()
    )
    if verified:
        return verified.user, False

    existing = User.objects.filter(email__iexact=email).order_by('id').first()
    if existing:
        # Google verified this email, so mark it verified locally too.
        ea, _ = EmailAddress.objects.get_or_create(
            user=existing,
            email=existing.email or email,
            defaults={'verified': True, 'primary': True},
        )
        if not ea.verified:
            ea.verified = True
            ea.save(update_fields=['verified'])
        return existing, False

    username = _generate_username(email)
    user = User.objects.create(
        username=username,
        email=email,
        first_name=(first_name or '')[:30],
        last_name=(last_name or '')[:30],
    )
    user.set_unusable_password()
    user.save()
    Profile.objects.get_or_create(
        user=user,
        defaults={'biography': "This user hasn't written anything yet."},
    )
    EmailAddress.objects.create(
        user=user, email=email, verified=True, primary=True,
    )
    return user, True


@api_view(['POST'])
@permission_classes([AllowAny])
def google_login(request):
    """Verify a Google id_token (credential) and return JWTs + user."""
    credential = (
        request.data.get('credential')
        or request.data.get('id_token')
        or request.data.get('access_token')
    )
    if not credential:
        return Response(
            {'error': 'Missing Google credential.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        idinfo = google_id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            settings.GOOGLE_OAUTH_CLIENT_ID,
        )
    except ValueError:
        return Response(
            {'error': 'Invalid or expired Google token.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not idinfo.get('email_verified'):
        return Response(
            {'error': 'Your Google account email is not verified.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    user, created = _get_or_create_google_user(
        idinfo['email'].lower(),
        idinfo.get('given_name', ''),
        idinfo.get('family_name', ''),
    )
    _link_social_account(user, idinfo)
    return _issue_login_response(user, extra={'is_new_user': created})


def _link_social_account(user, idinfo):
    """Record (or refresh) the allauth SocialAccount so Google usage is tracked."""
    uid = idinfo.get('sub')
    if not uid:
        return
    SocialAccount.objects.update_or_create(
        provider='google',
        uid=uid,
        defaults={'user': user, 'extra_data': idinfo},
    )


# ---------------------------------------------------------------------------
# Profile completion (grade) for new social signups
# ---------------------------------------------------------------------------

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def complete_profile(request):
    """Set the grade for a user that signed up without one (e.g. via Google)."""
    grade = str(request.data.get('grade', ''))
    valid_grades = {choice[0] for choice in Profile._meta.get_field('grade').choices}
    if grade not in valid_grades:
        return Response({'error': 'Invalid grade.'}, status=status.HTTP_400_BAD_REQUEST)

    profile = getattr(request.user, 'profile', None)
    if profile is None:
        return Response({'error': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    profile.grade = grade
    profile.save(update_fields=['grade'])
    return Response({'status': 'success', 'grade': profile.grade}, status=status.HTTP_200_OK)

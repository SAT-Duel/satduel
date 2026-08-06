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
from datetime import date, timedelta
import re
import uuid

from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User, update_last_login
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from api.account_deletion import AccountDeletionError, delete_user_account
from api.models import PendingRegistration, Profile, SATExamDate


REGISTRATION_TOKEN_SALT = 'satduel.pending-registration'
REGISTRATION_TOKEN_MAX_AGE = 60 * 60 * 24
REGISTRATION_RESEND_COOLDOWN = timedelta(seconds=60)


class RegistrationThrottle(AnonRateThrottle):
    rate = '10/hour'


class VerificationThrottle(AnonRateThrottle):
    rate = '30/hour'


class PendingRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)
    terms_accepted = serializers.BooleanField(write_only=True)
    next_path = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attrs):
        attrs['email'] = attrs['email'].strip().lower()
        if attrs['password1'] != attrs['password2']:
            raise serializers.ValidationError({'password2': 'Passwords do not match.'})
        if not re.search(r'[a-z]', attrs['password1']) or not re.search(r'[A-Z]', attrs['password1']) or not re.search(r'\d', attrs['password1']):
            raise serializers.ValidationError({
                'password1': 'Use at least one uppercase letter, one lowercase letter, and one number.',
            })
        if attrs['terms_accepted'] is not True:
            raise serializers.ValidationError({'terms_accepted': 'You must accept the Terms of Service to continue.'})
        if User.objects.filter(email__iexact=attrs['email']).exists():
            raise serializers.ValidationError({'email': 'An account with this email already exists. Sign in instead.'})
        next_path = attrs.get('next_path', '')
        if next_path and (not next_path.startswith('/') or next_path.startswith('//')):
            attrs['next_path'] = ''
        password_validation.validate_password(attrs['password1'], User(email=attrs['email']))
        return attrs


class AccountTokenRefreshSerializer(TokenRefreshSerializer):
    """Return 401 for deleted accounts or accounts without a verified email."""

    def validate(self, attrs):
        try:
            data = super().validate(attrs)
            token = RefreshToken(attrs['refresh'])
            user = User.objects.get(pk=token['user_id'])
        except User.DoesNotExist as exc:
            raise AuthenticationFailed(
                self.error_messages['no_active_account'],
                code='no_active_account',
            ) from exc
        if not _has_verified_email(user):
            raise AuthenticationFailed('Please verify your email address before logging in.')
        return data


class AccountTokenRefreshView(TokenRefreshView):
    serializer_class = AccountTokenRefreshSerializer


class VerifiedTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Keep the legacy token endpoint from bypassing email verification."""

    def validate(self, attrs):
        data = super().validate(attrs)
        if not _has_verified_email(self.user):
            raise AuthenticationFailed('Please verify your email address before logging in.')
        return data


class VerifiedTokenObtainPairView(TokenObtainPairView):
    serializer_class = VerifiedTokenObtainPairSerializer


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
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_admin': user.is_staff,
        'is_first_login': is_first_login,
        'role': profile.role if profile else 'STUDENT',
        'is_premium': bool(profile and profile.has_premium),
        'avatar': profile.avatar if profile else 'violet',
        'avatar_icon': profile.avatar_icon if profile else 'initial',
        'onboarding_required': bool(profile and profile.onboarding_required),
        'terms_accepted': bool(profile and profile.terms_accepted_at),
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


def _generate_provisional_username(token):
    base = f'student_{token.hex[:6]}'
    username = base
    suffix = 0
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f'{base[:15 - len(str(suffix))]}{suffix}'
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
        pending = PendingRegistration.objects.filter(email__iexact=str(identifier).strip()).first()
        if pending and check_password(password, pending.password_hash):
            return Response(
                {
                    'code': 'email_not_verified',
                    'error': 'Check your inbox and verify your email before logging in.',
                },
                status=status.HTTP_403_FORBIDDEN,
            )
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
# Password registration
# ---------------------------------------------------------------------------

def _send_registration_email(email, key):
    activate_url = f"{settings.FRONTEND_URL.rstrip('/')}/confirm-email/{key}/"
    message = (
        'Welcome to SAT Duel!\n\n'
        'Verify your email to create your account:\n'
        f'{activate_url}\n\n'
        'This link expires in 24 hours. If you did not request it, you can ignore this email.'
    )
    html_message = (
        '<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#1e293b">'
        '<h1 style="font-size:24px">Verify your SAT Duel email</h1>'
        '<p>One click creates your account. Until then, no username or public profile is reserved.</p>'
        f'<p><a href="{activate_url}" style="display:inline-block;padding:12px 18px;background:#7c5cf0;color:white;text-decoration:none;border-radius:10px;font-weight:700">Verify email</a></p>'
        '<p style="font-size:13px;color:#64748b">This link expires in 24 hours. If you did not request it, ignore this email.</p>'
        '</div>'
    )
    send_mail(
        'Verify your SAT Duel email',
        message,
        settings.DEFAULT_FROM_EMAIL,
        [email],
        html_message=html_message,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([RegistrationThrottle])
def register(request):
    """Email an ownership check without creating a User or Profile."""
    serializer = PendingRegistrationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    pending = PendingRegistration.objects.filter(email=data['email']).first()
    now = timezone.now()
    if pending and pending.email_sent_at and now - pending.email_sent_at < REGISTRATION_RESEND_COOLDOWN:
        retry_after = max(1, int((REGISTRATION_RESEND_COOLDOWN - (now - pending.email_sent_at)).total_seconds()))
        return Response(
            {'error': f'A verification email was just sent. Try again in {retry_after} seconds.', 'retry_after': retry_after},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    if pending:
        pending.password_hash = make_password(data['password1'])
        pending.verification_token = uuid.uuid4()
        pending.terms_accepted_at = now
        pending.next_path = data.get('next_path', '')
        pending.save()
    else:
        pending = PendingRegistration.objects.create(
            email=data['email'],
            password_hash=make_password(data['password1']),
            terms_accepted_at=now,
            next_path=data.get('next_path', ''),
        )

    key = signing.dumps(str(pending.verification_token), salt=REGISTRATION_TOKEN_SALT)
    _send_registration_email(pending.email, key)
    pending.email_sent_at = timezone.now()
    pending.save(update_fields=['email_sent_at'])
    return Response({'message': 'Check your email to finish creating your account.'}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([VerificationThrottle])
@transaction.atomic
def verify_registration(request):
    key = request.data.get('key', '')
    try:
        token = signing.loads(key, salt=REGISTRATION_TOKEN_SALT, max_age=REGISTRATION_TOKEN_MAX_AGE)
        pending = PendingRegistration.objects.select_for_update().get(verification_token=token)
    except signing.SignatureExpired:
        return Response({'error': 'This verification link has expired. Register again for a new one.'}, status=status.HTTP_400_BAD_REQUEST)
    except (signing.BadSignature, ValueError, PendingRegistration.DoesNotExist):
        return Response({'error': 'This verification link is invalid or has already been used.'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email__iexact=pending.email).exists():
        pending.delete()
        return Response({'error': 'An account with this email already exists. Sign in instead.'}, status=status.HTTP_409_CONFLICT)

    user = User.objects.create(
        username=_generate_provisional_username(pending.verification_token),
        email=pending.email,
        password=pending.password_hash,
    )
    Profile.objects.create(
        user=user,
        biography="This user hasn't written anything yet.",
        username_finalized=False,
        grade_selected=False,
        terms_accepted_at=pending.terms_accepted_at,
    )
    EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
    next_path = pending.next_path
    pending.delete()
    return _issue_login_response(user, extra={'next_path': next_path})


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
        defaults={
            'biography': "This user hasn't written anything yet.",
            'username_finalized': False,
            'grade_selected': False,
        },
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
# Account setup
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([AllowAny])
def sat_exam_dates(request):
    """Return the next six active weekend SAT dates maintained by staff."""
    dates = (
        SATExamDate.objects
        .filter(active=True, date__gte=timezone.localdate())
        .values_list('date', flat=True)[:6]
    )
    return Response({'dates': [exam_date.isoformat() for exam_date in dates]})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def complete_profile(request):
    """Save required onboarding choices for social and existing accounts."""
    try:
        profile = Profile.objects.select_for_update().select_related('user').get(user=request.user)
    except Profile.DoesNotExist:
        return Response({'error': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    if not _has_verified_email(request.user):
        return Response({'error': 'Verify your email before completing your profile.'}, status=status.HTTP_403_FORBIDDEN)

    identity_required = not profile.username_finalized or not profile.grade_selected

    if 'sat_exam_date' not in request.data:
        return Response({'error': 'Choose an SAT date or “I don’t know yet”.'}, status=status.HTTP_400_BAD_REQUEST)
    if not isinstance(request.data.get('marketing_opt_in'), bool):
        return Response({'error': 'Choose whether you want SAT Duel updates.'}, status=status.HTTP_400_BAD_REQUEST)
    if profile.terms_accepted_at is None and request.data.get('terms_accepted') is not True:
        return Response({'error': 'You must accept the Terms of Service to continue.'}, status=status.HTTP_400_BAD_REQUEST)

    sat_exam_date = request.data.get('sat_exam_date')
    if sat_exam_date is not None:
        try:
            sat_exam_date = date.fromisoformat(str(sat_exam_date))
        except ValueError:
            return Response({'error': 'Invalid SAT date.'}, status=status.HTTP_400_BAD_REQUEST)
        if not SATExamDate.objects.filter(
            date=sat_exam_date,
            date__gte=timezone.localdate(),
            active=True,
        ).exists():
            return Response({'error': 'Choose one of the available SAT dates.'}, status=status.HTTP_400_BAD_REQUEST)

    grade = request.data.get('grade')
    if grade is not None:
        grade = str(grade)
        valid_grades = {choice[0] for choice in Profile._meta.get_field('grade').choices}
        if grade not in valid_grades:
            return Response({'error': 'Invalid grade.'}, status=status.HTTP_400_BAD_REQUEST)
        profile.grade = grade
        profile.grade_selected = True
    elif not profile.grade_selected:
        return Response({'error': 'Please select your grade.'}, status=status.HTTP_400_BAD_REQUEST)

    username = request.data.get('username')
    if username is not None:
        username = str(username).strip()
        if profile.username_finalized and username != profile.user.username:
            return Response({'error': 'Use account settings to change your username.'}, status=status.HTTP_400_BAD_REQUEST)
        if not re.fullmatch(r'[a-zA-Z0-9_]{1,15}', username):
            return Response({'error': 'Use 1–15 letters, numbers, or underscores.'}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(username__iexact=username).exclude(pk=profile.user_id).exists():
            return Response({'error': 'That username is already taken.'}, status=status.HTTP_400_BAD_REQUEST)
        profile.user.username = username
        profile.username_finalized = True
    elif not profile.username_finalized:
        return Response({'error': 'Choose a username.'}, status=status.HTTP_400_BAD_REQUEST)

    first_name = str(request.data.get('first_name', profile.user.first_name)).strip()
    last_name = str(request.data.get('last_name', profile.user.last_name)).strip()
    if identity_required and (not first_name or not last_name or len(first_name) > 150 or len(last_name) > 150):
        return Response({'error': 'Enter your first and last name.'}, status=status.HTTP_400_BAD_REQUEST)
    profile.user.first_name = first_name
    profile.user.last_name = last_name
    profile.user.save(update_fields=['username', 'first_name', 'last_name'])

    profile.sat_exam_date = sat_exam_date
    profile.sat_exam_date_selected = True
    profile.marketing_opt_in = request.data['marketing_opt_in']
    if profile.terms_accepted_at is None:
        profile.terms_accepted_at = timezone.now()
    update_fields = [
        'sat_exam_date', 'sat_exam_date_selected', 'marketing_opt_in', 'terms_accepted_at',
        'username_finalized', 'grade_selected',
    ]
    if grade is not None:
        update_fields.append('grade')
    profile.save(update_fields=update_fields)
    return Response({
        'status': 'success',
        'username': profile.user.username,
        'first_name': profile.user.first_name,
        'last_name': profile.user.last_name,
        'grade': profile.grade,
        'sat_exam_date': profile.sat_exam_date.isoformat() if profile.sat_exam_date else None,
        'marketing_opt_in': profile.marketing_opt_in,
        'onboarding_required': profile.onboarding_required,
    })


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def set_password(request):
    """Let a verified Google-only account add its first password."""
    if request.user.has_usable_password():
        return Response(
            {'error': 'This account already has a password. Use password reset to change it.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    form = SetPasswordForm(request.user, request.data)
    if not form.is_valid():
        return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

    form.save()
    return Response({'message': 'Password set successfully.', 'has_usable_password': True})


@api_view(['DELETE'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def delete_account(request):
    """Permanently remove the authenticated user and their related data."""
    if request.data.get('confirmation') != 'DELETE':
        return Response(
            {'error': 'Type DELETE to confirm permanent account deletion.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        delete_user_account(request.user)
    except AccountDeletionError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(status=status.HTTP_204_NO_CONTENT)

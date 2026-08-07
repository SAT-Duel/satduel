import json
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.http import JsonResponse
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.http import require_POST
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from allauth.account.models import EmailAddress

from api.emails import send_password_changed_email, send_password_link_email


@csrf_exempt
def login_view(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        username = data.get('username')
        password = data.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if EmailAddress.objects.filter(user=user, verified=True).exists():
                is_first_login = user.last_login is None
                login(request, user)
                timezone = data.get('timezone')
                if timezone:
                    profile = user.profile
                    profile.timezone = timezone
                    profile.save()
                return JsonResponse({
                    'message': 'Logged In Successfully',
                    'username': user.username,
                    'email': user.email,
                    'id': user.id,
                    'is_admin': user.is_staff,
                    'is_first_login': is_first_login,
                    'role': user.profile.role,
                }, status=200)
            else:
                return JsonResponse({'error': 'Please verify your email address before logging in'}, status=401)
        else:
            return JsonResponse({'error': 'Invalid credentials'}, status=401)
    return JsonResponse({'error': 'Only POST method is allowed'}, status=405)


@require_POST  # Ensures that this view can only be accessed via POST request
@csrf_exempt  # Disables CSRF protection for this view
def logout_view(request):
    logout(request)
    return JsonResponse({'message': 'Logged out successfully'})


class PasswordResetThrottle(AnonRateThrottle):
    scope = 'password_reset'
    rate = '10/hour'


class PasswordResetRequestView(APIView):
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        email = str(request.data.get('email', '')).strip().lower()
        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        email_address = (
            EmailAddress.objects
            .filter(email__iexact=email, verified=True, user__is_active=True)
            .select_related('user')
            .order_by('user_id')
            .first()
        )
        if email_address:
            send_password_link_email(email_address.user)

        # Do not reveal whether an address has an account.
        return Response({"message": "If that account exists, a password link has been sent."}, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    def post(self, request, uidb64, token):
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is not None and default_token_generator.check_token(user, token):
            form = SetPasswordForm(user, request.data)
            if form.is_valid():
                form.save()
                send_password_changed_email(user)
                return Response({"message": "Password reset successful."}, status=status.HTTP_200_OK)
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)
        return Response({"error": "Invalid token or user ID."}, status=status.HTTP_400_BAD_REQUEST)

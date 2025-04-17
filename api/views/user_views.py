import json
from dj_rest_auth.registration.views import RegisterView
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.http import require_POST
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import Profile

from allauth.account.models import EmailAddress

from api.views.serializers import CustomRegisterSerializer
from satduel import settings


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


@csrf_exempt  # Disable CSRF for the API view (not recommended for production)
def register(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        username = data.get('username')
        email = data.get('email')
        first_name = data.get('first_name')
        last_name = data.get('last_name')
        password = data.get('password')
        grade = data.get('grade')

        if not all([username, email, first_name, last_name, password]):
            return JsonResponse({'error': 'All fields are required'}, status=400)

        if User.objects.filter(username=username).exists():
            return JsonResponse({'error': 'Username already exists'}, status=400)

        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password
        )
        Profile.objects.create(
            user=user,
            biography="This user is lazy and didn't write anything yet",
            grade=str(grade)
        )
        if user:
            login(request, user)
            return JsonResponse({
                'message': 'User registered and logged in successfully',
                'username': user.username,
                'email': user.email,
                'id': user.id,
                'is_admin': user.is_staff,
            }, status=201)

        else:
            return JsonResponse({'error': 'Registration successful but login failed'}, status=400)
    else:
        return JsonResponse({'error': 'Invalid HTTP method'}, status=405)


@method_decorator(csrf_exempt, name='dispatch')
class CustomRegisterView(RegisterView):
    serializer_class = CustomRegisterSerializer


class PasswordResetRequestView(APIView):
    def post(self, request):
        email = request.data.get('email')
        if email:
            form = PasswordResetForm({'email': email})
            if form.is_valid():
                form.save(
                    request=request,
                    use_https=True,
                    token_generator=default_token_generator,
                    from_email=None,
                    email_template_name='registration/password_reset_email.html',
                    subject_template_name='registration/password_reset_subject.txt',
                    domain_override=settings.FRONTEND_URL.replace("https://", ""),
                )
                return Response({"message": "Password reset link sent."}, status=status.HTTP_200_OK)
            return Response({"error": "Invalid email address."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)


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
                return Response({"message": "Password reset successful."}, status=status.HTTP_200_OK)
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)
        return Response({"error": "Invalid token or user ID."}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def set_goal(request):
    user = request.user
    data = json.loads(request.body)
    goal = data.get('goal')
    if goal:
        user.profile.goal = goal
        user.profile.save()
        return JsonResponse({'message': 'Goal set successfully'}, status=200)

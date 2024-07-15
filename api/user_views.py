import json

from dj_rest_auth.registration.views import RegisterView
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.http import require_POST
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.models import Profile

from allauth.account.models import EmailAddress

from api.serializers import CustomRegisterSerializer


@csrf_exempt
def login_view(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        username = data.get('username')
        password = data.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if EmailAddress.objects.filter(user=user, verified=True).exists():
                login(request, user)
                return JsonResponse({
                    'message': 'Logged In Successfully',
                    'username': user.username,
                    'email': user.email,
                    'id': user.id,
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
            biography='This user is lazy, he did not write anything yet',
            grade=grade
        )
        if user:
            login(request, user)
            return JsonResponse({
                'message': 'User registered and logged in successfully',
                'username': user.username,
                'email': user.email,
            }, status=201)

        else:
            return JsonResponse({'error': 'Registration successful but login failed'}, status=400)
    else:
        return JsonResponse({'error': 'Invalid HTTP method'}, status=405)




@method_decorator(csrf_exempt, name='dispatch')
class CustomRegisterView(RegisterView):
    serializer_class = CustomRegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save(request)
            email_address = EmailAddress.objects.filter(user=user).first()
            response_data = {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_active': user.is_active,
                'email_verified': email_address.verified if email_address else False
            }
            return Response(response_data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def perform_create(self, serializer):
        user = serializer.save(self.request)
        return user
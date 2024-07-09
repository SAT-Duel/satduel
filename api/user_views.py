import json

from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.http import require_POST

from api.models import Profile


@csrf_exempt
def login_view(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        username = data.get('username')
        password = data.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return JsonResponse({
                'message': 'Logged In Successfully',
                'username': user.username,
                'email': user.email,
                'id': user.id,
            }, status=200)
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
            grade= grade
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
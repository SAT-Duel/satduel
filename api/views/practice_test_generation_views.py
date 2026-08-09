"""Staff-only manual prompt workflow for isolated SAT test modules."""

from django.db import IntegrityError
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import PracticeTestModule
from api.practice_test_generation import build_module_prompt, validate_module_questions


def _summary(module):
    return {
        'id': module.id,
        'name': module.name,
        'subject': module.subject,
        'route': module.route,
        'question_count': module.question_count,
        'created_at': module.created_at.isoformat(),
    }


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminUser])
def practice_test_prompt(request):
    """Build a copyable prompt only; this workflow never calls an LLM API."""
    try:
        prompt = build_module_prompt(request.data.get('subject'), request.data.get('route'))
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'prompt': prompt})


@api_view(['GET', 'POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminUser])
def practice_test_modules(request):
    if request.method == 'GET':
        return Response({'modules': [_summary(module) for module in PracticeTestModule.objects.all()]})

    name = str(request.data.get('name', '')).strip()
    if not name:
        return Response({'error': 'Give this module a name'}, status=status.HTTP_400_BAD_REQUEST)
    if len(name) > 120:
        return Response({'error': 'Module names must be 120 characters or fewer'}, status=status.HTTP_400_BAD_REQUEST)
    subject = request.data.get('subject')
    route = request.data.get('route')
    try:
        questions = validate_module_questions(request.data.get('questions'), subject, route)
        module = PracticeTestModule.objects.create(
            name=name,
            subject=subject,
            route=route,
            questions=questions,
            created_by=request.user,
        )
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except IntegrityError:
        return Response({'error': 'A module with this name already exists'}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'module': _summary(module)}, status=status.HTTP_201_CREATED)

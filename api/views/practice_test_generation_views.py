"""Staff-only manual prompt workflow for isolated SAT test modules."""

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import PracticeTest, PracticeTestModule
from api.practice_test_generation import build_module_prompt, validate_module_questions


def _assigned_modules():
    assigned = {}
    for test in PracticeTest.objects.all():
        for field in ('english_a', 'english_b', 'english_c', 'math_a', 'math_b', 'math_c'):
            assigned[getattr(test, f'{field}_id')] = {'id': test.id, 'name': test.name}
    return assigned


def _summary(module, assigned=None):
    return {
        'id': module.id,
        'name': module.name,
        'subject': module.subject,
        'route': module.route,
        'question_count': module.question_count,
        'created_at': module.created_at.isoformat(),
        'assigned_test': (assigned or {}).get(module.id),
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
        assigned = _assigned_modules()
        return Response({'modules': [_summary(module, assigned) for module in PracticeTestModule.objects.all()]})

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


MODULE_FIELDS = {
    'english_a': ('english', 'A'),
    'english_b': ('english', 'B'),
    'english_c': ('english', 'C'),
    'math_a': ('math', 'A'),
    'math_b': ('math', 'B'),
    'math_c': ('math', 'C'),
}


def _test_summary(test):
    return {
        'id': test.id,
        'name': test.name,
        'active': test.active,
        'modules': {
            field: {'id': getattr(test, f'{field}_id'), 'name': getattr(test, field).name}
            for field in MODULE_FIELDS
        },
        'completion_count': getattr(test, 'completion_count', 0),
        'calibration_count': getattr(test, 'calibration_count', 0),
        'created_at': test.created_at.isoformat(),
    }


@api_view(['GET', 'POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminUser])
def practice_tests(request):
    if request.method == 'GET':
        tests = PracticeTest.objects.select_related(*MODULE_FIELDS).annotate(
            completion_count=Count('attempts__user', filter=Q(attempts__status='completed'), distinct=True),
            calibration_count=Count('attempts', filter=Q(attempts__contributes_to_calibration=True)),
        )
        assigned = _assigned_modules()
        return Response({
            'tests': [_test_summary(test) for test in tests],
            'modules': [_summary(module, assigned) for module in PracticeTestModule.objects.all()],
            'calibration_threshold': 500,
        })

    name = str(request.data.get('name', '')).strip()
    if not name:
        return Response({'error': 'Give this practice test a name'}, status=status.HTTP_400_BAD_REQUEST)
    if len(name) > 120:
        return Response({'error': 'Practice test names must be 120 characters or fewer'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        module_ids = {field: int(request.data.get(field)) for field in MODULE_FIELDS}
    except (TypeError, ValueError):
        return Response({'error': 'Select all six modules'}, status=status.HTTP_400_BAD_REQUEST)
    if len(set(module_ids.values())) != 6:
        return Response({'error': 'Each slot must use a different module'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            modules = {
                module.id: module
                for module in PracticeTestModule.objects.select_for_update().filter(id__in=module_ids.values())
            }
            if len(modules) != 6:
                raise ValueError('One or more selected modules no longer exist')
            values = {}
            for field, module_id in module_ids.items():
                module = modules[module_id]
                expected_subject, expected_route = MODULE_FIELDS[field]
                if (module.subject, module.route) != (expected_subject, expected_route):
                    raise ValueError(f'{field.replace("_", " ").title()} has the wrong subject or route')
                values[field] = module
            test = PracticeTest.objects.create(name=name, created_by=request.user, **values)
    except (ValueError, ValidationError) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
        return Response({'error': message}, status=status.HTTP_400_BAD_REQUEST)
    except IntegrityError:
        return Response(
            {'error': 'That name is already used, or one of these modules already belongs to a practice test'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    test.completion_count = 0
    test.calibration_count = 0
    return Response({'test': _test_summary(test)}, status=status.HTTP_201_CREATED)

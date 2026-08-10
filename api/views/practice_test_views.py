"""Student lifecycle endpoints for generated adaptive practice tests."""

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import PracticeTest, PracticeTestAttempt
from api.practice_test_scoring import SCORING_VERSION, answer_is_correct, score_section, select_second_module


MODULE_SECONDS = {'english': 32 * 60, 'math': 35 * 60}
BREAK_SECONDS = 10 * 60
ANNOTATION_COLORS = {'yellow', 'blue', 'pink'}
UNDERLINE_STYLES = {'none', 'solid', 'dashed', 'dotted'}
ANNOTATION_FIELDS = {'passage', 'prompt', 'choice:A', 'choice:B', 'choice:C', 'choice:D'}


def _module_for_phase(test, phase):
    return getattr(test, phase)


def _public_question(question):
    return {
        'id': question['order'],
        'order': question['order'],
        'response_type': question.get('response_type', 'multiple_choice'),
        'question': question['question'],
        'choices': [question.get(f'choice_{letter}', '') for letter in 'abcd'],
    }


def _valid_answers(module, raw):
    raw = raw if isinstance(raw, dict) else {}
    valid_keys = {str(question['order']) for question in module.questions}
    return {
        str(key): str(value).strip()[:100]
        for key, value in raw.items()
        if str(key) in valid_keys and value is not None
    }


def _valid_annotations(module, raw):
    raw = raw if isinstance(raw, dict) else {}
    valid_questions = {str(question['order']) for question in module.questions}
    cleaned = {}
    for question_key, tools in raw.items():
        question_key = str(question_key)
        if question_key not in valid_questions or not isinstance(tools, dict):
            continue

        marks = []
        for mark in tools.get('marks', [])[:100]:
            if not isinstance(mark, dict):
                continue
            try:
                start, end = int(mark.get('start')), int(mark.get('end'))
            except (TypeError, ValueError):
                continue
            field = mark.get('field')
            color = mark.get('color')
            underline = mark.get('underline', 'none')
            if field not in ANNOTATION_FIELDS or color not in ANNOTATION_COLORS:
                continue
            if underline not in UNDERLINE_STYLES or start < 0 or end <= start or end > 20000:
                continue
            marks.append({
                'id': str(mark.get('id', ''))[:64],
                'field': field,
                'start': start,
                'end': end,
                'color': color,
                'underline': underline,
            })

        crossed_out = tools.get('crossed_out', [])
        if not isinstance(crossed_out, list):
            crossed_out = []
        cleaned[question_key] = {
            'marks': marks,
            'crossed_out': sorted({str(letter) for letter in crossed_out if str(letter) in 'ABCD'}),
        }
    return cleaned


def _save_progress(attempt, data):
    module = _module_for_phase(attempt.practice_test, attempt.phase)
    answers = dict(attempt.answers)
    answers[attempt.phase] = _valid_answers(module, data.get('answers', answers.get(attempt.phase, {})))
    attempt.answers = answers

    limit = MODULE_SECONDS[module.subject]
    remaining = dict(attempt.remaining_seconds)
    try:
        seconds = int(data.get('remaining_seconds', remaining.get(attempt.phase, limit)))
    except (TypeError, ValueError):
        seconds = limit
    remaining[attempt.phase] = min(limit, max(0, seconds))
    attempt.remaining_seconds = remaining

    try:
        current = int(data.get('current_question', attempt.current_question))
    except (TypeError, ValueError):
        current = 1
    attempt.current_question = min(len(module.questions) + 1, max(1, current))

    review = data.get('review_questions', attempt.review_questions.get(attempt.phase, []))
    allowed = set(range(1, len(module.questions) + 1))
    if not isinstance(review, list):
        review = []
    all_review = dict(attempt.review_questions)
    all_review[attempt.phase] = sorted({int(item) for item in review if str(item).isdigit() and int(item) in allowed})
    attempt.review_questions = all_review

    annotations = dict(attempt.annotations)
    annotations[attempt.phase] = _valid_annotations(
        module,
        data.get('annotations', annotations.get(attempt.phase, {})),
    )
    attempt.annotations = annotations


def _question_responses(module, answers):
    return [(question, answers.get(str(question['order']))) for question in module.questions]


def _attempt_state(attempt):
    if attempt.status == PracticeTestAttempt.STATUS_COMPLETED:
        return {'attempt_id': attempt.id, 'completed': True}
    if attempt.phase == 'break':
        elapsed = (timezone.now() - attempt.break_started_at).total_seconds() if attempt.break_started_at else 0
        return {
            'attempt_id': attempt.id,
            'test_id': attempt.practice_test_id,
            'test_name': attempt.practice_test.name,
            'completed': False,
            'break': True,
            'break_remaining_seconds': max(0, BREAK_SECONDS - int(elapsed)),
        }
    module = _module_for_phase(attempt.practice_test, attempt.phase)
    subject_label = 'Reading and Writing' if module.subject == 'english' else 'Math'
    route_label = 'Module 1' if module.route == 'A' else 'Module 2'
    return {
        'attempt_id': attempt.id,
        'test_id': attempt.practice_test_id,
        'test_name': attempt.practice_test.name,
        'completed': False,
        'phase': attempt.phase,
        'eyebrow': route_label,
        'title': subject_label,
        'subject': module.subject,
        'status_label': 'Adaptive practice test',
        'questions': [_public_question(question) for question in module.questions],
        'answers': attempt.answers.get(attempt.phase, {}),
        'review_questions': attempt.review_questions.get(attempt.phase, []),
        'annotations': attempt.annotations.get(attempt.phase, {}),
        'current_question': attempt.current_question,
        'remaining_seconds': attempt.remaining_seconds.get(attempt.phase, MODULE_SECONDS[module.subject]),
        'time_limit_seconds': MODULE_SECONDS[module.subject],
        'section_number': 2 if module.subject == 'math' and attempt.practice_test.test_type == PracticeTest.TYPE_FULL else 1,
        'module_number': 1 if module.route == 'A' else 2,
    }


def _test_summary(test):
    active_attempt = next((attempt for attempt in test._user_attempts if attempt.status == 'active'), None)
    completed = [attempt for attempt in test._user_attempts if attempt.status == 'completed']
    return {
        'id': test.id,
        'name': test.name,
        'test_type': test.test_type,
        'question_count': test.delivered_question_count,
        'duration_minutes': test.duration_minutes,
        'maximum_score': test.maximum_score,
        'completion_count': test.completion_count,
        'calibration_count': test.calibration_count,
        'status': 'in_progress' if active_attempt else ('completed' if completed else 'not_started'),
        'active_attempt_id': active_attempt.id if active_attempt else None,
        'attempts_completed': len(completed),
    }


def _history_summary(attempt):
    details = attempt.score_details or {}
    return {
        'id': attempt.id,
        'test_id': attempt.practice_test_id,
        'test_name': attempt.practice_test.name,
        'test_type': attempt.practice_test.test_type,
        'maximum_score': attempt.practice_test.maximum_score,
        'score': attempt.total_score,
        'reading_writing_score': attempt.reading_writing_score,
        'math_score': attempt.math_score,
        'correct': details.get('correct', 0),
        'total': details.get('total') or attempt.practice_test.delivered_question_count,
        'created_at': attempt.completed_at.isoformat() if attempt.completed_at else attempt.updated_at.isoformat(),
    }


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def practice_tests(request):
    attempts = list(
        PracticeTestAttempt.objects.filter(user=request.user)
        .select_related('practice_test')
        .order_by('-created_at')
    )
    by_test = {}
    for attempt in attempts:
        by_test.setdefault(attempt.practice_test_id, []).append(attempt)

    tests = list(
        PracticeTest.objects.filter(active=True)
        .select_related('english_a', 'english_b', 'english_c', 'math_a', 'math_b', 'math_c')
        .annotate(
            completion_count=Count('attempts__user', filter=Q(attempts__status='completed'), distinct=True),
            calibration_count=Count('attempts', filter=Q(attempts__contributes_to_calibration=True)),
        )
    )
    for test in tests:
        test._user_attempts = by_test.get(test.id, [])

    history = [_history_summary(attempt) for attempt in attempts if attempt.status == 'completed']
    return Response({
        'tests': [_test_summary(test) for test in tests],
        'history': {
            'results': history,
            'tests_taken': len(history),
        },
    })


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def start_test(request, test_id):
    test = PracticeTest.objects.filter(id=test_id, active=True).first()
    if not test:
        return Response({'error': 'Practice test not found'}, status=status.HTTP_404_NOT_FOUND)
    with transaction.atomic():
        attempt, _ = PracticeTestAttempt.objects.get_or_create(
            user=request.user, practice_test=test, status='active',
            defaults={'phase': 'math_a' if test.test_type == PracticeTest.TYPE_MATH else 'english_a'},
        )
    return Response(_attempt_state(attempt), status=status.HTTP_200_OK)


def _attempt_queryset(user, attempt_id, lock=False):
    """Load an attempt with its modules, optionally locking the attempt row.

    Single-subject tests leave the other subject's slots empty, so every
    module foreign key is nullable and select_related() reaches them through
    LEFT OUTER JOINs. PostgreSQL refuses to apply FOR UPDATE to the nullable
    side of an outer join, so the lock has to name the attempt row itself.
    """
    query = PracticeTestAttempt.objects.select_related(
        'practice_test__english_a', 'practice_test__english_b', 'practice_test__english_c',
        'practice_test__math_a', 'practice_test__math_b', 'practice_test__math_c',
    ).filter(id=attempt_id, user=user)
    if lock:
        query = query.select_for_update(of=('self',))
    return query


def _owned_active_attempt(request, attempt_id, lock=False):
    return _attempt_queryset(request.user, attempt_id, lock=lock).first()


@api_view(['GET', 'PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def attempt_progress(request, attempt_id):
    attempt = _owned_active_attempt(request, attempt_id)
    if not attempt:
        return Response({'error': 'Attempt not found'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response(_attempt_state(attempt))
    if attempt.status != 'active':
        return Response({'error': 'This attempt is already complete'}, status=status.HTTP_409_CONFLICT)
    if attempt.phase == 'break' or request.data.get('phase') not in (None, attempt.phase):
        return Response({'error': 'The test has moved to another section'}, status=status.HTTP_409_CONFLICT)
    _save_progress(attempt, request.data)
    attempt.save(update_fields=[
        'answers', 'review_questions', 'annotations', 'remaining_seconds', 'current_question', 'updated_at',
    ])
    return Response(_attempt_state(attempt))


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def restart_test(request, attempt_id):
    with transaction.atomic():
        attempt = _owned_active_attempt(request, attempt_id, lock=True)
        if not attempt:
            return Response({'error': 'Attempt not found'}, status=status.HTTP_404_NOT_FOUND)
        if attempt.status != 'active':
            return Response({'error': 'Completed attempts cannot be deleted'}, status=status.HTTP_409_CONFLICT)
        test = attempt.practice_test
        attempt.delete()
        fresh = PracticeTestAttempt.objects.create(
            user=request.user,
            practice_test=test,
            phase='math_a' if test.test_type == PracticeTest.TYPE_MATH else 'english_a',
        )
    return Response(_attempt_state(fresh))


def _complete_attempt(attempt):
    test = attempt.practice_test
    section_scores = {}
    for subject in test.included_subjects:
        route = attempt.selected_routes[subject].lower()
        modules = [
            (f'{subject}_a', getattr(test, f'{subject}_a')),
            (f'{subject}_{route}', getattr(test, f'{subject}_{route}')),
        ]
        responses = [
            pair
            for phase, module in modules
            for pair in _question_responses(module, attempt.answers.get(phase, {}))
        ]
        section_scores[subject] = score_section(responses)

    reading_writing = section_scores.get('english')
    math = section_scores.get('math')
    first_completion = not PracticeTestAttempt.objects.filter(
        user=attempt.user,
        practice_test=attempt.practice_test,
        contributes_to_calibration=True,
    ).exclude(id=attempt.id).exists()
    attempt.reading_writing_score = reading_writing['score'] if reading_writing else None
    attempt.math_score = math['score'] if math else None
    attempt.total_score = sum(section['score'] for section in section_scores.values())
    attempt.score_details = {
        'reading_writing': reading_writing or {},
        'math': math or {},
        'correct': sum(section['correct'] for section in section_scores.values()),
        'total': sum(section['total'] for section in section_scores.values()),
        'score_low': sum(section['score_low'] for section in section_scores.values()),
        'score_high': sum(section['score_high'] for section in section_scores.values()),
        'scoring_version': SCORING_VERSION,
    }
    attempt.status = 'completed'
    attempt.phase = 'completed'
    attempt.current_question = 1
    attempt.completed_at = timezone.now()
    attempt.contributes_to_calibration = first_completion


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def finish_module(request, attempt_id):
    with transaction.atomic():
        attempt = _owned_active_attempt(request, attempt_id, lock=True)
        if not attempt:
            return Response({'error': 'Attempt not found'}, status=status.HTTP_404_NOT_FOUND)
        if attempt.status != 'active':
            return Response(_attempt_state(attempt))
        if attempt.phase == 'break' or request.data.get('phase') not in (None, attempt.phase):
            return Response({'error': 'The test has moved to another section'}, status=status.HTTP_409_CONFLICT)

        phase = attempt.phase
        module = _module_for_phase(attempt.practice_test, phase)
        _save_progress(attempt, request.data)
        phase_answers = attempt.answers.get(phase, {})

        if phase == 'english_a':
            route = select_second_module(_question_responses(module, phase_answers))
            attempt.selected_routes = {**attempt.selected_routes, 'english': route}
            attempt.phase = f'english_{route.lower()}'
        elif phase.startswith('english_'):
            if attempt.practice_test.test_type == PracticeTest.TYPE_FULL:
                attempt.phase = 'break'
                attempt.break_started_at = timezone.now()
            else:
                _complete_attempt(attempt)
        elif phase == 'math_a':
            route = select_second_module(_question_responses(module, phase_answers))
            attempt.selected_routes = {**attempt.selected_routes, 'math': route}
            attempt.phase = f'math_{route.lower()}'
        elif phase.startswith('math_'):
            _complete_attempt(attempt)
        else:
            return Response({'error': 'Invalid attempt state'}, status=status.HTTP_409_CONFLICT)

        attempt.current_question = 1
        attempt.save()
    return Response(_attempt_state(attempt))


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def resume_after_break(request, attempt_id):
    with transaction.atomic():
        attempt = _owned_active_attempt(request, attempt_id, lock=True)
        if not attempt:
            return Response({'error': 'Attempt not found'}, status=status.HTTP_404_NOT_FOUND)
        if attempt.status != 'active' or attempt.phase != 'break':
            return Response({'error': 'This attempt is not on a break'}, status=status.HTTP_409_CONFLICT)
        attempt.phase = 'math_a'
        attempt.break_started_at = None
        attempt.current_question = 1
        attempt.save(update_fields=['phase', 'break_started_at', 'current_question', 'updated_at'])
    return Response(_attempt_state(attempt))


def _review_question(phase, question, answers):
    response = answers.get(str(question['order']))
    return {
        'id': f"{phase}:{question['order']}",
        'phase': phase,
        'order': question['order'],
        'response_type': question.get('response_type', 'multiple_choice'),
        'question': question['question'],
        'choices': [question.get(f'choice_{letter}', '') for letter in 'abcd'],
        'answer': question['answer'],
        'user_answer': response,
        'correct': answer_is_correct(question, response),
        'explanation': question.get('explanation', ''),
    }


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def test_result(request, attempt_id):
    attempt = _owned_active_attempt(request, attempt_id)
    if not attempt:
        return Response({'error': 'Attempt not found'}, status=status.HTTP_404_NOT_FOUND)
    if attempt.status != 'completed':
        return Response({'error': 'Finish the test before viewing its score'}, status=status.HTTP_409_CONFLICT)

    test = attempt.practice_test
    phases = []
    for subject in test.included_subjects:
        route = attempt.selected_routes[subject].lower()
        phases.extend([
            (f'{subject}_a', getattr(test, f'{subject}_a')),
            (f'{subject}_{route}', getattr(test, f'{subject}_{route}')),
        ])
    questions = [
        _review_question(phase, question, attempt.answers.get(phase, {}))
        for phase, module in phases
        for question in module.questions
    ]
    details = attempt.score_details
    return Response({
        'id': attempt.id,
        'test_name': test.name,
        'test_type': test.test_type,
        'maximum_score': test.maximum_score,
        'total_score': attempt.total_score,
        'reading_writing_score': attempt.reading_writing_score,
        'math_score': attempt.math_score,
        'score_low': details.get('score_low'),
        'score_high': details.get('score_high'),
        'reading_writing': details.get('reading_writing', {}),
        'math': details.get('math', {}),
        'correct': details.get('correct'),
        'total': details.get('total'),
        'selected_routes': attempt.selected_routes,
        'contributed_to_calibration': attempt.contributes_to_calibration,
        'completed_at': attempt.completed_at.isoformat(),
        'questions': questions,
    })

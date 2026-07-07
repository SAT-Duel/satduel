"""Admin endpoints for AI-assisted question generation."""

from django.db.models import Count
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication

from api import generation
from api.models import Question


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminUser])
def generation_taxonomy(request):
    """The math taxonomy plus current per-skill question counts in the bank."""
    counts = dict(
        Question.objects.values_list('question_type')
        .annotate(n=Count('id'))
        .values_list('question_type', 'n')
    )
    domains = [
        {
            'name': d['name'],
            'share': d['share'],
            'skills': [
                {
                    'name': s['name'],
                    'blurb': s['blurb'],
                    'figures': s['figures'],
                    'variants': s.get('variants', []),
                    'count_in_bank': counts.get(s['name'], 0),
                }
                for s in d['skills']
            ],
        }
        for d in generation.DOMAINS
    ]
    return Response({'domains': domains, 'api_status': generation.api_status()})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminUser])
def generation_generate(request):
    """Build the prompt for a skill/difficulty batch and, if an API key is
    configured, run it and return parsed draft questions. Without a key the
    response carries the prompt so the admin can paste it into claude.ai or
    ChatGPT and paste the JSON back (parsed client-side)."""
    data = request.data
    skill = data.get('skill')
    if skill not in generation.SKILL_INDEX:
        return Response({'error': 'Unknown skill'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        difficulty = max(1, min(5, int(data.get('difficulty', 3))))
        count = max(1, min(10, int(data.get('count', 5))))
    except (TypeError, ValueError):
        return Response({'error': 'Invalid difficulty or count'}, status=status.HTTP_400_BAD_REQUEST)

    prompt = generation.build_prompt(skill, difficulty, count, variant=data.get('variant') or None)
    payload = {'prompt': prompt, 'api_status': generation.api_status()}

    try:
        raw = generation.call_llm(prompt)
    except Exception as exc:  # surface provider errors to the admin verbatim
        payload['error'] = 'LLM call failed: %s' % exc
        return Response(payload, status=status.HTTP_502_BAD_GATEWAY)

    if raw is None:
        payload['questions'] = None  # no key configured -> manual workflow
        return Response(payload)

    try:
        payload['questions'] = generation.parse_questions(raw)
    except (ValueError, TypeError) as exc:
        payload['error'] = 'Could not parse model output: %s' % exc
        payload['raw'] = raw
        return Response(payload, status=status.HTTP_502_BAD_GATEWAY)
    return Response(payload)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminUser])
def generation_import(request):
    """Bulk-save reviewed draft questions into the bank."""
    drafts = request.data.get('questions')
    if not isinstance(drafts, list) or not drafts:
        return Response({'error': 'questions must be a non-empty list'},
                        status=status.HTTP_400_BAD_REQUEST)
    created = []
    for q in drafts:
        try:
            question = Question.objects.create(
                question=q['question'],
                choice_a=q['choice_a'],
                choice_b=q['choice_b'],
                choice_c=q['choice_c'],
                choice_d=q['choice_d'],
                answer=str(q['answer']).upper(),
                difficulty=max(1, min(5, int(q['difficulty']))),
                question_type=q['question_type'],
                explanation=q.get('explanation', ''),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return Response(
                {'error': 'Invalid question payload: %s' % exc, 'created_ids': created},
                status=status.HTTP_400_BAD_REQUEST,
            )
        created.append(question.id)
    return Response({'status': 'success', 'created_ids': created})

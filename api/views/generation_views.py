"""Admin endpoints for AI-assisted question generation."""

import difflib
import itertools

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
    """The math + English taxonomy plus current per-skill question counts in the bank."""
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

    prompt = generation.build_prompt(skill, difficulty, count)
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


# Near matches are intentionally strict: the text must be almost identical and
# all four choices must also align. This accepts tiny extraction differences
# without treating two SAT items built from the same template as duplicates.
MIN_NEAR_TOKENS = 30
NEAR_QUESTION_RATIO = 0.97
NEAR_CHOICE_RATIO = 0.92
NEAR_AVERAGE_CHOICE_RATIO = 0.97
QUESTION_FIELDS = (
    'id', 'question', 'choice_a', 'choice_b', 'choice_c', 'choice_d',
    'answer', 'difficulty', 'question_type',
)


def _question_payload(question, *, include_id=True):
    payload = {field: question.get(field) for field in QUESTION_FIELDS if include_id or field != 'id'}
    return payload


def _choice_similarity(draft, existing):
    """Best order-independent pairing for four answer choices."""
    draft_choices = [generation.flatten_text(draft.get('choice_' + letter)) for letter in 'abcd']
    existing_choices = [generation.flatten_text(existing.get('choice_' + letter)) for letter in 'abcd']
    best = (-1, [])
    for order in itertools.permutations(existing_choices):
        ratios = [
            difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()
            for left, right in zip(draft_choices, order)
        ]
        score = sum(ratios)
        if score > best[0]:
            best = (score, ratios)
    return best[1]


def _near_match(draft, candidates):
    """Return the strongest high-confidence same-type English match."""
    tokens = generation.tokenize_text(draft.get('question'))
    if len(tokens) < MIN_NEAR_TOKENS:
        return None

    best = None
    for existing in candidates:
        existing_tokens = existing['_tokens']
        if min(len(tokens), len(existing_tokens)) / max(len(tokens), len(existing_tokens)) < NEAR_QUESTION_RATIO:
            continue
        ratio = difflib.SequenceMatcher(None, tokens, existing_tokens, autojunk=False).ratio()
        if ratio < NEAR_QUESTION_RATIO:
            continue
        choice_ratios = _choice_similarity(draft, existing)
        if (min(choice_ratios) < NEAR_CHOICE_RATIO
                or sum(choice_ratios) / len(choice_ratios) < NEAR_AVERAGE_CHOICE_RATIO):
            continue
        if best is None or ratio > best[0]:
            best = (ratio, existing)

    if not best:
        return None
    ratio, existing = best
    return {
        'question_id': existing['id'],
        'where': 'bank',
        'match': 'near',
        'ratio': round(ratio, 3),
        'comparison': _question_payload(existing),
    }


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminUser])
def generation_duplicates(request):
    """Flag same-type English duplicates in the bank or current batch."""
    drafts = request.data.get('questions')
    if not isinstance(drafts, list):
        return Response({'error': 'questions must be a list'}, status=status.HTTP_400_BAD_REQUEST)

    english_types = {
        generation.normalize_question_type(draft.get('question_type'))
        for draft in drafts
        if (isinstance(draft, dict)
            and generation.normalize_question_type(draft.get('question_type')) in generation.ENGLISH_SKILL_NAMES)
    }

    # ponytail: full-table scan, no stored fingerprint column. ~1s at 10k
    # questions; add a fingerprint field + unique index if the bank outgrows it.
    rows = list(Question.objects.filter(question_type__in=english_types).values(*QUESTION_FIELDS))
    exact, candidates = {}, {question_type: [] for question_type in english_types}
    for row in rows:
        key = (row['question_type'], generation.fingerprint(
            row['question'], [row['choice_' + letter] for letter in 'abcd'],
        ))
        exact.setdefault(key, row)
        row['_tokens'] = generation.tokenize_text(row['question'])
        candidates[row['question_type']].append(row)

    duplicates, seen = {}, {}
    for i, draft in enumerate(drafts):
        if not isinstance(draft, dict):
            continue
        question_type = generation.normalize_question_type(draft.get('question_type'))
        if question_type not in generation.ENGLISH_SKILL_NAMES:
            continue
        key = (question_type, generation.draft_fingerprint(draft))
        if key in exact:
            existing = exact[key]
            duplicates[i] = {
                'question_id': existing['id'],
                'where': 'bank',
                'match': 'exact',
                'comparison': _question_payload(existing),
            }
        elif key in seen:
            original_index = seen[key]
            duplicates[i] = {
                'question_id': None,
                'where': 'batch',
                'match': 'exact',
                'draft_index': original_index,
                'comparison': _question_payload(drafts[original_index], include_id=False),
            }
        else:
            seen[key] = i
            near = _near_match(draft, candidates.get(question_type, []))
            if near:
                duplicates[i] = near
    return Response({
        'duplicates': duplicates,
        'checked_count': sum(
            isinstance(draft, dict)
            and generation.normalize_question_type(draft.get('question_type')) in generation.ENGLISH_SKILL_NAMES
            for draft in drafts
        ),
        'bank_size': len(rows),
    })


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminUser])
def generation_import(request):
    """Bulk-save reviewed draft questions into the bank."""
    drafts = request.data.get('questions')
    if not isinstance(drafts, list) or not drafts:
        return Response({'error': 'questions must be a non-empty list'},
                        status=status.HTTP_400_BAD_REQUEST)
    source = request.data.get('source', Question.SOURCE_AI_GENERATED)
    source_other = str(request.data.get('source_other', '')).strip()
    if source not in dict(Question.SOURCE_CHOICES):
        return Response({'error': 'Invalid question source'}, status=status.HTTP_400_BAD_REQUEST)
    if source == Question.SOURCE_OTHER and not source_other:
        return Response({'error': 'Describe the other question source'}, status=status.HTTP_400_BAD_REQUEST)
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
                source=source,
                source_other=source_other,
                explanation=q.get('explanation', ''),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return Response(
                {'error': 'Invalid question payload: %s' % exc, 'created_ids': created},
                status=status.HTTP_400_BAD_REQUEST,
            )
        created.append(question.id)
    return Response({'status': 'success', 'created_ids': created})

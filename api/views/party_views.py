"""Party Mode: Kahoot-style live quiz rooms.

Clients poll `party_state` about once a second; the room's `advance()` derives
phase transitions from timestamps, so no worker or websocket is needed.
"""
import random

from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import (
    DuelEmote,
    PARTY_COUNTDOWN_SECONDS,
    PARTY_MAX_TEAMS,
    PARTY_PRESENCE_TIMEOUT_SECONDS,
    PARTY_WAGER_SECONDS,
    PartyPlayer,
    PartyRoom,
    Question,
    TestSection,
    party_lives_cap,
    usable_duel_emotes,
)

# Free-tier vs premium ceilings for room settings.
CAPS = {
    'free': {'max_players': 6, 'num_questions': 20},
    'premium': {'max_players': 50, 'num_questions': 50},
}
# Gold Rush question pool: premium hosts sample more so answers repeat less
# over a long game, without ever exposing the whole bank.
GOLD_POOL = {'free': 30, 'premium': 100}
GOLD_LOCKOUT_SECONDS = 3  # wrong-answer penalty before the next question


def _roll_reward():
    """One closed Gold Rush chest. Mostly gold, with the swingy events rare."""
    r = random.random()
    if r < 0.34:
        return {'kind': 'gold', 'amount': random.choice([100, 150, 200, 250, 300])}
    if r < 0.58:
        return {'kind': 'gold', 'amount': random.choice([350, 400, 500, 600])}
    if r < 0.70:
        return {'kind': 'gold', 'amount': random.choice([700, 900, 1200])}
    if r < 0.80:
        return {'kind': 'double'}          # your gold ×2
    if r < 0.90:
        return {'kind': 'steal', 'pct': 50}  # take half of a chosen player
    if r < 0.96:
        return {'kind': 'swap'}            # swap totals with a chosen player
    return {'kind': 'lose', 'pct': 30}     # a dud chest
DIFFICULTY_RANGES = {'easy': (1, 3), 'medium': (2, 4), 'hard': (3, 5)}
JOINABLE = ('lobby', 'countdown', 'question', 'leaderboard')


def _caps_for(user):
    return CAPS['premium'] if user.profile.has_premium else CAPS['free']


def _new_code():
    for _ in range(30):
        code = f"{random.randint(0, 999999):06d}"
        if not PartyRoom.objects.filter(code=code).exclude(status='finished').exists():
            return code
    raise RuntimeError('Could not allocate a party code')


def _clamp(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _player_entry(player, index_key):
    profile = player.user.profile
    answer = player.answers.get(index_key, {})
    return {
        'id': player.user_id,
        'username': player.user.username,
        'avatar': profile.avatar,
        'avatar_icon': profile.avatar_icon,
        'score': player.score,
        'team': player.team,
        'answered': index_key in player.answers,
        'last_points': answer.get('points', 0),
        'last_correct': answer.get('correct'),
        'wagered': player.wager_locked,
        'lives': player.lives,
        'lost_life': bool(answer.get('life_lost')),
    }


def _gold_view(player):
    """The player's current Gold Rush screen: question, wrong-answer, chest, or target pick."""
    now = timezone.now()
    view = {'gold': player.score}
    pending = player.gq_pending or {}

    if player.gq_locked_until and now < player.gq_locked_until:
        # Wrong answer: show the right one until the penalty clears.
        view['phase'] = 'wrong'
        view['seconds'] = max(0.0, (player.gq_locked_until - now).total_seconds())
        q = Question.objects.filter(id=pending.get('question')).first()
        if q:
            view['correct_choice'] = q.answer
            view['review'] = {
                'question': q.question,
                'choices': [q.choice_a, q.choice_b, q.choice_c, q.choice_d],
                'correct_choice': q.answer,
                'your_choice': pending.get('choice'),
                'explanation': q.explanation or '',
            }
        return view

    if pending.get('kind') == 'chest':
        options = pending.get('options') or []
        picked = pending.get('picked')
        if picked is not None and picked < len(options) and options[picked]['kind'] in ('steal', 'swap'):
            # The chest opened onto a targeted event — the client picks who from
            # the roster it already has.
            view['phase'] = 'target'
            view['reward'] = {'kind': options[picked]['kind']}
            return view
        view['phase'] = 'chest'
        view['chest_count'] = len(options) or 3
        return view

    view['phase'] = 'question'
    qid = player.gold_question_id()
    q = Question.objects.filter(id=qid).first() if qid else None
    if q:
        view['question'] = {
            'id': q.id,
            'question': q.question,
            'choices': [q.choice_a, q.choice_b, q.choice_c, q.choice_d],
        }
    return view


def _team_standings(room, entries):
    """Group player entries into teams, ranked by total score."""
    teams = []
    for index in range(room.num_teams):
        members = [e for e in entries if e['team'] == index]
        members.sort(key=lambda e: -e['score'])
        teams.append({
            'index': index,
            'name': room.team_label(index),
            'score': sum(e['score'] for e in members),
            'last_points': sum(e['last_points'] for e in members),
            'members': members,
        })
    teams.sort(key=lambda t: -t['score'])
    return teams


def _history_snapshot(room, user_id):
    """Final standings shared by the compact history list and full review."""
    roster = list(room.history_players)
    mine = next((player for player in roster if player.user_id == user_id), None)

    if room.mode == 'teams':
        team_scores = {
            index: sum(player.score for player in roster if player.team == index)
            for index in range(room.num_teams)
        }
        best = max(team_scores.values(), default=0)
        winning_teams = {index for index, score in team_scores.items() if score == best}
        ranked = sorted(roster, key=lambda player: (-team_scores.get(player.team, 0), -player.score))
        winners = [room.team_label(index) for index in sorted(winning_teams)]
        teams = [
            {'name': room.team_label(index), 'score': score, 'is_winner': index in winning_teams}
            for index, score in sorted(team_scores.items(), key=lambda item: -item[1])
        ]
        is_winner = bool(mine and mine.team in winning_teams)
    else:
        key = (lambda player: (player.lives, player.score)) if room.mode == 'survival' else (lambda player: player.score)
        ranked = sorted(roster, key=key, reverse=True)
        best = key(ranked[0]) if ranked else None
        winners = [player.user.username for player in ranked if key(player) == best]
        teams = []
        is_winner = bool(mine and key(mine) == best)

    players = []
    for rank, player in enumerate(ranked, start=1):
        profile = player.user.profile
        players.append({
            'id': player.user_id,
            'username': player.user.username,
            'avatar': profile.avatar,
            'avatar_icon': profile.avatar_icon,
            'score': player.score,
            'lives': player.lives,
            'team': room.team_label(player.team) if player.team is not None else None,
            'rank': rank,
            'is_you': player.user_id == user_id,
            'is_winner': (
                player.team in winning_teams if room.mode == 'teams' else key(player) == best
            ),
        })

    creator_id = room.original_host_id or room.host_id
    return {
        'id': room.id,
        'code': room.code,
        'mode': room.mode,
        'created_at': room.created_at,
        'role': 'hosted' if creator_id == user_id else 'participated',
        'host_username': (
            room.original_host.username if room.original_host else room.host.username
        ),
        'player_count': len(roster),
        'your_score': mine.score if mine else None,
        'winners': winners,
        'is_winner': is_winner,
        'players': players,
        'teams': teams,
    }


def _history_questions(room, player):
    if not player:
        return []

    if room.mode == 'goldrush':
        attempts = sorted(
            (
                (int(key[1:]), answer) for key, answer in player.answers.items()
                if key.startswith('g') and key[1:].isdigit() and answer.get('question_id')
            ),
            key=lambda item: item[0],
        )
        question_ids = [answer['question_id'] for _, answer in attempts]
        entries = [
            (index, answer['question_id'], answer)
            for index, (_, answer) in enumerate(attempts)
        ]
    else:
        question_ids = room.question_ids
        entries = [
            (index, question_id, player.answers.get(str(index), {}))
            for index, question_id in enumerate(question_ids)
        ]

    questions = Question.objects.in_bulk(question_ids)
    review = []
    for index, question_id, answer in entries:
        question = questions.get(question_id)
        if not question:
            continue
        review.append({
            'id': question.id,
            'number': index + 1,
            'question': question.question,
            'choices': [question.choice_a, question.choice_b, question.choice_c, question.choice_d],
            'correct_choice': question.answer,
            'correct_text': question.answer_text,
            'explanation': question.explanation or '',
            'your_choice': answer.get('choice'),
            'correct': answer.get('correct') if answer else None,
            'points': answer.get('points', 0),
            'skipped': not answer or answer.get('choice') is None,
        })
    return review


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def create_party(request):
    caps = _caps_for(request.user)
    data = request.data
    test_prep = request.user.profile.active_test_prep
    valid_subjects = set(TestSection.objects.filter(
        test_prep=test_prep, active=True,
    ).values_list('code', flat=True))
    subject = data.get('subject') if data.get('subject') in valid_subjects | {'mixed'} else 'mixed'
    difficulty = data.get('difficulty') if data.get('difficulty') in DIFFICULTY_RANGES else 'medium'
    mode = data.get('mode') if data.get('mode') in PartyRoom.MODES else 'classic'

    # One live room per host: a new room supersedes any the user abandoned.
    PartyRoom.objects.filter(host=request.user).exclude(status='finished').update(status='finished')

    num_questions = _clamp(data.get('num_questions'), 2 if mode == 'jeopardy' else 1,
                           caps['num_questions'], 10)
    last_standing = bool(data.get('last_standing', True))

    room = PartyRoom.objects.create(
        host=request.user,
        original_host=request.user,
        test_prep=test_prep,
        code=_new_code(),
        mode=mode,
        num_teams=_clamp(data.get('num_teams'), 2, PARTY_MAX_TEAMS, 2),
        random_teams=bool(data.get('random_teams', True)),
        last_standing=last_standing,
        lives=_clamp(data.get('lives'), 1, party_lives_cap(last_standing, num_questions), 3),
        max_players=_clamp(data.get('max_players'), 2, caps['max_players'], min(6, caps['max_players'])),
        num_questions=num_questions,
        seconds_per_question=_clamp(data.get('seconds_per_question'), 10, 300, 90),
        # Gold Rush runs on a clock instead of a question count: 5/10/15 min.
        time_limit=_clamp(data.get('time_limit'), 180, 1800, 600),
        subject=subject,
        difficulty=difficulty,
    )
    PartyPlayer.objects.create(room=room, user=request.user)
    return Response({'id': room.id, 'code': room.code}, status=201)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def join_party(request):
    code = str(request.data.get('code', '')).strip()
    room = PartyRoom.objects.filter(code=code).exclude(status='finished').order_by('-id').first()
    if room:
        room.sync_presence()  # an abandoned lobby closes here instead of matching
    if not room or room.status == 'finished':
        return Response({'error': 'No room found with that code.'}, status=404)

    if room.players.filter(user=request.user).exists():
        return Response({'id': room.id})  # rejoin
    if room.status != 'lobby':
        return Response({'error': 'That game has already started.'}, status=400)
    if room.players.count() >= room.max_players:
        return Response({'error': 'That room is full.'}, status=400)

    PartyPlayer.objects.get_or_create(room=room, user=request.user)
    return Response({'id': room.id})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def send_party_emote(request, room_id):
    room = get_object_or_404(PartyRoom, id=room_id)
    if not room.players.filter(user=request.user).exists():
        return Response({'error': 'You are not in this room.'}, status=403)

    raw_reactions = request.data.get('reactions')
    if raw_reactions is None:
        raw_reactions = [{'emoji': request.data.get('emoji'), 'count': 1}]
    if not isinstance(raw_reactions, list) or not raw_reactions:
        return Response({'error': 'Choose at least one reaction.'}, status=400)

    allowed = usable_duel_emotes(request.user.profile)
    emojis = []
    for item in raw_reactions:
        if not isinstance(item, dict) or item.get('emoji') not in allowed:
            return Response({'error': 'Invalid emote.'}, status=400)
        try:
            count = int(item.get('count', 1))
        except (TypeError, ValueError):
            return Response({'error': 'Invalid reaction count.'}, status=400)
        if count < 1 or count > 12:
            return Response({'error': 'Send between 1 and 12 of each reaction.'}, status=400)
        emojis.extend([item['emoji']] * count)

    if len(emojis) > 20:
        return Response({'error': 'Send at most 20 reactions at once.'}, status=400)

    now = timezone.now()
    recent_count = DuelEmote.objects.filter(
        party_room=room,
        sender=request.user,
        created_at__gt=now - timezone.timedelta(seconds=1),
    ).count()
    if recent_count + len(emojis) > 24:
        return Response({'error': 'Slow down.'}, status=429)

    emotes = DuelEmote.objects.bulk_create([
        DuelEmote(party_room=room, sender=request.user, emoji=emoji, visible_at=now)
        for emoji in emojis
    ])
    reactions = [
        {
            'id': emote.id,
            'sender_id': request.user.id,
            'sender_username': request.user.username,
            'emoji': emote.emoji,
            'visible_at': now.isoformat(),
        }
        for emote in emotes
    ]
    return Response({'reaction': reactions[0], 'reactions': reactions})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def start_party(request, room_id):
    room = get_object_or_404(PartyRoom, id=room_id, host=request.user)
    if room.status != 'lobby':
        return Response({'error': 'The game has already started.'}, status=400)

    if room.mode == 'teams' and room.players.count() < room.num_teams:
        return Response(
            {'error': f'You need at least {room.num_teams} players for {room.num_teams} teams.'},
            status=400,
        )

    lo, hi = DIFFICULTY_RANGES[room.difficulty]
    questions = Question.objects.filter(
        test_prep=room.test_prep,
        difficulty__gte=lo,
        difficulty__lte=hi,
    )
    if room.subject != 'mixed':
        questions = questions.filter(subject=room.subject)
    ids = list(questions.values_list('id', flat=True))
    if not ids:
        return Response({'error': 'No questions available for these settings.'}, status=400)

    if room.mode == 'goldrush':
        pool_size = GOLD_POOL['premium' if request.user.profile.has_premium else 'free']
        room.question_ids = random.sample(ids, min(pool_size, len(ids)))
    else:
        room.question_ids = random.sample(ids, min(room.num_questions, len(ids)))
    if room.mode == 'jeopardy' and len(room.question_ids) < 2:
        return Response(
            {'error': 'Final Jeopardy needs at least 2 questions for these settings.'},
            status=400,
        )
    room.num_questions = len(room.question_ids)
    room.status = 'countdown'
    room.phase_started_at = timezone.now()
    room.save()
    if room.mode == 'teams':
        # Random rooms have nobody seated yet, so this shuffles everyone; hand-sorted
        # rooms only pick up the stragglers the host never dragged.
        room.assign_missing_teams()
    if room.mode == 'survival':
        # The pool may have yielded fewer questions than asked for, which can
        # pull the cap down under the hearts the host picked.
        room.lives = min(room.lives, party_lives_cap(room.last_standing, room.num_questions))
        room.save(update_fields=['lives'])
        room.players.update(lives=room.lives)
    if room.mode == 'goldrush':
        # Everyone walks their own shuffle of the same pool, so nobody is in lockstep.
        for player in room.players.all():
            deck = room.question_ids[:]
            random.shuffle(deck)
            player.gq_deck = deck
            player.gq_index = 0
            player.gq_pending = None
            player.gq_locked_until = None
            player.save(update_fields=['gq_deck', 'gq_index', 'gq_pending', 'gq_locked_until'])
    return Response({'status': 'countdown'})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def answer_party_question(request, room_id):
    with transaction.atomic():
        room = get_object_or_404(PartyRoom.objects.select_for_update(), id=room_id)
        room.advance()
        if room.status != 'question':
            return Response({'error': 'Not accepting answers right now.'}, status=400)

        player = get_object_or_404(PartyPlayer, room=room, user=request.user)
        key = str(room.current_index)
        if key in player.answers:
            return Response({'error': 'Already answered.'}, status=400)
        if room.eliminates() and player.lives <= 0:
            return Response({'error': "You're out — you can only watch now."}, status=400)

        choice = str(request.data.get('choice', '')).upper()
        if choice not in ('A', 'B', 'C', 'D'):
            return Response({'error': 'Invalid choice.'}, status=400)

        question = Question.objects.get(id=room.current_question_id())
        elapsed = (timezone.now() - room.phase_started_at).total_seconds()
        elapsed = max(0.0, min(elapsed, room.seconds_per_question))
        correct = choice == question.answer

        entry = {'choice': choice, 'correct': correct}
        if room.is_wager_question():
            # The bet is the whole score here — speed deliberately pays nothing,
            # so a slow, careful answer is worth as much as a fast one.
            points = player.wager if correct else -player.wager
            entry['wager'] = player.wager
        else:
            # Kahoot-style: a correct answer is worth 500-1000, scaling with speed.
            points = 500 + round(500 * (1 - elapsed / room.seconds_per_question)) if correct else 0

        if room.mode == 'survival' and not correct and player.lives > 0:
            player.lives -= 1
            entry['life_lost'] = True

        entry['points'] = points
        player.answers[key] = entry
        player.score += points
        player.save()
        room.advance()  # everyone may have answered now
    return Response({'answered': True})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def next_party_question(request, room_id):
    room = get_object_or_404(PartyRoom, id=room_id, host=request.user)
    if room.status != 'leaderboard':
        return Response({'error': 'Nothing to advance right now.'}, status=400)

    if room.game_is_over():
        room.status = 'finished'
    else:
        room.current_index += 1
        # Final Jeopardy takes bets before revealing the last question.
        room.status = 'wager' if room.is_wager_question() else 'question'
    room.phase_started_at = timezone.now()
    room.save(update_fields=['status', 'current_index', 'phase_started_at'])
    return Response({'status': room.status})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def place_party_wager(request, room_id):
    """Lock in a Final Jeopardy bet before the last question is revealed."""
    with transaction.atomic():
        room = get_object_or_404(PartyRoom.objects.select_for_update(), id=room_id)
        room.advance()
        if room.status != 'wager':
            return Response({'error': 'Bets are closed.'}, status=400)

        player = get_object_or_404(PartyPlayer, room=room, user=request.user)
        if player.wager_locked:
            return Response({'error': 'You already placed your bet.'}, status=400)

        # You can only lose what you brought; everything else is clamped into range.
        player.wager = _clamp(request.data.get('amount'), 0, max(0, player.score), 0)
        player.wager_locked = True
        player.save(update_fields=['wager', 'wager_locked'])
        room.advance()  # everyone may have bet now
    return Response({'wager': player.wager})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def gold_rush_answer(request, room_id):
    """Answer the player's current Gold Rush question. Correct earns a chest."""
    with transaction.atomic():
        room = get_object_or_404(PartyRoom.objects.select_for_update(), id=room_id)
        room.advance()
        if room.mode != 'goldrush' or room.status != 'playing':
            return Response({'error': 'Not accepting answers right now.'}, status=400)

        player = get_object_or_404(PartyPlayer, room=room, user=request.user)
        now = timezone.now()
        if player.gq_locked_until and now < player.gq_locked_until:
            return Response({'error': 'Hold on a moment.'}, status=400)
        if player.gq_pending:
            return Response({'error': 'Open your chest first.'}, status=400)

        choice = str(request.data.get('choice', '')).upper()
        if choice not in ('A', 'B', 'C', 'D'):
            return Response({'error': 'Invalid choice.'}, status=400)

        question = Question.objects.get(id=player.gold_question_id())
        attempt = 1 + max(
            (int(key[1:]) for key in player.answers if key.startswith('g') and key[1:].isdigit()),
            default=-1,
        )
        player.answers[f'g{attempt}'] = {
            'question_id': question.id,
            'choice': choice,
            'correct': choice == question.answer,
            'points': 0,
        }
        if choice == question.answer:
            player.gq_pending = {'kind': 'chest', 'options': [_roll_reward() for _ in range(3)], 'picked': None}
            player.save()
            return Response({'correct': True})

        # Wrong: a short penalty, then the next question (handled by gold_rush_tick).
        player.gq_locked_until = now + timezone.timedelta(seconds=GOLD_LOCKOUT_SECONDS)
        player.gq_pending = {'kind': 'wrong', 'question': question.id, 'choice': choice}
        player.save()
        return Response({'correct': False, 'correct_choice': question.answer})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def gold_rush_chest(request, room_id):
    """Open a chosen Gold Rush chest, then apply its reward (targeted or not)."""
    with transaction.atomic():
        room = get_object_or_404(PartyRoom.objects.select_for_update(), id=room_id)
        room.advance()
        if room.mode != 'goldrush' or room.status != 'playing':
            return Response({'error': 'The game is over.'}, status=400)

        player = get_object_or_404(PartyPlayer, room=room, user=request.user)
        pending = player.gq_pending or {}
        if pending.get('kind') != 'chest':
            return Response({'error': 'No chest to open.'}, status=400)

        options = pending.get('options') or []
        # A chosen chest is locked in, so the follow-up target step can't reroll it.
        if pending.get('picked') is not None:
            pick = pending['picked']
        else:
            pick = _clamp(request.data.get('pick'), 0, len(options) - 1, 0)
        reward = options[pick]
        kind = reward['kind']

        target_id = request.data.get('target')
        if kind in ('steal', 'swap') and target_id is None:
            pending['picked'] = pick
            player.gq_pending = pending
            player.save()
            return Response({'needs_target': True, 'kind': kind})

        result = {'kind': kind}
        if kind == 'gold':
            player.score += reward['amount']
            result['amount'] = reward['amount']
        elif kind == 'double':
            gain = player.score  # doubling adds a second copy of your pile
            player.score += gain
            result['amount'] = gain
        elif kind == 'lose':
            loss = player.score * reward['pct'] // 100
            player.score -= loss
            result['amount'] = -loss
        else:  # steal / swap — both need a valid opponent
            target = room.players.filter(user_id=target_id).exclude(user_id=player.user_id).first()
            if not target:
                return Response({'error': 'Pick another player.'}, status=400)
            if kind == 'steal':
                taken = target.score * reward['pct'] // 100
                target.score -= taken
                player.score += taken
                result['amount'] = taken
            else:
                player.score, target.score = target.score, player.score
                result['amount'] = player.score
            result['target'] = target.user.username
            target.save(update_fields=['score'])

        player.gq_pending = None
        player.gq_index += 1
        player.save()
        result['gold'] = player.score
        return Response(result)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def update_party_teams(request, room_id):
    """Host-only lobby controls for Teams mode: resize, rename, and seat players."""
    room = get_object_or_404(PartyRoom, id=room_id, host=request.user)
    if room.mode != 'teams':
        return Response({'error': 'This room is not in Teams mode.'}, status=400)
    if room.status != 'lobby':
        return Response({'error': 'Teams are locked once the game starts.'}, status=400)

    data = request.data
    fields = []
    if 'num_teams' in data:
        room.num_teams = _clamp(data.get('num_teams'), 2, PARTY_MAX_TEAMS, room.num_teams)
        fields.append('num_teams')
        # Shrinking strands anyone sitting on a team that no longer exists.
        room.players.filter(team__gte=room.num_teams).update(team=None)
    if 'random_teams' in data:
        room.random_teams = bool(data.get('random_teams'))
        fields.append('random_teams')
        if room.random_teams:
            room.players.update(team=None)  # the shuffle at kickoff owns the seating
    if 'names' in data:
        names = data.get('names') or []
        room.team_names = [str(name)[:24].strip() for name in names[:PARTY_MAX_TEAMS]]
        fields.append('team_names')
    if fields:
        room.save(update_fields=fields)

    if not room.random_teams:
        for user_id, team in (data.get('assignments') or {}).items():
            seat = None if team is None else _clamp(team, 0, room.num_teams - 1, None)
            room.players.filter(user_id=user_id).update(team=seat)
    return Response({'ok': True})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def leave_party(request, room_id):
    room = get_object_or_404(PartyRoom, id=room_id)
    player = room.players.filter(user=request.user)
    if room.status == 'lobby':
        player.delete()
    else:
        # Keep completed answers and scores for history, but make the seat stale
        # immediately so it never blocks phase changes or host handoff.
        player.update(
            last_seen=timezone.now() - timezone.timedelta(seconds=PARTY_PRESENCE_TIMEOUT_SECONDS + 1),
        )
    # Empty room closes; a departing host hands off to the next player.
    room.sync_presence()
    return Response({'left': True})


def _history_queryset():
    return PartyRoom.objects.select_related('host', 'original_host').prefetch_related(
        Prefetch(
            'players',
            queryset=PartyPlayer.objects.select_related('user__profile'),
            to_attr='history_players',
        ),
    )


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def party_history(request):
    rooms = (
        _history_queryset()
        .filter(status='finished')
        .exclude(question_ids=[])
        .filter(Q(original_host=request.user) | Q(players__user=request.user))
        .distinct()
        .order_by('-created_at')
    )
    return Response([
        {key: value for key, value in _history_snapshot(room, request.user.id).items()
         if key not in ('players', 'teams')}
        for room in rooms
    ])


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def party_history_detail(request, room_id):
    room = get_object_or_404(_history_queryset(), id=room_id, status='finished')
    creator_id = room.original_host_id or room.host_id
    player = next(
        (seat for seat in room.history_players if seat.user_id == request.user.id),
        None,
    )
    if creator_id != request.user.id and not player:
        return Response({'error': 'You did not participate in this party.'}, status=403)

    detail = _history_snapshot(room, request.user.id)
    detail['questions'] = _history_questions(room, player)
    detail['settings'] = {
        'subject': room.subject,
        'difficulty': room.difficulty,
        'num_questions': room.num_questions,
        'seconds_per_question': room.seconds_per_question,
    }
    return Response(detail)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def party_state(request, room_id):
    room = get_object_or_404(PartyRoom, id=room_id)
    player = room.players.filter(user=request.user).first()
    if not player:
        return Response({'error': 'You are not in this room.'}, status=403)
    player.save(update_fields=['last_seen'])  # auto_now heartbeat
    room.advance()

    now = timezone.now()
    key = str(room.current_index)
    roster = list(room.players.select_related('user__profile').all())
    players = [_player_entry(p, key) for p in roster]
    if room.mode == 'survival':
        # Hearts decide it; the speed score is only the tiebreak.
        players.sort(key=lambda p: (-p['lives'], -p['score']))
    else:
        players.sort(key=lambda p: -p['score'])

    state = {
        'id': room.id,
        'code': room.code,
        'status': room.status,
        'started': bool(room.question_ids),  # lets the UI tell "host closed the lobby" from "game over"
        'you': request.user.id,
        'is_host': room.host_id == request.user.id,
        'host_username': room.host.username,
        'test_prep': room.test_prep_id,
        'mode': room.mode,
        'settings': {
            'max_players': room.max_players,
            'num_questions': room.num_questions,
            'seconds_per_question': room.seconds_per_question,
            'subject': room.subject,
            'difficulty': room.difficulty,
            'num_teams': room.num_teams,
            'random_teams': room.random_teams,
            'lives': room.lives,
            'last_standing': room.last_standing,
        },
        'players': players,
        'your_emotes': usable_duel_emotes(request.user.profile),
        'reactions': list(reversed([
            {
                'id': reaction.id,
                'sender_id': reaction.sender_id,
                'sender_username': reaction.sender.username,
                'emoji': reaction.emoji,
                'visible_at': reaction.visible_at.isoformat(),
            }
            for reaction in DuelEmote.objects.filter(
                party_room=room,
                visible_at__lte=now,
                visible_at__gte=now - timezone.timedelta(seconds=7),
            ).select_related('sender').order_by('-visible_at', '-id')[:30]
        ])),
        'question_number': room.current_index + 1,
        'total_questions': room.num_questions if room.question_ids else room.num_questions,
    }
    if room.mode == 'teams':
        state['teams'] = _team_standings(room, players)
    if room.mode == 'survival':
        state['your_lives'] = player.lives
        state['you_are_out'] = room.eliminates() and player.lives <= 0
        state['survivors'] = len(room.survivors(roster))

    if room.mode == 'goldrush' and room.status == 'playing':
        player.gold_rush_tick()  # clear an expired wrong-answer lockout
        state['seconds_left'] = max(0.0, (room.game_deadline() - now).total_seconds())
        state['gold'] = _gold_view(player)

    if room.status == 'countdown':
        ends = room.phase_started_at + timezone.timedelta(seconds=PARTY_COUNTDOWN_SECONDS)
        state['seconds_left'] = max(0.0, (ends - now).total_seconds())
    elif room.status == 'wager':
        state['seconds_left'] = max(0.0, (room.wager_deadline() - now).total_seconds())
        state['wager'] = {
            'your_score': player.score,
            'your_wager': player.wager if player.wager_locked else None,
            'locked': player.wager_locked,
            'waiting_on': sum(1 for p in roster if not p.wager_locked and p.score > 0),
        }
    elif room.status == 'question':
        question = Question.objects.get(id=room.current_question_id())
        state['seconds_left'] = max(0.0, (room.question_deadline() - now).total_seconds())
        state['is_final_question'] = room.is_wager_question()
        if room.is_wager_question():
            state['your_wager'] = player.wager
        state['question'] = {
            'id': question.id,
            'question': question.question,
            'choices': [question.choice_a, question.choice_b, question.choice_c, question.choice_d],
        }
        state['your_answer'] = player.answers.get(key, {}).get('choice')
    elif room.status == 'leaderboard':
        question = Question.objects.get(id=room.current_question_id())
        answer = player.answers.get(key, {})
        counts = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
        skipped = 0
        for seat in roster:
            choice = seat.answers.get(key, {}).get('choice')
            if choice in counts:
                counts[choice] += 1
            else:
                skipped += 1
        state['reveal'] = {
            'correct_choice': question.answer,
            'correct_text': question.answer_text,
            'your_choice': answer.get('choice'),
            'correct': answer.get('correct', False),
            'points_earned': answer.get('points', 0),
            'wager': answer.get('wager'),
            'was_final_bet': room.is_wager_question(),
            'lost_life': bool(answer.get('life_lost')),
            'your_lives': player.lives,
            'is_last': room.game_is_over(),
            'distribution': counts,
            'skipped': skipped,
            'review': {
                'question': question.question,
                'choices': [question.choice_a, question.choice_b, question.choice_c, question.choice_d],
                'explanation': question.explanation or '',
            },
        }

    return Response(state)

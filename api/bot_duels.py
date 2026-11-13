import random

from django.db.models import Q
from django.utils import timezone

from api.models import Profile, Room, TrackedQuestion


def bot_accuracy(rating):
    return min(82, max(52, 52 + (rating - 1200) // 20))


def rotating_bot_users(now=None):
    """Return three or four bot rivals, rotating once per minute."""
    bots = list(
        Profile.objects.filter(is_bot=True, user__is_active=True)
        .select_related('user')
        .order_by('user_id')
    )
    if not bots:
        return []
    slot = int((now or timezone.now()).timestamp() // 60)
    count = min(len(bots), 3 + slot % 2)
    start = slot % len(bots)
    return [bots[(start + offset) % len(bots)].user for offset in range(count)]


def available_bot_user(exclude_user=None):
    active_ids = set(
        Room.objects.filter(status__in=['Searching', 'Battling'])
        .filter(Q(user1__profile__is_bot=True) | Q(user2__profile__is_bot=True))
        .values_list('user1_id', 'user2_id')
    )
    unavailable = {user_id for pair in active_ids for user_id in pair if user_id}
    if exclude_user:
        unavailable.add(exclude_user.id)

    rotating = rotating_bot_users()
    remaining = [
        profile.user
        for profile in Profile.objects.filter(is_bot=True, user__is_active=True)
        .exclude(user_id__in=[user.id for user in rotating])
        .select_related('user')
        .order_by('user_id')
    ]
    return next((user for user in rotating + remaining if user.id not in unavailable), None)


def _answer_blanks(questions, accuracy):
    """Grade the still-blank questions in `questions` at the bot's accuracy."""
    changed = []
    for tracked in questions:
        if tracked.status != 'Blank':
            continue
        tracked.status = 'Correct' if random.randrange(100) < accuracy else 'Incorrect'
        changed.append(tracked)
    if changed:
        TrackedQuestion.objects.bulk_update(changed, ['status'])


def advance_bot(room, bot):
    """Advance a bot from elapsed battle time whenever progress is polled."""
    if not room.battle_start_time:
        return

    questions = list(TrackedQuestion.objects.filter(room=room, user=bot).order_by('id'))
    rating = bot.profile.elo_rating
    pace_seconds = max(16, 25 - max(0, rating - 1200) // 150)
    elapsed = max(0, (timezone.now() - room.battle_start_time).total_seconds())
    due = min(len(questions), int(elapsed // pace_seconds))
    _answer_blanks(questions[:due], bot_accuracy(rating))


def finish_bot(room, bot):
    """Answer everything the bot has left, ignoring its pace.

    The pace exists so a student has something to race. Once the student has
    answered all of their questions there is no race left, and at 16-25 seconds
    a question the bot would hold the result back for up to four minutes.
    Accuracy is unchanged, so finishing early does not make the bot easier or
    harder to beat.
    """
    questions = TrackedQuestion.objects.filter(room=room, user=bot).order_by('id')
    _answer_blanks(questions, bot_accuracy(bot.profile.elo_rating))


def settle_bot(room, bot):
    """Bring a bot up to date: on pace while its opponent is still answering,
    all the way to the end once the opponent is done."""
    opponent_has_blanks = (
        TrackedQuestion.objects.filter(room=room, status='Blank').exclude(user=bot).exists()
    )
    if opponent_has_blanks:
        advance_bot(room, bot)
    else:
        finish_bot(room, bot)

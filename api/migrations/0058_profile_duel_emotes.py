from django.db import migrations, models
import api.models


ILLUSTRATED = {
    'ethan_w': 'ember-abacus',
    'noahg22': 'pixel-pathfinder',
    'liam1440': 'margin-warden',
    'lucas17': 'echo-fencer',
    'kaisun': 'slate-sentinel',
    'sienna_q': 'mira-mnemonic',
}

LOADOUTS = [
    ['👍', '🔥', '😂', '😮'],
    ['💀', '👀', '🧠', '🤯'],
    ['🎉', '🏆', '👏', '✨'],
    ['😎', '🤔', '😤', '🫡'],
    ['🚀', '⚡', '🎯', '🐐'],
    ['😭', '😅', '🙃', '🫠'],
]


def tune_bot_profiles(apps, schema_editor):
    Profile = apps.get_model('api', 'Profile')
    bots = Profile.objects.filter(is_bot=True).select_related('user').order_by('user_id')
    for index, profile in enumerate(bots):
        profile.avatar_icon = ILLUSTRATED.get(profile.user.username, 'initial')
        profile.duel_emotes = LOADOUTS[index % len(LOADOUTS)]
        profile.is_premium = profile.user.username in {'sophia_k', 'liam1440'}
        profile.elo_rating = min(profile.elo_rating, 1750)
        profile.save(update_fields=['avatar_icon', 'duel_emotes', 'is_premium', 'elo_rating'])


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0057_duel_elo_and_bot_identities'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='duel_emotes',
            field=models.JSONField(default=api.models.default_duel_emotes),
        ),
        migrations.RunPython(tune_bot_profiles, migrations.RunPython.noop),
    ]

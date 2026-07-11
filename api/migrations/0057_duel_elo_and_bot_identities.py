from django.db import migrations, models


BOT_IDENTITIES = [
    ('nova_reader', 'maddie07', 'initial', 'rose'),
    ('algebra_ace', 'ethan_w', 'ember-abacus', 'amber'),
    ('vocab_violet', 'arireads', 'initial', 'violet'),
    ('pixel_prep', 'noahg22', 'pixel-pathfinder', 'sky'),
    ('score_scout', 'sophia_k', 'initial', 'emerald'),
    ('theorem_tiger', 'liam1440', 'margin-warden', 'amber'),
    ('comma_commander', 'zoe.c', 'inkcap-alchemist', 'rose'),
    ('radian_runner', 'devonm', 'initial', 'sky'),
    ('evidence_ember', 'lucas17', 'echo-fencer', 'amber'),
    ('linear_luna', 'emilyq', 'initial', 'violet'),
    ('syntax_sage', 'kaisun', 'slate-sentinel', 'slate'),
    ('graph_glider', 'nina_notes', 'bloom-circuit', 'emerald'),
    ('inference_ivy', 'samir23', 'initial', 'rose'),
    ('boundary_ben', 'avafocus', 'orbit-scout', 'sky'),
    ('prism_prep', 'riley_p', 'initial', 'violet'),
    ('orbit_owl', 'jordan88', 'prism-page', 'slate'),
    ('margin_maven', 'milo_reads', 'nova-quill', 'emerald'),
    ('calc_cadet', 'chloex', 'initial', 'sky'),
    ('passage_panda', 'theologic', 'cipher-lantern', 'rose'),
    ('ratio_raven', 'leah1200', 'initial', 'slate'),
    ('function_fox', 'benji_m', 'ember-abacus', 'amber'),
    ('transition_tess', 'sienna_q', 'mira-mnemonic', 'violet'),
    ('data_dragon', 'omarj', 'initial', 'emerald'),
    ('context_cobra', 'grace_notes', 'bloom-circuit', 'rose'),
]


def update_bot_identities(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Profile = apps.get_model('api', 'Profile')
    for old_username, username, avatar_icon, avatar in BOT_IDENTITIES:
        user = User.objects.filter(username=old_username, profile__is_bot=True).first()
        if not user:
            continue
        if User.objects.exclude(pk=user.pk).filter(username=username).exists():
            username = f'{username}{user.pk}'
        user.username = username
        user.email = f'{username}@bots.satduel.invalid'
        user.save(update_fields=['username', 'email'])
        Profile.objects.filter(user_id=user.pk).update(
            avatar=avatar,
            avatar_icon=avatar_icon,
            biography='',
        )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0056_bot_duels'),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='user1_elo_after',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='room',
            name='user1_elo_before',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='room',
            name='user2_elo_after',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='room',
            name='user2_elo_before',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.RunPython(update_bot_identities, migrations.RunPython.noop),
    ]

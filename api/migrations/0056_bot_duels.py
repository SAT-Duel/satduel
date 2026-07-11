from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


BOTS = [
    ('nova_reader', 'nova-quill', 'violet', 1510),
    ('algebra_ace', 'ember-abacus', 'amber', 1630),
    ('vocab_violet', 'cipher-lantern', 'violet', 1420),
    ('pixel_prep', 'pixel-pathfinder', 'sky', 1550),
    ('score_scout', 'orbit-scout', 'emerald', 1690),
    ('theorem_tiger', 'margin-warden', 'amber', 1740),
    ('comma_commander', 'inkcap-alchemist', 'rose', 1470),
    ('radian_runner', 'prism-page', 'sky', 1580),
    ('evidence_ember', 'echo-fencer', 'amber', 1610),
    ('linear_luna', 'mira-mnemonic', 'violet', 1540),
    ('syntax_sage', 'slate-sentinel', 'slate', 1660),
    ('graph_glider', 'bloom-circuit', 'emerald', 1590),
    ('inference_ivy', 'nova-quill', 'rose', 1450),
    ('boundary_ben', 'orbit-scout', 'sky', 1500),
    ('prism_prep', 'prism-page', 'violet', 1710),
    ('orbit_owl', 'orbit-scout', 'slate', 1570),
    ('margin_maven', 'margin-warden', 'emerald', 1640),
    ('calc_cadet', 'ember-abacus', 'sky', 1490),
    ('passage_panda', 'inkcap-alchemist', 'rose', 1430),
    ('ratio_raven', 'cipher-lantern', 'slate', 1680),
    ('function_fox', 'echo-fencer', 'amber', 1720),
    ('transition_tess', 'mira-mnemonic', 'violet', 1530),
    ('data_dragon', 'bloom-circuit', 'emerald', 1760),
    ('context_cobra', 'pixel-pathfinder', 'rose', 1460),
]


def seed_duel_bots(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Profile = apps.get_model('api', 'Profile')
    for username, avatar_icon, avatar, rating in BOTS:
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': f'{username}@bots.satduel.invalid', 'is_active': True},
        )
        if not created:
            continue
        user.password = make_password(None)
        user.save(update_fields=['password'])
        Profile.objects.create(
            user=user,
            is_bot=True,
            avatar=avatar,
            avatar_icon=avatar_icon,
            elo_rating=rating,
            biography='SAT Duel practice rival',
        )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api', '0055_manual_practice_timer'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='is_bot',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.CreateModel(
            name='DuelEmote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('emoji', models.CharField(max_length=8)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('visible_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('room', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='emotes', to='api.room')),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='duel_emotes', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['visible_at', 'id']},
        ),
        migrations.RunPython(seed_duel_bots, migrations.RunPython.noop),
    ]

# Generated manually for profile avatar icons.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0043_profile_stripe_customer_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='avatar_icon',
            field=models.CharField(
                choices=[
                    ('initial', 'Initial'),
                    ('nova-quill', 'Nova Quill'),
                    ('ember-abacus', 'Ember Abacus'),
                    ('cipher-lantern', 'Cipher Lantern'),
                    ('prism-page', 'Prism Page'),
                    ('orbit-scout', 'Orbit Scout'),
                    ('inkcap-alchemist', 'Inkcap Alchemist'),
                    ('bloom-circuit', 'Bloom Circuit'),
                    ('echo-fencer', 'Echo Fencer'),
                    ('slate-sentinel', 'Slate Sentinel'),
                    ('mira-mnemonic', 'Mira Mnemonic'),
                    ('pixel-pathfinder', 'Pixel Pathfinder'),
                    ('margin-warden', 'Margin Warden'),
                ],
                default='initial',
                max_length=32,
            ),
        ),
    ]

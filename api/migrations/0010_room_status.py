# Generated by Django 5.0.4 on 2024-07-05 20:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0009_profile_friends_friendrequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='status',
            field=models.CharField(choices=[('Battling', 'Battling'), ('Ended', 'Ended')], default='Ended', max_length=10),
            preserve_default=False,
        ),
    ]

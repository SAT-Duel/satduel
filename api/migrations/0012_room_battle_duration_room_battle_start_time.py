# Generated by Django 5.0.4 on 2024-07-07 18:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0011_alter_room_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='battle_duration',
            field=models.IntegerField(default=20),
        ),
        migrations.AddField(
            model_name='room',
            name='battle_start_time',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
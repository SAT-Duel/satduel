# Generated by Django 5.0.4 on 2024-07-31 01:17

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0025_rename_tournamentanswer_tournamentquestion'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='country',
            field=models.CharField(default='US', max_length=2),
        ),
        migrations.AddField(
            model_name='profile',
            name='elo_rating',
            field=models.IntegerField(default=1500),
        ),
        migrations.AddField(
            model_name='profile',
            name='max_streak',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='profile',
            name='problems_solved',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='tournament',
            name='end_time',
            field=models.DateTimeField(null=True),
        ),
        migrations.CreateModel(
            name='Ranking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rank', models.PositiveIntegerField(unique=True)),
                ('last_updated', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['rank'],
            },
        ),
    ]

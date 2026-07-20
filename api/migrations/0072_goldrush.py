# Gold Rush party mode: room clock + per-player question walk and chest state.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0071_partyplayer_lives_partyroom_last_standing_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='partyroom',
            name='mode',
            field=models.CharField(
                choices=[(m, m) for m in ('classic', 'teams', 'survival', 'jeopardy', 'goldrush')],
                default='classic', max_length=10),
        ),
        migrations.AlterField(
            model_name='partyroom',
            name='status',
            field=models.CharField(
                choices=[(s, s) for s in
                         ('lobby', 'countdown', 'question', 'wager', 'leaderboard', 'playing', 'finished')],
                default='lobby', max_length=12),
        ),
        migrations.AddField(
            model_name='partyroom',
            name='time_limit',
            field=models.IntegerField(default=600),
        ),
        migrations.AddField(
            model_name='partyplayer',
            name='gq_deck',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='partyplayer',
            name='gq_index',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='partyplayer',
            name='gq_locked_until',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='partyplayer',
            name='gq_pending',
            field=models.JSONField(blank=True, null=True),
        ),
    ]

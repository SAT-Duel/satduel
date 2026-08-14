from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0087_partyroom_original_host'),
    ]

    operations = [
        migrations.AddField(
            model_name='duelemote',
            name='party_room',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='emotes',
                to='api.partyroom',
            ),
        ),
        migrations.AlterField(
            model_name='duelemote',
            name='room',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='emotes',
                to='api.room',
            ),
        ),
        migrations.AddField(
            model_name='practicetest',
            name='premium_only',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddConstraint(
            model_name='duelemote',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(('party_room__isnull', True), ('room__isnull', False))
                    | models.Q(('party_room__isnull', False), ('room__isnull', True))
                ),
                name='reaction_targets_exactly_one_room',
            ),
        ),
    ]

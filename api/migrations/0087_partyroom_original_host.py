from django.db import migrations, models
from django.db.models import F
import django.db.models.deletion


def backfill_original_hosts(apps, schema_editor):
    PartyRoom = apps.get_model('api', 'PartyRoom')
    PartyRoom.objects.filter(original_host__isnull=True).update(original_host_id=F('host_id'))


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0086_remove_unused_statistics_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='partyroom',
            name='original_host',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='created_parties',
                to='auth.user',
            ),
        ),
        migrations.RunPython(backfill_original_hosts, migrations.RunPython.noop),
    ]

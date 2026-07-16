from datetime import date

from django.db import migrations, models


SAT_DATES = (
    date(2026, 8, 22),
    date(2026, 9, 12),
    date(2026, 10, 3),
    date(2026, 11, 7),
    date(2026, 12, 5),
    date(2027, 3, 6),
    date(2027, 5, 1),
    date(2027, 6, 5),
)


def seed_sat_dates(apps, schema_editor):
    SATExamDate = apps.get_model('api', 'SATExamDate')
    SATExamDate.objects.bulk_create(
        [SATExamDate(date=exam_date) for exam_date in SAT_DATES],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0064_drop_orphaned_user_tables'),
    ]

    operations = [
        migrations.CreateModel(
            name='SATExamDate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(unique=True)),
                ('active', models.BooleanField(default=True)),
            ],
            options={'ordering': ['date']},
        ),
        migrations.AddField(
            model_name='profile',
            name='marketing_opt_in',
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='profile',
            name='sat_exam_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='profile',
            name='sat_exam_date_selected',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='profile',
            name='terms_accepted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(seed_sat_dates, migrations.RunPython.noop),
    ]

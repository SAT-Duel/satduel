from django.db import migrations, models


def set_existing_metadata(apps, schema_editor):
    Question = apps.get_model('api', 'Question')
    Question.objects.all().update(source='sat_question_bank')
    for canonical in (
        'One-variable data: distributions and measures of center and spread',
        'Two-variable data: models and scatterplots',
    ):
        Question.objects.filter(question_type__iexact=canonical).update(question_type=canonical)


class Migration(migrations.Migration):
    dependencies = [('api', '0077_directmessage')]

    operations = [
        migrations.AddField(
            model_name='question',
            name='source',
            field=models.CharField(
                choices=[
                    ('sat_question_bank', 'SAT Question Bank'),
                    ('ai_generated', 'AI Generated'),
                    ('other', 'Other'),
                ],
                db_index=True,
                default='other',
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='question',
            name='source_other',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.RunPython(set_existing_metadata, migrations.RunPython.noop),
    ]

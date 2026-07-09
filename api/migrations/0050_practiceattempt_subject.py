from django.db import migrations, models


MATH_QUESTION_TYPES = [
    'Linear equations in one variable',
    'Linear functions',
    'Linear equations in two variables',
    'Systems of two linear equations in two variables',
    'Linear inequalities in one or two variables',
    'Equivalent expressions',
    'Nonlinear equations in one variable and systems of equations in two variables',
    'Nonlinear functions',
    'Ratios, rates, proportional relationships, and units',
    'Percentages',
    'One-variable data: distributions and measures of center and spread',
    'Two-variable data: models and scatterplots',
    'Probability and conditional probability',
    'Inference from sample statistics and margin of error',
    'Evaluating statistical claims: observational studies and experiments',
    'Area and volume',
    'Lines, angles, and triangles',
    'Right triangles and trigonometry',
    'Circles',
]


def backfill_subject(apps, schema_editor):
    PracticeAttempt = apps.get_model('api', 'PracticeAttempt')
    Question = apps.get_model('api', 'Question')
    math_question_ids = Question.objects.filter(
        question_type__in=MATH_QUESTION_TYPES,
    ).values_list('id', flat=True)
    PracticeAttempt.objects.filter(question_id__in=math_question_ids).update(subject='math')


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0049_reset_math_practice_attempts'),
    ]

    operations = [
        migrations.AddField(
            model_name='practiceattempt',
            name='subject',
            field=models.CharField(
                choices=[('english', 'English'), ('math', 'Math')],
                db_index=True,
                default='english',
                max_length=10,
            ),
        ),
        migrations.AddIndex(
            model_name='practiceattempt',
            index=models.Index(fields=['user', 'subject'], name='api_practic_user_id_9678a4_idx'),
        ),
        migrations.RunPython(backfill_subject, migrations.RunPython.noop),
    ]

from django.db import migrations


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


def reset_math_practice(apps, schema_editor):
    Profile = apps.get_model('api', 'Profile')
    PracticeAttempt = apps.get_model('api', 'PracticeAttempt')
    Question = apps.get_model('api', 'Question')

    math_question_ids = Question.objects.filter(
        question_type__in=MATH_QUESTION_TYPES,
    ).values_list('id', flat=True)
    PracticeAttempt.objects.filter(question_id__in=math_question_ids).delete()
    Profile.objects.update(math_elo_rating=1200, active_math_question=None)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0048_profile_active_math_question_profile_math_elo_rating'),
    ]

    operations = [
        migrations.RunPython(reset_math_practice, migrations.RunPython.noop),
    ]

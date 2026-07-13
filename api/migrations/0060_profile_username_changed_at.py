from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0059_practiceattempt_selected_choice'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='username_changed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0058_profile_duel_emotes'),
    ]

    operations = [
        migrations.AddField(
            model_name='practiceattempt',
            name='selected_choice',
            field=models.TextField(blank=True, null=True),
        ),
    ]

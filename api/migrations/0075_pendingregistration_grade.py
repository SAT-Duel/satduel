from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0074_pendingregistration_profile_setup_flags'),
    ]

    operations = [
        migrations.AddField(
            model_name='pendingregistration',
            name='grade',
            field=models.CharField(default='11', max_length=3),
            preserve_default=False,
        ),
    ]

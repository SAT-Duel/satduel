from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0040_drop_orphaned_auth_tables'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='avatar',
            field=models.CharField(
                choices=[
                    ('violet', 'Violet'),
                    ('sky', 'Sky'),
                    ('emerald', 'Emerald'),
                    ('amber', 'Amber'),
                    ('rose', 'Rose'),
                    ('slate', 'Slate'),
                ],
                default='violet',
                max_length=32,
            ),
        ),
    ]

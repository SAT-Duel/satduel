from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0077_directmessage'),
    ]

    operations = [
        migrations.CreateModel(
            name='Announcement',
            fields=[
                ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('message', models.TextField(blank=True, max_length=500)),
                ('is_active', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]

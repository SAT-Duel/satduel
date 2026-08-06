import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0073_practicetestresult'),
    ]

    operations = [
        migrations.CreateModel(
            name='PendingRegistration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('password_hash', models.CharField(max_length=128)),
                ('verification_token', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('terms_accepted_at', models.DateTimeField()),
                ('next_path', models.CharField(blank=True, max_length=500)),
                ('email_sent_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(
            model_name='profile',
            name='grade_selected',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='profile',
            name='username_finalized',
            field=models.BooleanField(default=True),
        ),
    ]

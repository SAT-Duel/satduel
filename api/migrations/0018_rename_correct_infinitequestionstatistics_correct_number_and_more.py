# Generated by Django 5.0.4 on 2024-07-17 13:05

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0017_infinitequestionstatistics_powersprintstatistics_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='infinitequestionstatistics',
            old_name='correct',
            new_name='correct_number',
        ),
        migrations.RenameField(
            model_name='infinitequestionstatistics',
            old_name='incorrect',
            new_name='incorrect_number',
        ),
    ]

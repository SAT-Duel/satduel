# Generated by Django 5.0.4 on 2024-08-15 11:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0035_alter_userinventory_user_house_area_userstatistics_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='userstatistics',
            name='user_pet_levels',
            field=models.JSONField(default=dict),
        ),
        migrations.DeleteModel(
            name='UserAlcumusProfile',
        ),
    ]

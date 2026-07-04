"""
Drop tables left behind by auth libraries removed from INSTALLED_APPS
(django-oauth-toolkit and social-auth-app-django).

Django stopped managing these tables when the apps were uninstalled, but they
still hold foreign-key constraints to auth_user, which breaks user deletion
(admin deletes, account cleanup). They contain only dead tokens.

Runs as RunPython so it can use CASCADE on Postgres (production) while staying
a harmless no-op on local SQLite databases, where the tables never existed.
Also prunes the libraries' rows from django_migrations so a future reinstall
would start clean.
"""
from django.db import migrations

DEAD_TABLES = [
    # django-oauth-toolkit
    'oauth2_provider_accesstoken',
    'oauth2_provider_refreshtoken',
    'oauth2_provider_idtoken',
    'oauth2_provider_grant',
    'oauth2_provider_application',
    # social-auth-app-django
    'social_auth_usersocialauth',
    'social_auth_nonce',
    'social_auth_association',
    'social_auth_code',
    'social_auth_partial',
]


def drop_dead_tables(apps, schema_editor):
    connection = schema_editor.connection
    cascade = ' CASCADE' if connection.vendor == 'postgresql' else ''
    with connection.cursor() as cursor:
        for table in DEAD_TABLES:
            cursor.execute(f'DROP TABLE IF EXISTS {table}{cascade};')
        cursor.execute(
            "DELETE FROM django_migrations WHERE app IN ('oauth2_provider', 'social_django')"
        )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0039_remove_house_user_delete_area_delete_house'),
    ]

    operations = [
        migrations.RunPython(drop_dead_tables, migrations.RunPython.noop),
    ]

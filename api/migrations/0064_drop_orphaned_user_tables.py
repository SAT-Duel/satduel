"""Drop legacy tables whose hidden user foreign keys block account deletion."""

from django.db import migrations


DEAD_TABLES = [
    'api_area',
    'api_house',
    'oauth2_provider_accesstoken',
    'oauth2_provider_refreshtoken',
    'oauth2_provider_idtoken',
    'oauth2_provider_grant',
    'oauth2_provider_application',
    'social_auth_usersocialauth',
    'social_auth_nonce',
    'social_auth_association',
    'social_auth_code',
    'social_auth_partial',
]


def drop_orphaned_user_tables(apps, schema_editor):
    connection = schema_editor.connection
    cascade = ' CASCADE' if connection.vendor == 'postgresql' else ''
    with connection.cursor() as cursor:
        for table in DEAD_TABLES:
            cursor.execute(
                f'DROP TABLE IF EXISTS {schema_editor.quote_name(table)}{cascade}'
            )
        cursor.execute(
            "DELETE FROM django_migrations WHERE app IN ('oauth2_provider', 'social_django')"
        )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0063_questionreport'),
    ]

    operations = [
        migrations.RunPython(drop_orphaned_user_tables, migrations.RunPython.noop),
    ]

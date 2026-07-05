# Generated manually for Stripe Billing integration.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0042_profile_is_premium_profile_premium_until_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='stripe_customer_id',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='profile',
            name='stripe_price_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='profile',
            name='stripe_subscription_id',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
    ]

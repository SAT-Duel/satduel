import logging

import stripe
from django.db import transaction

from api.models import Profile, QuestionReport
from api.views.billing_views import (
    StripeError,
    _configure_stripe,
    _is_resource_missing_error,
    _stripe_ready,
)

logger = logging.getLogger(__name__)


class AccountDeletionError(Exception):
    pass


def delete_user_account(user):
    """Delete billing first, then all local data owned by a user."""
    customer_id = Profile.objects.filter(user=user).values_list(
        'stripe_customer_id', flat=True,
    ).first()

    if customer_id:
        if _stripe_ready():
            raise AccountDeletionError(
                'Billing cleanup is temporarily unavailable. Your account was not deleted.',
            )
        _configure_stripe()
        try:
            # Deleting the Stripe customer immediately cancels subscriptions
            # and removes stored payment details.
            stripe.Customer.delete(customer_id)
        except StripeError as exc:
            if not _is_resource_missing_error(exc):
                logger.exception('Stripe customer deletion failed for user %s', user.pk)
                raise AccountDeletionError(
                    'Could not cancel your billing account. Your SAT Duel account was not deleted.',
                ) from exc

    with transaction.atomic():
        # Reports otherwise anonymize via SET_NULL; permanent account deletion
        # should remove the user's submitted content too.
        QuestionReport.objects.filter(reporter=user).delete()
        user.delete()

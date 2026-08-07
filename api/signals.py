"""Keep the Resend marketing audience in sync with local state.

Two triggers matter for a contact's subscription status:

* ``Profile.marketing_opt_in`` changing (onboarding, admin edits, signup).
* The user's email becoming verified (an opted-in user only counts as a
  deliverable contact once verified).

Both funnel into ``sync_marketing_contact``. The Profile handler is careful not
to hit Resend on unrelated saves (elo updates, streaks, billing): it skips when
``update_fields`` is given without ``marketing_opt_in``, and otherwise only
syncs when the value actually changed.
"""

import logging

from allauth.account.signals import email_confirmed
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from api.marketing import marketing_sync_enabled, sync_marketing_contact
from api.models import Profile

logger = logging.getLogger(__name__)

_OLD_OPT_IN_ATTR = '_old_marketing_opt_in'


@receiver(pre_save, sender=Profile, dispatch_uid='marketing_capture_old_opt_in')
def _capture_old_opt_in(sender, instance, update_fields=None, **kwargs):
    # Cheap early-out for hot paths that explicitly save unrelated fields.
    if update_fields is not None and 'marketing_opt_in' not in update_fields:
        return
    if not instance.pk:
        return  # brand-new profile; the post_save "created" branch handles it
    old = sender.objects.filter(pk=instance.pk).values_list(
        'marketing_opt_in', flat=True,
    ).first()
    setattr(instance, _OLD_OPT_IN_ATTR, old)


@receiver(post_save, sender=Profile, dispatch_uid='marketing_sync_on_profile_save')
def _sync_on_profile_save(sender, instance, created, update_fields=None, **kwargs):
    if not marketing_sync_enabled():
        return
    if update_fields is not None and 'marketing_opt_in' not in update_fields and not created:
        return

    if created:
        should_sync = True
    elif hasattr(instance, _OLD_OPT_IN_ATTR):
        should_sync = getattr(instance, _OLD_OPT_IN_ATTR) != instance.marketing_opt_in
    else:
        should_sync = False

    if should_sync and instance.user_id:
        sync_marketing_contact(instance.user)


@receiver(email_confirmed, dispatch_uid='marketing_sync_on_email_confirmed')
def _sync_on_email_confirmed(request, email_address, **kwargs):
    # A newly verified, opted-in user now qualifies as a deliverable contact.
    if not marketing_sync_enabled():
        return
    user = getattr(email_address, 'user', None)
    if user is not None:
        sync_marketing_contact(user)

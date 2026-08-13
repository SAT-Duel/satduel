"""Side effects that hang off account lifecycle events.

Email confirmation fans out to two independent receivers: the welcome email
(everyone) and the Resend audience sync (opted-in users only).

For the marketing sync, two triggers matter for a contact's subscription status:

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
from django.db.models.signals import post_migrate, post_save, pre_save
from django.dispatch import receiver

from api.emails import send_welcome_email
from api.marketing import marketing_sync_enabled, sync_marketing_contact
from api.models import Profile, TestPrep, TestSection

logger = logging.getLogger(__name__)

_OLD_OPT_IN_ATTR = '_old_marketing_opt_in'


@receiver(post_migrate, dispatch_uid='seed_test_prep_catalog')
def _seed_test_prep_catalog(sender, **kwargs):
    """Keep required lookup rows available after flushes and fresh installs."""
    if sender.name != 'api':
        return
    catalog = [
        ('sat', 'SAT', True), ('act', 'ACT', False),
        ('ssat', 'SSAT', False), ('gre', 'GRE', False),
    ]
    sections = {
        'sat': [('english', 'Reading and Writing'), ('math', 'Math')],
        'act': [('english', 'English'), ('math', 'Math'), ('reading', 'Reading'), ('science', 'Science')],
        'ssat': [('verbal', 'Verbal'), ('quantitative', 'Quantitative'), ('reading', 'Reading'), ('writing', 'Writing Sample')],
        'gre': [('verbal', 'Verbal Reasoning'), ('quantitative', 'Quantitative Reasoning'), ('analytical-writing', 'Analytical Writing')],
    }
    for display_order, (code, name, active) in enumerate(catalog, start=1):
        TestPrep.objects.get_or_create(
            code=code,
            defaults={'name': name, 'active': active, 'display_order': display_order},
        )
        for section_order, (section_code, section_name) in enumerate(sections[code], start=1):
            TestSection.objects.get_or_create(
                test_prep_id=code, code=section_code,
                defaults={'name': section_name, 'display_order': section_order},
            )


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


@receiver(email_confirmed, dispatch_uid='welcome_email_on_email_confirmed')
def _welcome_on_email_confirmed(request, email_address, **kwargs):
    """Verification is the moment the account becomes real — greet the user.

    Sent to everyone regardless of ``marketing_opt_in``: this is a one-time
    onboarding email about the account they just created, not a campaign.
    Recurring/promotional sends belong in Resend, which honours the opt-in.

    ponytail: no "already welcomed" flag, so changing your email address and
    re-verifying sends a second welcome. Add a Profile boolean if that ever
    shows up in support mail.
    """
    user = getattr(email_address, 'user', None)
    if user is not None and user.email:
        send_welcome_email(user)

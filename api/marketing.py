"""Sync marketing consent (``Profile.marketing_opt_in``) to Resend.

The local database stays the source of truth; Resend is a mirror we push to.
Marketing/broadcast email goes through Resend (a dedicated sending path) rather
than the transactional SMTP backend in settings, so campaign sends never affect
the deliverability of password resets and email confirmations.

A contact is treated as *subscribed* only when the user has opted in **and** has
a verified email address — sending campaigns to unverified addresses hurts
sender reputation. Everyone else is pushed as ``unsubscribed`` so Resend
suppresses them until they qualify (see the ``email_confirmed`` hook in
``signals.py``).

All functions are best-effort: a Resend outage must never break signup,
onboarding, or account deletion. The ``sync_marketing_audience`` management
command reconciles any drift that a transient failure leaves behind.
"""

import base64
import binascii
import hashlib
import hmac
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

RESEND_API_BASE = 'https://api.resend.com'
_TIMEOUT = 10  # seconds; keep short so a slow Resend never stalls a request


def marketing_sync_enabled():
    """True when a Resend API key is configured (otherwise every call no-ops)."""
    return bool(getattr(settings, 'RESEND_API_KEY', ''))


def _headers():
    return {
        'Authorization': f'Bearer {settings.RESEND_API_KEY}',
        'Content-Type': 'application/json',
    }


def is_subscribed(user):
    """A user should receive marketing only if opted in AND email-verified."""
    profile = getattr(user, 'profile', None)
    if not (profile and profile.marketing_opt_in):
        return False
    # Iterate (not .filter) so a prefetched emailaddress_set is reused — the
    # reconcile command prefetches it to avoid a query per user.
    return any(ea.verified for ea in user.emailaddress_set.all())


def sync_marketing_contact(user):
    """Mirror a user's subscription state into Resend. Never raises.

    Upserts the contact by email: PATCH first (the common case — the contact
    already exists), falling back to POST when Resend reports it is missing.
    """
    if not marketing_sync_enabled():
        return False

    email = (user.email or '').strip()
    if not email:
        return False

    fields = {
        'first_name': user.first_name or '',
        'last_name': user.last_name or '',
        'unsubscribed': not is_subscribed(user),
    }

    try:
        resp = requests.patch(
            f'{RESEND_API_BASE}/contacts/{email}',
            json=fields,
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code == 404:
            resp = requests.post(
                f'{RESEND_API_BASE}/contacts',
                json={'email': email, **fields},
                headers=_headers(),
                timeout=_TIMEOUT,
            )
        resp.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception('Resend contact sync failed for user %s', getattr(user, 'pk', '?'))
        return False


def remove_marketing_contact(email):
    """Delete a contact from Resend (e.g. on account deletion). Never raises."""
    if not marketing_sync_enabled():
        return False

    email = (email or '').strip()
    if not email:
        return False

    try:
        resp = requests.delete(
            f'{RESEND_API_BASE}/contacts/{email}',
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        # A missing contact is already in the desired state.
        if resp.status_code != 404:
            resp.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception('Resend contact delete failed for %s', email)
        return False


def verify_webhook_signature(payload, svix_id, svix_timestamp, svix_signature):
    """Verify a Resend (Svix) webhook signature.

    ``payload`` is the raw request body (bytes). Returns True only when the
    signature matches the configured ``RESEND_WEBHOOK_SECRET``.
    """
    secret = getattr(settings, 'RESEND_WEBHOOK_SECRET', '')
    if not (secret and svix_id and svix_timestamp and svix_signature):
        return False

    # Secret is delivered as "whsec_<base64>"; the signing key is the base64 part.
    secret_key = secret[len('whsec_'):] if secret.startswith('whsec_') else secret
    try:
        secret_bytes = base64.b64decode(secret_key)
    except (ValueError, binascii.Error):
        return False

    signed_content = f'{svix_id}.{svix_timestamp}.'.encode() + payload
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode()

    # The header holds one or more space-delimited "v1,<signature>" entries.
    for part in svix_signature.split():
        _, _, sig = part.partition(',')
        if sig and hmac.compare_digest(sig, expected):
            return True
    return False

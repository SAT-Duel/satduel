import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


logger = logging.getLogger(__name__)


def send_branded_email(recipient, subject, template_name, context=None):
    context = {
        **(context or {}),
        'brand_name': 'SAT Duel',
        'logo_url': f"{settings.FRONTEND_URL.rstrip('/')}/logo192.png",
        'site_url': settings.FRONTEND_URL.rstrip('/'),
        'support_email': settings.SUPPORT_EMAIL,
    }
    text = render_to_string(f'emails/{template_name}.txt', context).strip()
    html = render_to_string(f'emails/{template_name}.html', context)
    email = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        reply_to=[settings.SUPPORT_EMAIL],
    )
    email.attach_alternative(html, 'text/html')
    return email.send()


def send_registration_verification_email(recipient, activate_url):
    return send_branded_email(
        recipient,
        'Verify your SAT Duel email',
        'verify_email',
        {'action_url': activate_url},
    )


def send_password_link_email(user):
    action = 'Change' if user.has_usable_password() else 'Set'
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    action_url = f"{settings.FRONTEND_URL.rstrip('/')}/api/reset/{uid}/{token}/"
    return send_branded_email(
        user.email,
        f'{action} your SAT Duel password',
        'password_link',
        {
            'action': action.lower(),
            'action_label': f'{action} password',
            'action_url': action_url,
            'first_name': user.first_name,
        },
    )


def send_welcome_email(user):
    """One-time onboarding email, sent when the user verifies their address.

    Never raises: a send failure must not break email confirmation, which is
    what actually activates the account.
    """
    site = settings.FRONTEND_URL.rstrip('/')
    try:
        return send_branded_email(
            user.email,
            'Welcome to SAT Duel',
            'welcome',
            {
                'first_name': user.first_name,
                'practice_url': f'{site}/infinite_questions',
                'party_url': f'{site}/party',
                'discord_url': settings.DISCORD_INVITE_URL,
            },
        )
    except Exception:
        logger.exception('Could not send the welcome email to user %s', user.pk)
        return 0


def send_password_changed_email(user):
    try:
        return send_branded_email(
            user.email,
            'Your SAT Duel password was changed',
            'password_changed',
            {
                'first_name': user.first_name,
                'reset_url': f"{settings.FRONTEND_URL.rstrip('/')}/password_reset",
            },
        )
    except Exception:
        logger.exception('Password changed, but the confirmation email could not be sent for user %s', user.pk)
        return 0

"""The welcome email fires on verification and never breaks confirmation."""

from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.account.signals import email_confirmed
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class WelcomeEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='rookie', email='rookie@example.com',
            password='pw', first_name='Rookie',
        )
        self.address = EmailAddress.objects.create(
            user=self.user, email=self.user.email, verified=True, primary=True,
        )
        mail.outbox = []

    def _confirm(self):
        email_confirmed.send(
            sender=EmailAddress, request=None, email_address=self.address,
        )

    def test_verification_sends_a_welcome_with_both_next_steps(self):
        self._confirm()

        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['rookie@example.com'])
        self.assertEqual(sent.subject, 'Welcome to SAT Duel')

        html = sent.alternatives[0][0]
        for body in (sent.body, html):
            self.assertIn('Rookie', body)
            self.assertIn('/infinite_questions', body)
            self.assertIn('/party', body)
            self.assertIn('discord.gg', body)
        # No unrendered template variables leaked into either part.
        self.assertNotIn('{{', sent.body + html)

    def test_a_send_failure_does_not_break_confirmation(self):
        with patch('api.emails.EmailMultiAlternatives.send', side_effect=OSError('smtp down')):
            self._confirm()  # must not raise

        self.assertEqual(len(mail.outbox), 0)

from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings

import logging
logger = logging.getLogger(__name__)

class CustomAccountAdapter(DefaultAccountAdapter):
    def send_confirmation_mail(self, request, emailconfirmation, signup):
        activate_url = f"{settings.FRONTEND_URL}/confirm-email/{emailconfirmation.key}/"
        ctx = {
            "user": emailconfirmation.email_address.user,
            "activate_url": activate_url,
            "key": emailconfirmation.key,
        }
        logger.info("Sending account confirmation email")
        self.send_mail("account/email/email_confirmation", emailconfirmation.email_address.email, ctx)

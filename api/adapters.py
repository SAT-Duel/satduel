from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings

import logging
logger = logging.getLogger(__name__)

class CustomAccountAdapter(DefaultAccountAdapter):
    def send_confirmation_mail(self, request, emailconfirmation, signup):
        try:
            activate_url = f"{settings.FRONTEND_URL}/confirm-email/{emailconfirmation.key}/"
            ctx = {
                "user": emailconfirmation.email_address.user,
                "activate_url": activate_url,
                "key": emailconfirmation.key,
            }
            logger.info(f"Sending confirmation email to {emailconfirmation.email_address.email}")
            self.send_mail("account/email/email_confirmation", emailconfirmation.email_address.email, ctx)
            logger.info("Confirmation email sent successfully")
        except Exception as e:
            logger.error(f"Failed to send confirmation email: {str(e)}")

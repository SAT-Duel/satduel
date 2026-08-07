"""Inbound Resend webhook: keep ``marketing_opt_in`` honest.

When a user clicks the unsubscribe link inside a campaign, Resend flips the
contact's ``unsubscribed`` flag and sends a ``contact.updated`` event. We mirror
that back into the local flag so onboarding and any future email-preference UI
reflect reality. The update uses a queryset ``.update()`` so it does not re-fire
the outbound sync signal.
"""

import json
import logging

from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from api.marketing import verify_webhook_signature
from api.models import Profile

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def resend_webhook(request):
    if not verify_webhook_signature(
        request.body,
        request.META.get('HTTP_SVIX_ID', ''),
        request.META.get('HTTP_SVIX_TIMESTAMP', ''),
        request.META.get('HTTP_SVIX_SIGNATURE', ''),
    ):
        return Response({'error': 'invalid_signature'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        event = json.loads(request.body)
    except (ValueError, TypeError):
        return Response({'error': 'invalid_payload'}, status=status.HTTP_400_BAD_REQUEST)

    if event.get('type') == 'contact.updated':
        data = event.get('data') or {}
        email = (data.get('email') or '').strip()
        unsubscribed = bool(data.get('unsubscribed'))
        if email:
            # Mirror Resend's global unsubscribe state onto the local flag.
            # .update() intentionally bypasses the post_save sync signal.
            Profile.objects.filter(user__email__iexact=email).update(
                marketing_opt_in=not unsubscribed,
            )

    return Response({'received': True})

import logging
from datetime import datetime, timezone as datetime_timezone

import stripe
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.models import Profile

logger = logging.getLogger(__name__)

ACTIVE_SUBSCRIPTION_STATUSES = {'active', 'trialing'}
StripeError = getattr(getattr(stripe, 'error', None), 'StripeError', getattr(stripe, 'StripeError', Exception))


def _configure_stripe():
    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = settings.STRIPE_API_VERSION


def _stripe_ready(require_price=False, require_webhook=False):
    missing = []
    if not settings.STRIPE_SECRET_KEY:
        missing.append('STRIPE_SECRET_KEY')
    if require_price and not settings.STRIPE_PREMIUM_PRICE_ID:
        missing.append('STRIPE_PREMIUM_PRICE_ID')
    if require_webhook and not settings.STRIPE_WEBHOOK_SECRET:
        missing.append('STRIPE_WEBHOOK_SECRET')
    return missing


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _metadata_get(obj, key, default=None):
    metadata = _get(obj, 'metadata', {}) or {}
    return _get(metadata, key, default)


def _timestamp_to_datetime(timestamp):
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, tz=datetime_timezone.utc)


def _subscription_period_end(subscription):
    period_end = _get(subscription, 'current_period_end')
    if period_end:
        return _timestamp_to_datetime(period_end)

    items = _get(subscription, 'items', {}) or {}
    item_data = _get(items, 'data', []) or []
    if item_data:
        return _timestamp_to_datetime(_get(item_data[0], 'current_period_end'))
    return None


def _subscription_price_id(subscription):
    items = _get(subscription, 'items', {}) or {}
    item_data = _get(items, 'data', []) or []
    if not item_data:
        return None
    price = _get(item_data[0], 'price')
    return _get(price, 'id')


def _profile_for_subscription(subscription):
    subscription_id = _get(subscription, 'id')
    customer_id = _get(subscription, 'customer')
    user_id = _metadata_get(subscription, 'user_id')

    if subscription_id:
        profile = Profile.objects.filter(stripe_subscription_id=subscription_id).first()
        if profile:
            return profile
    if customer_id:
        profile = Profile.objects.filter(stripe_customer_id=customer_id).first()
        if profile:
            return profile
    if user_id:
        return Profile.objects.filter(user_id=user_id).first()
    return None


def _apply_subscription(profile, subscription):
    subscription_id = _get(subscription, 'id')
    customer_id = _get(subscription, 'customer')
    price_id = _subscription_price_id(subscription)
    subscription_status = _get(subscription, 'status', '')
    is_active = subscription_status in ACTIVE_SUBSCRIPTION_STATUSES
    period_end = _subscription_period_end(subscription)

    if customer_id:
        profile.stripe_customer_id = customer_id
    if subscription_id:
        profile.stripe_subscription_id = subscription_id
    if price_id:
        profile.stripe_price_id = price_id

    profile.is_premium = is_active
    profile.premium_until = period_end if is_active else timezone.now()
    profile.save(update_fields=[
        'stripe_customer_id',
        'stripe_subscription_id',
        'stripe_price_id',
        'is_premium',
        'premium_until',
    ])


def _get_or_create_customer(profile):
    if profile.stripe_customer_id:
        return profile.stripe_customer_id

    user = profile.user
    customer = stripe.Customer.create(
        email=user.email or None,
        name=user.get_full_name() or user.username,
        metadata={'user_id': str(user.id), 'username': user.username},
    )
    profile.stripe_customer_id = customer.id
    profile.save(update_fields=['stripe_customer_id'])
    return customer.id


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def create_checkout_session(request):
    missing = _stripe_ready(require_price=True)
    if missing:
        return Response(
            {'error': 'stripe_not_configured', 'missing': missing},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    profile = request.user.profile
    _configure_stripe()
    success_url = f"{settings.FRONTEND_URL.rstrip('/')}/pricing?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{settings.FRONTEND_URL.rstrip('/')}/pricing?checkout=cancelled"

    try:
        customer_id = _get_or_create_customer(profile)
        session_params = {
            'mode': 'subscription',
            'customer': customer_id,
            'client_reference_id': str(request.user.id),
            'line_items': [{'price': settings.STRIPE_PREMIUM_PRICE_ID, 'quantity': 1}],
            'success_url': success_url,
            'cancel_url': cancel_url,
            'allow_promotion_codes': True,
            'billing_address_collection': 'auto',
            'customer_update': {'address': 'auto', 'name': 'auto'},
            'metadata': {'user_id': str(request.user.id)},
            'subscription_data': {'metadata': {'user_id': str(request.user.id)}},
        }
        if settings.STRIPE_AUTOMATIC_TAX:
            session_params['automatic_tax'] = {'enabled': True}

        session = stripe.checkout.Session.create(**session_params)
    except StripeError as exc:
        logger.exception('Stripe checkout session creation failed')
        return Response(
            {'error': 'stripe_checkout_failed', 'detail': str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response({'url': session.url})


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def create_portal_session(request):
    missing = _stripe_ready()
    if missing:
        return Response(
            {'error': 'stripe_not_configured', 'missing': missing},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    profile = request.user.profile
    if not profile.stripe_customer_id:
        return Response(
            {'error': 'stripe_customer_missing', 'detail': 'Start checkout before opening the billing portal.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    _configure_stripe()
    try:
        session_params = {
            'customer': profile.stripe_customer_id,
            'return_url': f"{settings.FRONTEND_URL.rstrip('/')}/settings",
        }
        if settings.STRIPE_PORTAL_CONFIGURATION_ID:
            session_params['configuration'] = settings.STRIPE_PORTAL_CONFIGURATION_ID

        session = stripe.billing_portal.Session.create(**session_params)
    except StripeError as exc:
        logger.exception('Stripe portal session creation failed')
        return Response(
            {'error': 'stripe_portal_failed', 'detail': str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response({'url': session.url})


def _handle_checkout_completed(session):
    if _get(session, 'mode') != 'subscription':
        return

    user_id = _get(session, 'client_reference_id') or _metadata_get(session, 'user_id')
    customer_id = _get(session, 'customer')
    subscription_id = _get(session, 'subscription')

    profile = None
    if user_id:
        profile = Profile.objects.filter(user_id=user_id).first()
    if profile is None and customer_id:
        profile = Profile.objects.filter(stripe_customer_id=customer_id).first()
    if profile is None:
        logger.warning('Checkout completed for unknown user/customer: %s', customer_id)
        return

    if customer_id and profile.stripe_customer_id != customer_id:
        profile.stripe_customer_id = customer_id
        profile.save(update_fields=['stripe_customer_id'])
    if subscription_id:
        subscription = stripe.Subscription.retrieve(subscription_id)
        _apply_subscription(profile, subscription)


def _handle_subscription_event(subscription):
    profile = _profile_for_subscription(subscription)
    if profile is None:
        logger.warning('Subscription event for unknown customer: %s', _get(subscription, 'customer'))
        return
    _apply_subscription(profile, subscription)


@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def stripe_webhook(request):
    missing = _stripe_ready(require_webhook=True)
    if missing:
        return Response(
            {'error': 'stripe_not_configured', 'missing': missing},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    _configure_stripe()
    payload = request.body
    signature = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return Response({'error': 'invalid_payload'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        if exc.__class__.__name__ == 'SignatureVerificationError':
            return Response({'error': 'invalid_signature'}, status=status.HTTP_400_BAD_REQUEST)
        raise

    event_type = _get(event, 'type')
    event_object = _get(_get(event, 'data', {}), 'object')

    try:
        if event_type == 'checkout.session.completed':
            _handle_checkout_completed(event_object)
        elif event_type in {'customer.subscription.created', 'customer.subscription.updated'}:
            _handle_subscription_event(event_object)
        elif event_type == 'customer.subscription.deleted':
            profile = _profile_for_subscription(event_object)
            if profile:
                profile.is_premium = False
                profile.premium_until = timezone.now()
                profile.save(update_fields=['is_premium', 'premium_until'])
        elif event_type == 'invoice.paid':
            subscription_id = _get(event_object, 'subscription')
            if subscription_id:
                subscription = stripe.Subscription.retrieve(subscription_id)
                _handle_subscription_event(subscription)
    except StripeError:
        logger.exception('Stripe webhook processing failed')
        return Response(
            {'error': 'webhook_processing_failed'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response({'received': True})

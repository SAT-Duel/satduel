"""Reconcile the Resend marketing audience with local subscription state.

Run once to backfill existing users into Resend, and re-run any time to repair
drift left by a transient webhook/API failure (the inline signal sync is
best-effort and swallows errors). Idempotent.

    python manage.py sync_marketing_audience
    python manage.py sync_marketing_audience --dry-run
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from api.marketing import is_subscribed, marketing_sync_enabled, sync_marketing_contact


class Command(BaseCommand):
    help = "Push every user's marketing subscription state to Resend."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be synced without calling Resend.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if not marketing_sync_enabled() and not dry_run:
            self.stderr.write(self.style.ERROR(
                'RESEND_API_KEY is not set; nothing to sync. '
                'Set it (or use --dry-run) and try again.'
            ))
            return

        users = (
            User.objects
            .filter(email__gt='')
            .exclude(profile__is_bot=True)
            .select_related('profile')
            .prefetch_related('emailaddress_set')
            .order_by('pk')
        )

        synced = subscribed = failed = 0
        for user in users.iterator(chunk_size=500):
            will_subscribe = is_subscribed(user)
            subscribed += 1 if will_subscribe else 0

            if dry_run:
                state = 'subscribed' if will_subscribe else 'unsubscribed'
                self.stdout.write(f'{user.email}: {state}')
                synced += 1
                continue

            if sync_marketing_contact(user):
                synced += 1
            else:
                failed += 1
                self.stderr.write(self.style.WARNING(f'Failed to sync {user.email}'))

        summary = (
            f'{"[dry-run] " if dry_run else ""}Processed {synced + failed} users '
            f'({subscribed} subscribed).'
        )
        if failed:
            self.stdout.write(self.style.WARNING(f'{summary} {failed} failed — re-run to retry.'))
        else:
            self.stdout.write(self.style.SUCCESS(summary))

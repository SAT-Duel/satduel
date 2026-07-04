"""
Delete abandoned signups: accounts that never verified their email, never
logged in, and are older than a cutoff. Dry-run by default.

    python manage.py cleanup_unverified_users            # preview only
    python manage.py cleanup_unverified_users --delete   # actually delete
    python manage.py cleanup_unverified_users --days 60 --delete
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from allauth.account.models import EmailAddress


class Command(BaseCommand):
    help = "Delete unverified, never-logged-in accounts older than --days (dry-run unless --delete)."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30,
                            help='Minimum account age in days (default: 30).')
        parser.add_argument('--delete', action='store_true',
                            help='Actually delete. Without this flag, only previews.')

    def handle(self, *args, **options):
        days = options['days']
        cutoff = timezone.now() - timedelta(days=days)

        verified_ids = set(
            EmailAddress.objects.filter(verified=True).values_list('user_id', flat=True)
        )
        stale = (
            User.objects
            .exclude(id__in=verified_ids)      # no verified email
            .filter(last_login__isnull=True)   # never logged in
            .filter(date_joined__lt=cutoff)    # old enough
            .filter(is_staff=False, is_superuser=False)  # never touch staff
            .order_by('date_joined')
        )

        count = stale.count()
        self.stdout.write(f"Matched {count} stale account(s) "
                          f"(unverified, never logged in, joined before {cutoff.date()}).")
        for u in stale[:100]:
            self.stdout.write(f"  - {u.username} <{u.email}> joined {u.date_joined.date()}")
        if count > 100:
            self.stdout.write(f"  ... and {count - 100} more")

        if not options['delete']:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing deleted. Re-run with --delete to remove these accounts."))
            return

        with transaction.atomic():
            deleted, _ = stale.delete()
        self.stdout.write(self.style.SUCCESS(f"\nDeleted {count} account(s) ({deleted} rows total)."))

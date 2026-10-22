import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections

from notifications.push import process_push_jobs, push_config
from notifications.services import reconcile_menus

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Reconcile menu events/deadlines and send queued Web Push. Run one instance."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=2.0)

    def handle(self, *args, **options):
        if options["interval"] < 1:
            raise CommandError("Minimum interval is one second.")
        if getattr(settings, "NOTIFICATIONS_PUSH_ENABLED", False):
            if not push_config():
                raise CommandError("Push keys are missing. Run generate_push_keys, or disable Push.")
            try:
                import pywebpush  # noqa: F401
            except ImportError:
                raise CommandError("Install requirements-notifications.txt first.")

        self.stdout.write("Notification worker running. Stop with Ctrl+C.")
        try:
            while True:
                close_old_connections()
                try:
                    events = reconcile_menus()
                    pushed = process_push_jobs()
                    if events or pushed:
                        self.stdout.write(f"Menu events: {events}; processed push jobs: {pushed}")
                except DatabaseError:
                    logger.warning("Database busy; worker will retry on next cycle.")
                    if options["once"]:
                        raise
                if options["once"]:
                    break
                time.sleep(options["interval"])
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped.")

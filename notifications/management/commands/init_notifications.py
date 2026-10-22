from django.core.management.base import BaseCommand
from kitchen.models import DailyMenu
from notifications.services import observe_menu


class Command(BaseCommand):
    help = "Record existing menu states WITHOUT sending retrospective notifications."

    def handle(self, *args, **options):
        count = 0
        for pk in DailyMenu.objects.values_list("pk", flat=True):
            observe_menu(pk, baseline=True)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Initialized {count} menu states. No messages sent."))

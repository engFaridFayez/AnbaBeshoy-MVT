"""Explicit opt-in: grant inventory permissions to an EXISTING administrator."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Grant store website permissions without enabling staff or superuser access."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist as error:
            raise CommandError("Username not found.") from error
        if not user.is_active or getattr(user, "role", "") not in ("admin", "superadmin"):
            raise CommandError("The account must already be active and role=admin or superadmin.")
        codes = [f"{action}_{model}" for model in ("category", "unitofmeasure", "product")
                 for action in ("view", "add", "change", "delete")]
        codes += ["view_stockbatch", "view_stockmovement", "add_stockmovement", "view_stockalert"]
        permissions = Permission.objects.filter(content_type__app_label="store", codename__in=codes)
        if permissions.count() != len(codes):
            raise CommandError("Store permissions are missing. Apply migrations first.")
        # Grant only the explicit permissions above, leaving existing groups unchanged.
        with transaction.atomic():
            user.user_permissions.add(*permissions)
        self.stdout.write(self.style.SUCCESS(
            f"Store access granted to {user.username}. Staff, role and superuser flags unchanged."
        ))

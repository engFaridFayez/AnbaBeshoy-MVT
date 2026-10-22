import base64
import json
import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email


class Command(BaseCommand):
    help = "Create VAPID keys locally. Never put .secrets/ in static/ or source control."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)

    def handle(self, *args, **options):
        email = options["email"].strip()
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError("Supply a real contact email.")
        try:
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization
        except ImportError:
            raise CommandError("Install requirements-notifications.txt first.")

        path = Path(getattr(
            settings, "NOTIFICATIONS_VAPID_FILE",
            Path(settings.BASE_DIR) / ".secrets" / "webpush.json",
        ))
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_path = path.parent / "webpush-private.pem"
        if path.exists() or private_path.exists():
            raise CommandError("Keys already exist. Do not replace live keys; subscribers use them.")
        private = ec.generate_private_key(ec.SECP256R1())
        pem = private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
        public = private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
        )
        public_key = base64.urlsafe_b64encode(public).rstrip(b"=").decode()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        with os.fdopen(os.open(private_path, flags, 0o600), "wb") as fh:
            fh.write(pem)
        config = {
            "public_key": public_key,
            "private_key_file": private_path.name,
            "subject": f"mailto:{email}",
        }
        with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
        self.stdout.write(self.style.SUCCESS("Keys created in .secrets. Restart server and worker."))
        self.stdout.write("Keep the private key secret and retain it across deployments.")

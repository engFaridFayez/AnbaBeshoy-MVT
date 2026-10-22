import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import F
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from .models import MenuState, Notice, PushJob
from .security import validate_endpoint
from .services import is_effectively_open


def push_config():
    if not getattr(settings, "NOTIFICATIONS_PUSH_ENABLED", False):
        return {}
    path = Path(getattr(
        settings, "NOTIFICATIONS_VAPID_FILE",
        Path(settings.BASE_DIR) / ".secrets" / "webpush.json",
    ))
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        private_path = path.parent / values["private_key_file"]
        if not private_path.is_file():
            return {}
        return {
            "public_key": values["public_key"],
            "private_key": str(private_path),
            "subject": values["subject"],
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def retry_job(job, reason):
    if job.attempts >= 5:
        job.status = PushJob.Status.FAILED
    else:
        job.status = PushJob.Status.PENDING
        job.next_attempt_at = timezone.now() + timedelta(seconds=min(3600, 15 * 2 ** job.attempts))
    job.last_error = reason[:120]
    job.locked_at = None
    job.save(update_fields=["status", "last_error", "next_attempt_at", "locked_at"])


def send_job(job, cfg):
    # Imports remain optional for an in-app-only installation.
    import requests
    from pywebpush import WebPushException, webpush
    from django.core.exceptions import ValidationError

    notice = job.receipt.notice
    sub = job.subscription
    now = timezone.now()
    stale_event = False

    if notice.kind != Notice.Kind.MANUAL:
        state = MenuState.objects.filter(menu_id=notice.menu_id).first()
        stale_event = (
            notice.menu is None or state is None or state.revision != notice.menu_revision
            or (
                is_effectively_open(notice.menu, now)
                != (notice.kind == Notice.Kind.OPEN)
            )
        )

    if (
        not sub.active or not sub.user.is_active
        or sub.user_id != job.receipt.user_id or sub.generation != job.generation
        or notice.push_expires_at <= now or job.receipt.read_at is not None
        or stale_event
    ):
        job.status = PushJob.Status.SKIPPED
        job.last_error = "expired_or_inactive_or_superseded"
        job.locked_at = None
        job.save(update_fields=["status", "last_error", "locked_at"])
        return

    try:
        validate_endpoint(sub.endpoint)
    except ValidationError:
        job.status = PushJob.Status.FAILED
        job.last_error = "blocked_endpoint"
        job.locked_at = None
        job.save(update_fields=["status", "last_error", "locked_at"])
        return

    payload = json.dumps({
        "title": notice.title,
        "body": notice.body,
        "tag": f"notice-{notice.pk}",
        "url": reverse("notifications:detail", args=[job.receipt_id]),
        "icon": static("notifications/icon-192.png"),
        "badge": static("notifications/badge.png"),
    }, ensure_ascii=False)

    class SafeSession(requests.Session):
        def request(self, method, url, **kwargs):
            kwargs["allow_redirects"] = False
            return super().request(method, url, **kwargs)

    try:
        with SafeSession() as http:
            response = webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=cfg["private_key"],
                vapid_claims={"sub": cfg["subject"]},
                ttl=max(1, min(10800, int((notice.push_expires_at - now).total_seconds()))),
                timeout=8,
                requests_session=http,
                headers={"Urgency": "normal"},
            )
        if not 200 <= response.status_code < 300:
            raise WebPushException("non_success", response=response)
    except WebPushException as exc:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status in (404, 410):
            sub.active = False
            sub.save(update_fields=["active"])
            job.status = PushJob.Status.SKIPPED
            job.last_error = "subscription_expired"
        elif status is None or status == 429 or status >= 500:
            retry_job(job, f"push_http_{status or 'network'}")
            return
        else:
            job.status = PushJob.Status.FAILED
            job.last_error = f"push_http_{status}"
    except requests.RequestException:
        retry_job(job, "network_error")
        return
    except (ValueError, TypeError, OSError):
        retry_job(job, "vapid_or_payload_error")
        return
    else:
        # SENT means accepted by the push provider, not seen by the person.
        job.status = PushJob.Status.SENT
        job.last_error = ""

    job.locked_at = None
    job.save(update_fields=["status", "last_error", "locked_at"])


def process_push_jobs(limit=30):
    cfg = push_config()
    if not cfg:
        return 0
    now = timezone.now()
    PushJob.objects.filter(
        status=PushJob.Status.SENDING,
        locked_at__lt=now - timedelta(minutes=5),
    ).update(status=PushJob.Status.PENDING, locked_at=None)
    ids = list(PushJob.objects.filter(
        status=PushJob.Status.PENDING, next_attempt_at__lte=now,
    ).order_by("pk").values_list("pk", flat=True)[:limit])
    count = 0
    for pk in ids:
        claimed = PushJob.objects.filter(
            pk=pk, status=PushJob.Status.PENDING,
        ).update(
            status=PushJob.Status.SENDING,
            locked_at=timezone.now(), attempts=F("attempts") + 1,
        )
        if not claimed:
            continue
        job = PushJob.objects.select_related(
            "receipt__notice__menu", "subscription__user",
        ).get(pk=pk)
        send_job(job, cfg)
        count += 1
    return count

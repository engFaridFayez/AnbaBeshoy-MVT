import uuid

from django.conf import settings
from django.db import models


class MenuAudience(models.Model):
    """An empty selected audience means nobody, never 'all'."""
    class Mode(models.TextChoices):
        ALL = "all", "كل الحسابات النشطة"
        SELECTED = "selected", "مستخدمون محددون"

    menu = models.OneToOneField(
        "kitchen.DailyMenu", on_delete=models.CASCADE,
        related_name="notification_audience",
    )
    enabled = models.BooleanField(default=True, verbose_name="الإشعارات التلقائية")
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.ALL)
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="menu_notification_audiences",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.menu)


class MenuState(models.Model):
    """Durable last-observed state; compare-and-swap revision prevents duplicates."""
    menu = models.OneToOneField(
        "kitchen.DailyMenu", on_delete=models.CASCADE, related_name="notification_state",
    )
    is_open = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class Notice(models.Model):
    class Kind(models.TextChoices):
        OPEN = "open", "فتح قائمة"
        CLOSE = "close", "إغلاق قائمة"
        MANUAL = "manual", "رسالة من المسؤول"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=600)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    menu = models.ForeignKey("kitchen.DailyMenu", null=True, blank=True, on_delete=models.SET_NULL)
    menu_date = models.DateField(null=True, blank=True)
    meal_type = models.CharField(max_length=10, blank=True)
    menu_revision = models.PositiveIntegerField(null=True, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="sent_notices",
    )
    dedupe_key = models.CharField(max_length=160, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    push_expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Receipt(models.Model):
    notice = models.ForeignKey(Notice, on_delete=models.CASCADE, related_name="receipts")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notice_receipts",
    )
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["notice", "user"], name="notice_unique_recipient"),
        ]
        indexes = [
            models.Index(fields=["user", "read_at"], name="notice_unread_idx"),
        ]


class PushSubscription(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="webpush_subscriptions",
    )
    endpoint_hash = models.CharField(max_length=64, unique=True)
    endpoint = models.TextField()
    p256dh = models.CharField(max_length=180)
    auth = models.CharField(max_length=80)
    session_tag = models.CharField(max_length=64)
    generation = models.PositiveIntegerField(default=1)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class PushJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "في انتظار الإرسال"
        SENDING = "sending", "جارٍ الإرسال"
        SENT = "sent", "قبلته خدمة Push"
        FAILED = "failed", "تعذر الإرسال"
        SKIPPED = "skipped", "تم التجاوز"

    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name="push_jobs")
    subscription = models.ForeignKey(PushSubscription, on_delete=models.CASCADE)
    generation = models.PositiveIntegerField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    locked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=120, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["receipt", "subscription"], name="notice_unique_device_job",
            ),
        ]

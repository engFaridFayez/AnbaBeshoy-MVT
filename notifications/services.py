from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from kitchen.models import DailyMenu

from .models import MenuAudience, MenuState, Notice, PushJob, PushSubscription, Receipt


def is_manager(user):
    return bool(
        user.is_authenticated and user.is_active
        and getattr(user, "role", None) in ("admin", "superadmin")
    )


def eligible_users():
    # "Select all" means all active accounts, including administrators.
    return get_user_model().objects.filter(is_active=True).order_by("username")


def is_effectively_open(menu, now=None):
    now = now or timezone.now()
    return bool(
        menu.is_published
        and (menu.ordering_deadline is None or now < menu.ordering_deadline)
        and menu.entries.filter(is_available=True, item__is_active=True).exists()
    )


def current_menu_url(notice):
    # The existing menu_view only serves today; do not route an old/future
    # notice to an unrelated menu with the same meal name.
    if notice.menu_id and notice.menu_date == timezone.localdate():
        return reverse("kitchen:menu") + "?" + urlencode({"meal": notice.meal_type})
    return None


def menu_recipients(menu):
    policy = MenuAudience.objects.filter(menu=menu).first()
    users = eligible_users()
    if policy is None:
        return users
    if not policy.enabled:
        return users.none()
    if policy.mode == MenuAudience.Mode.SELECTED:
        return users.filter(pk__in=policy.users.values("pk"))
    return users


@transaction.atomic
def create_notice(*, title, body, kind, recipients, dedupe_key,
                  actor=None, menu=None, revision=None):
    now = timezone.now()
    expires = now + timedelta(hours=24 if kind == Notice.Kind.MANUAL else 3)
    if menu and kind == Notice.Kind.OPEN and menu.ordering_deadline:
        expires = min(expires, menu.ordering_deadline)

    notice, created = Notice.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "title": title, "body": body, "kind": kind,
            "actor": actor, "menu": menu,
            "menu_date": menu.date if menu else None,
            "meal_type": menu.meal_type if menu else "",
            "menu_revision": revision, "push_expires_at": expires,
        },
    )
    if not created:
        return notice, False

    user_ids = list(recipients.filter(is_active=True).values_list("pk", flat=True).distinct())
    Receipt.objects.bulk_create([
        Receipt(notice=notice, user_id=user_id) for user_id in user_ids
    ], batch_size=300)

    receipt_ids = dict(notice.receipts.values_list("user_id", "pk"))
    subscriptions = PushSubscription.objects.filter(
        user_id__in=user_ids, active=True,
    )
    PushJob.objects.bulk_create([
        PushJob(
            receipt_id=receipt_ids[sub.user_id],
            subscription=sub, generation=sub.generation, next_attempt_at=now,
        ) for sub in subscriptions
    ], batch_size=300)
    return notice, True


@transaction.atomic
def observe_menu(menu_id, *, baseline=False):
    """Observe committed state. No network I/O and no publication modification."""
    menu = DailyMenu.objects.filter(pk=menu_id).first()
    if menu is None:
        return False
    now = timezone.now()
    opened = is_effectively_open(menu, now)
    state, created = MenuState.objects.get_or_create(
        menu=menu, defaults={"is_open": opened if baseline else False},
    )
    if baseline:
        if created:
            return False
        # Never reset an existing revision during initialization.
        return False
    if state.is_open == opened:
        return False

    # A database compare-and-swap, not only a Python-level check.
    changed = MenuState.objects.filter(
        pk=state.pk, revision=state.revision, is_open=state.is_open,
    ).update(
        is_open=opened, revision=F("revision") + 1, updated_at=now,
    )
    if not changed:
        return False

    revision = state.revision + 1
    # Do not broadcast stale historical menus.
    if menu.date < timezone.localdate():
        return True

    label = menu.get_meal_type_display()
    date_label = menu.date.strftime("%Y-%m-%d")
    if opened:
        title = f"تم فتح قائمة {label}"
        if menu.date == timezone.localdate():
            body = f"قائمة {label} ليوم {date_label} متاحة الآن. افتح الوجبة وسجّل طلبك."
        else:
            body = f"تم نشر قائمة {label} ليوم {date_label}. تظهر صفحة طلبها في يوم الوجبة."
        kind = Notice.Kind.OPEN
    else:
        title = f"تم إغلاق طلبات {label}"
        body = f"تم إغلاق قائمة {label} ليوم {date_label}. الطلبات المسجلة سابقًا محفوظة."
        kind = Notice.Kind.CLOSE

    create_notice(
        title=title, body=body, kind=kind,
        recipients=menu_recipients(menu), menu=menu,
        dedupe_key=f"menu:{menu.pk}:revision:{revision}",
        revision=revision,
    )
    return True


def reconcile_menus():
    # Recovers queryset.update()/bulk changes and detects an elapsed deadline.
    since = timezone.localdate() - timedelta(days=1)
    count = 0
    for pk in DailyMenu.objects.filter(date__gte=since).values_list("pk", flat=True):
        count += int(observe_menu(pk))
    return count

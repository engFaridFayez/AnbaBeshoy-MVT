import hashlib
import json
import uuid
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from kitchen.models import DailyMenu
from .forms import AutoAudienceForm, ComposeForm
from .models import MenuAudience, Notice, PushJob, PushSubscription, Receipt
from .push import push_config
from .security import session_tag, validate_subscription
from .services import create_notice, current_menu_url, is_manager


def manager_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_manager(request.user):
            raise PermissionDenied("هذه الصفحة لمسؤول المطعم والمطور فقط.")
        return view(request, *args, **kwargs)
    return wrapped


def api_login(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_active:
            return JsonResponse({"error": "يلزم تسجيل الدخول."}, status=401)
        return view(request, *args, **kwargs)
    return wrapped


@login_required
@require_GET
@never_cache
def inbox(request):
    receipts = Receipt.objects.filter(user=request.user).select_related("notice")
    page = Paginator(receipts, 20).get_page(request.GET.get("page"))
    return render(request, "notifications/inbox.html", {"page_obj": page})


@login_required
@require_GET
@never_cache
def detail(request, pk):
    receipt = get_object_or_404(
        Receipt.objects.select_related("notice"), pk=pk, user=request.user,
    )
    return render(request, "notifications/detail.html", {
        "receipt": receipt, "meal_url": current_menu_url(receipt.notice),
    })


@login_required
@require_POST
def read_notice(request, pk):
    receipt = get_object_or_404(
        Receipt.objects.select_related("notice"), pk=pk, user=request.user,
    )
    if receipt.read_at is None:
        receipt.read_at = timezone.now()
        receipt.save(update_fields=["read_at"])
    target = current_menu_url(receipt.notice)
    if request.POST.get("open_menu") and target:
        return redirect(target)
    return redirect("notifications:detail", pk=receipt.pk)


@login_required
@require_POST
def read_all(request):
    Receipt.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return redirect("notifications:inbox")


@require_GET
@api_login
@never_cache
def feed(request):
    receipts = Receipt.objects.filter(user=request.user).select_related("notice")
    rows = list(receipts[:15])
    return JsonResponse({
        "unread": receipts.filter(read_at__isnull=True).count(),
        "latest_id": rows[0].pk if rows else 0,
        "items": [{
            "id": row.pk,
            "title": row.notice.title,
            "body": row.notice.body,
            "kind": row.notice.kind,
            "read": row.read_at is not None,
            "created_at": row.created_at.isoformat(),
            "url": reverse("notifications:detail", args=[row.pk]),
        } for row in rows],
    })


def issue_token(user):
    return signing.dumps(
        {"user": str(user.pk), "id": str(uuid.uuid4())},
        salt="notifications.compose",
    )


@manager_required
@require_http_methods(["GET", "POST"])
@never_cache
def manage(request):
    menu_id = request.GET.get("menu") or request.POST.get("policy_menu")
    menu = None
    if menu_id:
        try:
            menu = get_object_or_404(DailyMenu, pk=int(menu_id))
        except (TypeError, ValueError, OverflowError):
            raise Http404
    menus = DailyMenu.objects.filter(
        date__gte=timezone.localdate(),
    ).order_by("date", "meal_type")
    policy = MenuAudience.objects.filter(menu=menu).first() if menu else None

    auto_initial = {
        "mode": policy.mode if policy else "all",
        "enabled": policy.enabled if policy else True,
        "users": list(policy.users.values_list("pk", flat=True)) if policy else [],
    }
    compose = ComposeForm(
        prefix="send",
        initial={"mode": "all", "token": issue_token(request.user), "menu": menu},
    )
    auto_form = AutoAudienceForm(prefix="auto", initial=auto_initial)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "send":
            compose = ComposeForm(request.POST, prefix="send")
            if compose.is_valid():
                try:
                    token = signing.loads(
                        compose.cleaned_data["token"], salt="notifications.compose", max_age=86400,
                    )
                    if token["user"] != str(request.user.pk):
                        raise signing.BadSignature
                    token_id = str(uuid.UUID(token["id"]))
                except (signing.BadSignature, KeyError, ValueError, TypeError):
                    compose.add_error(None, "انتهت صلاحية النموذج. حدّث الصفحة ثم أعد المحاولة.")
                else:
                    notice, created = create_notice(
                        title=compose.cleaned_data["title"],
                        body=compose.cleaned_data["body"],
                        kind=Notice.Kind.MANUAL,
                        recipients=compose.recipients(),
                        menu=compose.cleaned_data["menu"],
                        actor=request.user,
                        dedupe_key=f"manual:{request.user.pk}:{token_id}",
                    )
                    count = notice.receipts.count()
                    messages.success(
                        request,
                        f"تم حفظ الإشعار لـ {count} مستخدم. تنبيهات الأجهزة المفعّلة في قائمة الإرسال."
                        if created else "هذا الإشعار مسجل بالفعل؛ لم يُرسل مرتين.",
                    )
                    return redirect("notifications:manage")

        elif action == "audience":
            if menu is None:
                messages.error(request, "اختَر قائمة الوجبة أولًا.")
                return redirect("notifications:manage")
            auto_form = AutoAudienceForm(request.POST, prefix="auto")
            if auto_form.is_valid():
                with transaction.atomic():
                    policy, _ = MenuAudience.objects.get_or_create(menu=menu)
                    policy.mode = auto_form.cleaned_data["mode"]
                    policy.enabled = auto_form.cleaned_data["enabled"]
                    policy.save()
                    policy.users.set(
                        auto_form.cleaned_data["users"]
                        if policy.mode == MenuAudience.Mode.SELECTED else []
                    )
                messages.success(
                    request, "تم حفظ المستلمين للأحداث القادمة. لم يُرسل إشعار بمجرد تغيير الإعدادات.",
                )
                return redirect(reverse("notifications:manage") + f"?menu={menu.pk}")
        else:
            messages.error(request, "العملية غير صحيحة.")
            return redirect("notifications:manage")

    recent = list(Notice.objects.select_related("actor").order_by("-created_at")[:10])
    for notice in recent:
        notice.recipient_count = notice.receipts.count()
        jobs = PushJob.objects.filter(receipt__notice=notice)
        notice.push_sent_count = jobs.filter(status=PushJob.Status.SENT).count()
        notice.push_failed_count = jobs.filter(status=PushJob.Status.FAILED).count()
        notice.push_pending_count = jobs.filter(
            status__in=[PushJob.Status.PENDING, PushJob.Status.SENDING],
        ).count()

    return render(request, "notifications/manage.html", {
        "compose_form": compose, "audience_form": auto_form,
        "policy_menu": menu, "menus": menus, "recent_notices": recent,
    })


@require_GET
@api_login
@never_cache
def config(request):
    cfg = push_config()
    return JsonResponse({
        "enabled": bool(cfg),
        "public_key": cfg.get("public_key", ""),
        "worker_url": reverse("notifications_worker"),
        "scope": "/",
    })


def read_json(request):
    if len(request.body) > 12000:
        raise ValidationError("حجم البيانات غير مسموح.")
    try:
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValidationError("بيانات غير صحيحة.")


@require_POST
@api_login
@never_cache
def subscribe(request):
    if not push_config():
        return JsonResponse({"error": "لم يتم إعداد Push على السيرفر بعد."}, status=503)
    try:
        values = validate_subscription(read_json(request))
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)

    with transaction.atomic():
        sub = PushSubscription.objects.select_for_update().filter(
            endpoint_hash=values["endpoint_hash"],
        ).first()
        if sub:
            # Someone who only knows an endpoint must not take over a subscription.
            if sub.p256dh != values["p256dh"] or sub.auth != values["auth"]:
                return JsonResponse({"error": "تعارض في اشتراك الجهاز. أوقف الإشعارات ثم فعّلها."}, status=409)
            if sub.user_id != request.user.pk or not sub.active:
                sub.generation += 1
            sub.user = request.user
            sub.session_tag = session_tag(request)
            sub.active = True
            sub.save()
        else:
            if PushSubscription.objects.filter(user=request.user, active=True).count() >= 10:
                return JsonResponse({"error": "وصل الحساب للحد الأقصى للأجهزة المفعّلة."}, status=400)
            sub, created = PushSubscription.objects.get_or_create(
                endpoint_hash=values["endpoint_hash"],
                defaults={
                    "endpoint": values["endpoint"], "p256dh": values["p256dh"],
                    "auth": values["auth"], "user": request.user,
                    "session_tag": session_tag(request),
                },
            )
            if not created:
                # Another tab registered it between the lookup and insert.
                if sub.user_id != request.user.pk or sub.p256dh != values["p256dh"] or sub.auth != values["auth"]:
                    return JsonResponse({"error": "حدث تعارض. أعد المحاولة."}, status=409)
                sub.active = True
                sub.session_tag = session_tag(request)
                sub.save(update_fields=["active", "session_tag", "updated_at"])
    return JsonResponse({"ok": True})


@require_POST
@api_login
@never_cache
def unsubscribe(request):
    try:
        data = read_json(request)
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)
    endpoint = data.get("endpoint", "") if isinstance(data, dict) else ""
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        return JsonResponse({"error": "بيانات غير صحيحة."}, status=400)
    digest = hashlib.sha256(endpoint.encode()).hexdigest()
    PushSubscription.objects.filter(
        user=request.user, endpoint_hash=digest,
    ).update(active=False)
    return JsonResponse({"ok": True})


@require_GET
@never_cache
def worker_script(request):
    path = Path(__file__).parent / "static" / "notifications" / "worker.js"
    response = HttpResponse(path.read_text(encoding="utf-8"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def manifest(request):
    return JsonResponse({
        "id": "/", "name": "طلبات دير الأنبا بيشوي",
        "short_name": "طلبات الدير", "lang": "ar", "dir": "rtl",
        "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#f7f2e9", "theme_color": "#581a2d",
        "icons": [
            {"src": static("notifications/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("notifications/icon-512.png"), "sizes": "512x512", "type": "image/png"},
        ],
    }, content_type="application/manifest+json")

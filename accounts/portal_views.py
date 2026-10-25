"""اختيار خدمات الدير بعد تسجيل الدخول."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from store.web_permissions import can_access_store


@login_required
@require_GET
def services_home(request):

    if not request.user.is_active:
        raise PermissionDenied

    context = {
        "current_user": request.user,
        "today": timezone.localdate(),

        # يظهر المخزن فقط للمسؤول
        "can_access_store": can_access_store(
            request.user
        ),
    }

    return render(
        request,
        "accounts/services_home.html",
        context,
    )
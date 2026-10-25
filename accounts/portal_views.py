"""The new service chooser. Existing accounts.views.home remains the meals page."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET


@login_required
@require_GET
def services_home(request):
    if not request.user.is_active:
        raise PermissionDenied
    return render(request, "accounts/services_home.html", {
        "current_user": request.user, "today": timezone.localdate(),
    })

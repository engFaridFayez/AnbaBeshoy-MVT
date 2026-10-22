from django.urls import reverse
from .services import is_manager


def notification_ui(request):
    user = getattr(request, "user", None)
    return {
        "notices_manager": bool(user and is_manager(user)),
    }

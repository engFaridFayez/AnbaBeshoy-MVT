"""Shared visual identity. No database queries or model changes."""
from django.conf import settings


def monastery_branding(request):
    options = getattr(settings, "MONASTERY_BRANDING", {}) or {}
    try:
        splash_ms = int(options.get("splash_ms", 1500))
    except (TypeError, ValueError):
        splash_ms = 1500
    splash_ms = max(0, min(splash_ms, 3000))

    return {
        "monastery_brand": {
            "title": options.get("title") or "دير الأنبا بيشوي العامر",
            "subtitle": options.get("subtitle") or "خدمة الوجبات وطلبات الدير",
            "main_image": options.get("main_image")
                or "images/branding/monastery.jpg",
            # Empty means no second image, not a request for a missing file.
            "saint_image": options.get("saint_image") or "",
            "splash_enabled": bool(options.get("splash_enabled", True))
                and splash_ms > 0,
            # String avoids localized separators inside HTML data-*.
            "splash_ms": str(splash_ms),
        }
    }

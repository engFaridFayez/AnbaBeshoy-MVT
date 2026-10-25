
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from notifications import views as notification_views
urlpatterns = [
    path(
        "admin/",
        admin.site.urls,
    ),

    path(
        "kitchen/",
        include("kitchen.urls"),
    ),

    path(
        "",
        include("accounts.urls"),
    ),
    path(
    "notifications/",
    include("notifications.urls"),
),

path(
    "notifications-sw.js",
    notification_views.worker_script,
    name="notifications_worker",
),

path(
    "notifications.webmanifest",
    notification_views.manifest,
    name="notifications_manifest",
),
path("store/", include("store.web_urls")),
]
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

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

    path(
        "store/",
        include("store.web_urls"),
    ),

    path(
        "",
        include("accounts.urls"),
    ),
]


if settings.DEBUG:

    # Static files: CSS / JS / Images
    urlpatterns = staticfiles_urlpatterns() + urlpatterns

    # Uploaded media files
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
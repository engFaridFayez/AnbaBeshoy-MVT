from django.urls import path
from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("manage/", views.manage, name="manage"),
    path("message/<int:pk>/", views.detail, name="detail"),
    path("message/<int:pk>/read/", views.read_notice, name="read"),
    path("read-all/", views.read_all, name="read_all"),
    path("api/feed/", views.feed, name="feed"),
    path("api/config/", views.config, name="config"),
    path("api/subscribe/", views.subscribe, name="subscribe"),
    path("api/unsubscribe/", views.unsubscribe, name="unsubscribe"),
]

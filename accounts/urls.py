
from django.urls import path
from django.contrib.auth.views import LogoutView
from . import portal_views
from . import views


app_name = "accounts"

urlpatterns = [

    path("", portal_views.services_home, name="home"),

    path("meals/", views.home, name="meals"),

    path(
        "login/",
        views.UserLoginView.as_view(),
        name="login",
    ),

    path(
        "logout/",
        LogoutView.as_view(
            next_page="accounts:login"
        ),
        name="logout",
    ),

    path(
        "dashboard/",
        views.admin_dashboard,
        name="admin_dashboard",
    ),

]

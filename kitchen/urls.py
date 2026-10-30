
from django.urls import path
from . import views


app_name = "kitchen"


urlpatterns = [

    path(
        "",
        views.menu_view,
        name="menu",
    ),

    path(
        "dashboard/",
        views.restaurant_dashboard,
        name="dashboard",
    ),

    path(
        "manage-menu/",
        views.manage_daily_menu,
        name="manage_menu",
    ),
    path(
    "items/",
    views.menu_items_manage,
    name="menu_items_manage",
),

path(
    "items/<int:pk>/edit/",
    views.menu_item_edit,
    name="menu_item_edit",
),

]

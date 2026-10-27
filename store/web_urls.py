from django.urls import path
from . import web_views as views

app_name = "store"
urlpatterns = [
    path("", views.catalog, name="catalog"),
    path("products/add/", views.product_edit, name="product_add"),
    path("products/<int:pk>/", views.product_detail, name="product"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/receive/", views.stock_operation, {"operation": "receive"}, name="receive"),
    path("products/<int:pk>/issue/", views.stock_operation, {"operation": "issue"}, name="issue"),
    path("products/<int:pk>/movements/", views.movements, name="movements"),
    path("settings/<str:kind>/", views.reference_list, name="references"),
    path("settings/<str:kind>/add/", views.reference_edit, name="reference_add"),
    path("settings/<str:kind>/<int:pk>/edit/", views.reference_edit, name="reference_edit"),
    path("remove/<str:kind>/<int:pk>/", views.delete_empty, name="delete"),
    path(
    "expiry/soon/",
    views.expiring_products,
    name="expiring_products",
),

path(
    "expiry/expired/",
    views.expired_products,
    name="expired_products",
),
]

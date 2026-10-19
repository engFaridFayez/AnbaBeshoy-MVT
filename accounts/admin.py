from django.contrib import admin

# Register your models here.

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model


User = get_user_model()


@admin.register(User)
class CustomUserAdmin(UserAdmin):

    list_display = (
        "username",
        "display_name",
        "role",
        "is_active",
        "is_staff",
        "date_joined",
    )

    list_display_links = (
        "username",
        "display_name",
    )

    list_filter = (
        "role",
        "is_active",
        "is_staff",
        "is_superuser",
    )

    search_fields = (
        "username",
        "display_name",
        "first_name",
        "last_name",
        "email",
    )

    ordering = ("username",)

    list_per_page = 25

    fieldsets = (
        (
            "بيانات تسجيل الدخول",
            {
                "fields": (
                    "username",
                    "password",
                )
            },
        ),
        (
            "البيانات الشخصية",
            {
                "fields": (
                    "display_name",
                    "first_name",
                    "last_name",
                    "email",
                )
            },
        ),
        (
            "نوع الحساب",
            {
                "fields": (
                    "role",
                    "is_active",
                )
            },
        ),
        (
            "صلاحيات Django",
            {
                "classes": ("collapse",),
                "fields": (
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (
            "تواريخ الحساب",
            {
                "classes": ("collapse",),
                "fields": (
                    "last_login",
                    "date_joined",
                ),
            },
        ),
    )

    add_fieldsets = (
        (
            "إنشاء حساب جديد",
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "display_name",
                    "role",
                    "password1",
                    "password2",
                    "is_active",
                    "is_staff",
                ),
            },
        ),
    )

    readonly_fields = (
        "last_login",
        "date_joined",
    )

    filter_horizontal = (
        "groups",
        "user_permissions",
    )

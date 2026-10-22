from django.contrib import admin
from django.db.models import Count
from .models import Notice, Receipt, PushJob


class DeveloperReadOnlyAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notice)
class NoticeAdmin(DeveloperReadOnlyAdmin):
    list_display = ("title", "kind", "created_at", "actor")
    list_filter = ("kind", "created_at")
    search_fields = ("title", "body")
    list_select_related = ("actor",)


@admin.register(PushJob)
class PushJobAdmin(DeveloperReadOnlyAdmin):
    list_display = ("id", "status", "attempts", "next_attempt_at", "last_error")
    list_filter = ("status",)
    exclude = ("subscription",)  # Do not expose endpoint/key details in the UI.


@admin.register(Receipt)
class ReceiptAdmin(DeveloperReadOnlyAdmin):
    list_display = ("id", "user", "notice", "read_at", "created_at")
    list_select_related = ("user", "notice")


from django.contrib import admin
from django.db.models import Count, Sum, Q
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import (
    MenuItem,
    DailyMenu,
    DailyMenuItem,
    Order,
    OrderItem,
)


# ==========================================
# 1. MENU ITEMS
# ==========================================

@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "item_icon",
        "name",
        "category",
        "is_active",
        "created_at",
    )

    list_display_links = (
        "id",
        "name",
    )

    list_editable = (
        "is_active",
    )

    list_filter = (
        "category",
        "is_active",
        "created_at",
    )

    search_fields = (
        "name",
    )

    ordering = (
        "category",
        "name",
    )

    list_per_page = 30

    fields = (
        "name",
        "category",
        "icon",
        "is_active",
    )

    @admin.display(description="الأيقونة")
    def item_icon(self, obj):
        return obj.icon or "🍲"


# ==========================================
# 2. DAILY MENU ITEMS INLINE
# ==========================================

class DailyMenuItemInline(admin.TabularInline):

    model = DailyMenuItem

    extra = 1

    autocomplete_fields = (
        "item",
    )

    fields = (
        "item",
        "is_available",
    )

    verbose_name = "صنف في القائمة"
    verbose_name_plural = "أصناف الوجبة"


# ==========================================
# 3. DAILY MENUS
# ==========================================

@admin.register(DailyMenu)
class DailyMenuAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "date",
        "meal_type",
        "is_published",
        "available_items_count",
        "ordering_deadline",
    )

    list_display_links = (
        "id",
        "date",
    )

    list_editable = (
        "is_published",
    )

    list_filter = (
        "date",
        "meal_type",
        "is_published",
    )

    search_fields = (
        "entries__item__name",
    )

    ordering = (
        "-date",
        "meal_type",
    )

    date_hierarchy = "date"

    list_per_page = 30

    inlines = [
        DailyMenuItemInline,
    ]

    fieldsets = (
        (
            "بيانات الوجبة",
            {
                "fields": (
                    "date",
                    "meal_type",
                )
            },
        ),
        (
            "إعدادات الطلب",
            {
                "fields": (
                    "is_published",
                    "ordering_deadline",
                )
            },
        ),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        return queryset.annotate(
            available_count=Count(
                "entries",
                filter=Q(
                    entries__is_available=True
                ),
                distinct=True,
            )
        )

    @admin.display(description="الأصناف المتاحة")
    def available_items_count(self, obj):
        return obj.available_count


# ==========================================
# 4. DAILY MENU ITEM ADMIN
# ==========================================

@admin.register(DailyMenuItem)
class DailyMenuItemAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "item",
        "get_date",
        "get_meal",
        "is_available",
    )

    list_filter = (
        "is_available",
        "daily_menu__meal_type",
        "daily_menu__date",
    )

    search_fields = (
        "item__name",
        "daily_menu__meal_type",
    )

    list_select_related = (
        "item",
        "daily_menu",
    )

    autocomplete_fields = (
        "daily_menu",
        "item",
    )

    ordering = (
        "-daily_menu__date",
    )

    @admin.display(description="التاريخ")
    def get_date(self, obj):
        return obj.daily_menu.date

    @admin.display(description="الوجبة")
    def get_meal(self, obj):
        return obj.daily_menu.get_meal_type_display()


# ==========================================
# 5. ORDER ITEM FORMSET VALIDATION
# ==========================================

class OrderItemInlineFormSet(BaseInlineFormSet):

    def clean(self):
        super().clean()

        # Skip additional validation if fields have errors
        if any(self.errors):
            return

        # Existing orders are read-only at item level
        if self.instance.pk:
            return

        daily_menu_id = self.instance.daily_menu_id

        if not daily_menu_id:
            raise ValidationError(
                "يجب اختيار الوجبة أولاً."
            )

        selected_items = set()
        valid_items_count = 0

        for form in self.forms:

            if not form.cleaned_data:
                continue

            if form.cleaned_data.get("DELETE"):
                continue

            daily_menu_item = form.cleaned_data.get(
                "daily_menu_item"
            )

            quantity = form.cleaned_data.get(
                "quantity"
            )

            if not daily_menu_item:
                continue

            if not quantity or quantity < 1:
                raise ValidationError(
                    "يجب إدخال كمية صحيحة أكبر من صفر."
                )

            # Check item belongs to selected meal
            if (
                daily_menu_item.daily_menu_id
                != daily_menu_id
            ):
                raise ValidationError(
                    "يوجد صنف لا ينتمي للوجبة المحددة."
                )

            # Check item availability
            if not daily_menu_item.is_available:
                raise ValidationError(
                    "لا يمكن طلب صنف غير متاح."
                )

            if not daily_menu_item.item.is_active:
                raise ValidationError(
                    "لا يمكن طلب صنف غير نشط."
                )

            # Prevent duplicate items
            if daily_menu_item.pk in selected_items:
                raise ValidationError(
                    "لا يمكن إضافة نفس الصنف مرتين."
                )

            selected_items.add(daily_menu_item.pk)
            valid_items_count += 1

        if valid_items_count == 0:
            raise ValidationError(
                "يجب إضافة صنف واحد على الأقل للطلب."
            )


# ==========================================
# 6. ORDER ITEMS INLINE
# ==========================================

class OrderItemInline(admin.TabularInline):

    model = OrderItem

    formset = OrderItemInlineFormSet

    extra = 3

    autocomplete_fields = (
        "daily_menu_item",
    )

    fields = (
        "daily_menu_item",
        "quantity",
        "item_name_snapshot",
        "category_snapshot",
    )

    readonly_fields = (
        "item_name_snapshot",
        "category_snapshot",
    )

    verbose_name = "صنف مطلوب"
    verbose_name_plural = "الأصناف المطلوبة"

    def get_readonly_fields(self, request, obj=None):

        if obj is not None:
            return self.fields

        return self.readonly_fields

    def has_add_permission(self, request, obj=None):

        if obj is not None:
            return False

        return super().has_add_permission(
            request,
            obj,
        )

    def has_delete_permission(self, request, obj=None):
        return False

    def get_extra(self, request, obj=None, **kwargs):

        if obj is not None:
            return 0

        return 3


# ==========================================
# 7. ORDERS ADMIN
# ==========================================

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "user",
        "order_date",
        "meal_name",
        "status",
        "total_items",
        "created_at",
    )

    list_display_links = (
        "id",
        "user",
    )

    list_filter = (
        "status",
        "daily_menu__meal_type",
        "daily_menu__date",
        "created_at",
    )

    search_fields = (
        "user__username",
        "user__display_name",
    )

    list_select_related = (
        "user",
        "daily_menu",
    )

    autocomplete_fields = (
        "user",
        "daily_menu",
    )

    ordering = (
        "-created_at",
    )

    list_per_page = 30

    inlines = [
        OrderItemInline,
    ]

    fields = (
        "user",
        "daily_menu",
        "status",
        "created_at",
        "updated_at",
    )

    # --------------------------------------
    # Readonly Fields
    # --------------------------------------

    def get_readonly_fields(self, request, obj=None):

        fields = [
            "created_at",
            "updated_at",
        ]

        if obj is not None:
            fields.extend([
                "user",
                "daily_menu",
            ])

        return fields

    # --------------------------------------
    # Queryset
    # --------------------------------------

    def get_queryset(self, request):

        queryset = super().get_queryset(request)

        return queryset.annotate(
            total_quantity=Sum(
                "items__quantity"
            )
        )

    # --------------------------------------
    # Custom Columns
    # --------------------------------------

    @admin.display(description="التاريخ")
    def order_date(self, obj):
        return obj.daily_menu.date

    @admin.display(description="الوجبة")
    def meal_name(self, obj):
        return obj.daily_menu.get_meal_type_display()

    @admin.display(description="إجمالي الكميات")
    def total_items(self, obj):
        return obj.total_quantity or 0

    # --------------------------------------
    # Allow Add Order
    # --------------------------------------

    def has_add_permission(self, request):

        return super().has_add_permission(
            request
        )

    # --------------------------------------
    # Prevent Order Deletion
    # --------------------------------------

    def has_delete_permission(self, request, obj=None):

        return False


# ==========================================
# 8. ADMIN SITE BRANDING
# ==========================================

admin.site.site_header = "إدارة دير الأنبا بيشوي"

admin.site.site_title = "طلبات الدير"

admin.site.index_title = "لوحة إدارة الطلبات والوجبات"

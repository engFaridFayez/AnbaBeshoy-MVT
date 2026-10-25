"""إدارة بيانات المخزن وعملياته دون تحرير سجل الحركات مباشرة."""
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Case, DecimalField, F, Q, Sum, When
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .admin_forms import IssueStockForm, ReceiveStockForm
from .models import (
    ZERO, INCOMING_TYPES, Category, UnitOfMeasure, Product,
    StockBatch, StockMovement, StockAlert,
)
from .services import can_manage_stock, issue_stock, receive_stock


def signed_quantity(prefix):
    return Case(
        When(
            **{f"{prefix}movement_type__in": INCOMING_TYPES},
            then=F(f"{prefix}quantity"),
        ),
        default=-F(f"{prefix}quantity"),
        output_field=DecimalField(max_digits=18, decimal_places=3),
    )


def badge(text, color, background):
    return format_html(
        '<span style="display:inline-block;padding:4px 9px;border-radius:6px;'
        'color:{};background:{};font-weight:bold">{}</span>',
        color, background, text,
    )


class StoreAdmin(admin.ModelAdmin):
    """صلاحيات Django القياسية مع قصر الإدارة على أدوار المسؤولين."""
    def _role_allowed(self, request):
        return (
            request.user.is_superuser
            or getattr(request.user, "role", "") in ("admin", "superadmin")
        )

    def has_module_permission(self, request):
        return self._role_allowed(request) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return self._role_allowed(request) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self._role_allowed(request) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return self._role_allowed(request) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._role_allowed(request) and super().has_delete_permission(request, obj)


class ReadOnlyStoreAdmin(StoreAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.concrete_fields)


@admin.register(Category)
class CategoryAdmin(StoreAdmin):
    list_display = ("name", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("sort_order", "name")


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(StoreAdmin):
    list_display = ("name", "symbol", "allow_fractions", "is_active")
    list_filter = ("allow_fractions", "is_active")
    search_fields = ("name", "symbol")


@admin.register(Product)
class ProductAdmin(StoreAdmin):
    list_display = (
        "name", "category", "unit", "total_balance", "available_balance",
        "minimum_stock", "stock_status", "operations",
    )
    list_display_links = ("name",)
    list_filter = ("category", "is_active", "requires_expiry_date")
    search_fields = ("name", "code", "=barcode")
    list_select_related = ("category", "unit")
    autocomplete_fields = ("category", "unit")
    readonly_fields = (
        "code", "created_at", "updated_at",
        "total_balance", "available_balance", "stock_status",
    )
    list_per_page = 25

    fieldsets = (
        ("بيانات المنتج", {
            "fields": ("name", "category", "unit", "barcode", "image", "description"),
        }),
        ("إعدادات الرصيد والصلاحية", {
            "fields": (
                "minimum_stock", "requires_expiry_date",
                "expiry_warning_days", "is_active",
            ),
        }),
        ("الأرصدة المحسوبة", {
            "fields": ("total_balance", "available_balance", "stock_status"),
            "description": "الرصيد يتغير من التوريد والصرف، وليس من تعديل المنتج.",
        }),
        ("بيانات النظام", {
            "fields": ("code", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        available = (
            Q(
                is_active=True,
                category__is_active=True,
                unit__is_active=True,
                batches__is_blocked=False,
            )
            & (
                Q(batches__expiry_date__gte=timezone.localdate())
                | Q(
                    requires_expiry_date=False,
                    batches__expiry_date__isnull=True,
                )
            )
        )

        return super().get_queryset(request).select_related(
            "category", "unit"
        ).annotate(
            _stock_total=Sum(
                signed_quantity("batches__movements__"), default=ZERO,
            ),
            _stock_available=Sum(
                signed_quantity("batches__movements__"),
                filter=available,
                default=ZERO,
            ),
        )

    def get_list_display(self, request):
        fields = super().get_list_display(request)
        if not can_manage_stock(request.user):
            return tuple(field for field in fields if field != "operations")
        return fields

    @admin.display(description="الموجود فعليًا", ordering="_stock_total")
    def total_balance(self, obj):
        return f"{obj._stock_total:.3f}" if obj and obj.pk else "0.000"

    @admin.display(description="المتاح للصرف", ordering="_stock_available")
    def available_balance(self, obj):
        return f"{obj._stock_available:.3f}" if obj and obj.pk else "0.000"

    @admin.display(description="حالة الرصيد")
    def stock_status(self, obj):
        if not obj or not obj.pk:
            return "يظهر بعد الحفظ"
        if not (obj.is_active and obj.category.is_active and obj.unit.is_active):
            return badge("موقوف", "#5b5148", "#eee8de")
        if obj._stock_available <= obj.minimum_stock:
            return badge("مخزون منخفض", "#8b2436", "#fce6e7")
        return badge("متاح", "#245347", "#deeee8")

    @admin.display(description="العمليات")
    def operations(self, obj):
        receive_url = reverse(
            "admin:store_product_receive",
            args=[obj.pk],
            current_app=self.admin_site.name,
        )
        issue_url = reverse(
            "admin:store_product_issue",
            args=[obj.pk],
            current_app=self.admin_site.name,
        )
        return format_html(
            '<a href="{}">توريد</a> &nbsp; | &nbsp; <a href="{}">صرف</a>',
            receive_url, issue_url,
        )

    def get_urls(self):
        custom = [
            path(
                "<int:product_id>/receive/",
                self.admin_site.admin_view(self.receive_view),
                name="store_product_receive",
            ),
            path(
                "<int:product_id>/issue/",
                self.admin_site.admin_view(self.issue_view),
                name="store_product_issue",
            ),
        ]
        return custom + super().get_urls()

    def receive_view(self, request, product_id):
        return self.operation_view(request, product_id, receiving=True)

    def issue_view(self, request, product_id):
        return self.operation_view(request, product_id, receiving=False)

    def operation_view(self, request, product_id, *, receiving):
        if request.method not in ("GET", "POST"):
            return HttpResponseNotAllowed(["GET", "POST"])

        product = self.get_object(request, product_id)
        if product is None:
            raise Http404("المنتج غير موجود.")
        if not (
            self.has_view_permission(request, product)
            and can_manage_stock(request.user)
        ):
            raise PermissionDenied("ليس لديك صلاحية تنفيذ حركة مخزن.")

        form_class = ReceiveStockForm if receiving else IssueStockForm
        form = form_class(
            request.POST if request.method == "POST" else None,
            product=product,
        )

        if request.method == "POST" and form.is_valid():
            try:
                service = receive_stock if receiving else issue_stock
                result = service(
                    product_id=product.pk,
                    user=request.user,
                    **form.cleaned_data,
                )
            except ValidationError as error:
                for message in error.messages:
                    form.add_error(None, message)
            else:
                if receiving:
                    message = f"تم تسجيل الوارد. رقم الدفعة: {str(result.code)[:8]}."
                else:
                    message = (
                        "تم تسجيل الصرف بنجاح. "
                        f"عدد الدفعات المستخدمة: {len(result)}."
                    )
                self.message_user(request, message, level=messages.SUCCESS)
                return redirect(reverse(
                    "admin:store_product_changelist",
                    current_app=self.admin_site.name,
                ))

        # قد يكون الرصيد تغيّر أثناء معالجة طلب غير صحيح.
        product.refresh_from_db()
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "تسجيل وارد جديد" if receiving else "صرف من المخزن",
            "product": product,
            "form": form,
            "receiving": receiving,
            "current_stock": product.current_stock,
            "available_stock": product.available_stock,
            "back_url": reverse(
                "admin:store_product_changelist",
                current_app=self.admin_site.name,
            ),
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request, "admin/store/stock_operation.html", context
        )


@admin.register(StockBatch)
class StockBatchAdmin(ReadOnlyStoreAdmin):
    list_display = (
        "id", "product", "received_date", "expiry_date",
        "received_balance", "remaining_balance", "batch_status",
    )
    list_filter = ("source", "is_blocked", "expiry_date", "product__category")
    search_fields = (
        "product__name", "product__code",
        "supplier_batch_number", "supplier_name", "reference",
    )
    date_hierarchy = "received_date"
    list_per_page = 30

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "product", "product__unit"
        ).annotate(
            _remaining=Sum(signed_quantity("movements__"), default=ZERO),
            _received=Sum(
                "movements__quantity",
                filter=Q(movements__movement_type="receipt"),
                default=ZERO,
            ),
        )

    @admin.display(description="الوارد", ordering="_received")
    def received_balance(self, obj):
        return f"{obj._received:.3f}"

    @admin.display(description="المتبقي", ordering="_remaining")
    def remaining_balance(self, obj):
        return f"{obj._remaining:.3f}"

    @admin.display(description="الحالة")
    def batch_status(self, obj):
        if obj._remaining <= ZERO:
            return "نفدت"
        if obj.is_expired:
            return badge("منتهية الصلاحية", "#8b2436", "#fce6e7")
        if obj.is_blocked:
            return badge("موقوفة", "#5b5148", "#eee8de")
        days = obj.days_to_expiry
        if days is not None and days <= obj.product.expiry_warning_days:
            return badge("قرب انتهاء الصلاحية", "#79521e", "#fff0cc")
        return badge("سارية", "#245347", "#deeee8")


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyStoreAdmin):
    list_display = (
        "id", "batch", "movement_type", "quantity",
        "recipient", "performed_by", "created_at",
    )
    list_filter = ("movement_type", "created_at", "batch__product__category")
    list_select_related = ("batch__product", "performed_by")
    search_fields = ("batch__product__name", "recipient", "reference", "notes")
    date_hierarchy = "created_at"
    list_per_page = 40


@admin.register(StockAlert)
class StockAlertAdmin(ReadOnlyStoreAdmin):
    list_display = ("product", "batch", "alert_type", "open_state", "created_at")
    list_filter = ("alert_type", "resolved_at")
    list_select_related = ("product", "batch__product")
    search_fields = ("product__name", "message")

    @admin.display(description="مفتوح", boolean=True)
    def open_state(self, obj):
        return obj.is_open

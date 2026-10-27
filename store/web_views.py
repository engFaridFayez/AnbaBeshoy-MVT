"""Store website. Requires phase-1 models and phase-2 services/admin_forms."""
from functools import wraps
from urllib.parse import urlencode
from .web_selectors import get_expiry_groups
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from .models import ZERO, Category, Product, StockMovement, UnitOfMeasure
from .services import can_manage_stock, issue_stock, receive_stock
from .web_forms import CatalogFilterForm, CategoryForm, ProductForm, UnitForm, WebIssueForm, WebReceiveForm
from .web_permissions import (
    access_flags,
    can_access_store,
    can_see_inactive,
    can_view_history,
    has_store_permission,
)
from .web_selectors import batches_with_balances, batch_row, expiry_product_ids, product_card, products_with_balances, with_display_batches


def store_admin_required(view):

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):

        if not can_access_store(request.user):
            raise PermissionDenied(
                "المخزن متاح للمسؤول فقط."
            )

        return view(
            request,
            *args,
            **kwargs,
        )

    return wrapper

def base_context(request, **context):
    return {**access_flags(request.user), **context}


def visible_products(user):
    qs = products_with_balances()
    if not can_see_inactive(user):
        qs = qs.filter(is_active=True, category__is_active=True, unit__is_active=True)
    return qs


def attach_errors(form, error):
    if hasattr(error, "message_dict"):
        for name, errors in error.message_dict.items():
            for message in errors:
                form.add_error(name if name in form.fields else None, message)
    else:
        for message in error.messages:
            form.add_error(None, message)


def page_context(queryset, request, size=12, page_key="page"):
    page = Paginator(queryset, size).get_page(request.GET.get(page_key))
    params = request.GET.copy()
    params.pop(page_key, None)
    prefix = "?" + params.urlencode()
    prefix += "&" if params else ""
    return page, {
        "previous_url": prefix + urlencode({page_key: page.previous_page_number()}) if page.has_previous() else "",
        "next_url": prefix + urlencode({page_key: page.next_page_number()}) if page.has_next() else "",
        "page_obj": page,
    }


@store_admin_required
@require_GET
def catalog(request):
    can_inactive = can_see_inactive(request.user)

    form = CatalogFilterForm(
        request.GET or None,
        include_inactive_allowed=can_inactive,
    )

    data = form.cleaned_data if form.is_valid() else {}

    products = visible_products(request.user)

    # =====================================
    # Active / inactive products
    # =====================================

    if not (
        can_inactive
        and data.get("include_inactive")
    ):
        products = products.filter(
            is_active=True,
            category__is_active=True,
            unit__is_active=True,
        )

    # =====================================
    # Search
    # =====================================

    keyword = data.get("q", "")

    if keyword:
        products = products.filter(
            Q(name__icontains=keyword)
            | Q(code__iexact=keyword)
            | Q(barcode__iexact=keyword)
        )

    # =====================================
    # Category filter
    # =====================================

    if data.get("category"):
        products = products.filter(
            category=data["category"]
        )

    # =====================================
    # Expiry status
    # =====================================

    soon_ids, expired_ids = expiry_product_ids(
        products.values("pk")
    )

    # =====================================
    # Low stock
    # =====================================

    low_products = products.filter(
        is_active=True,
        category__is_active=True,
        unit__is_active=True,
        ui_available__lte=F("minimum_stock"),
    )

    # =====================================
    # Dashboard counts
    # =====================================

    counts = {
        "products": products.count(),
        "low": low_products.count(),
        "expiring": len(soon_ids),
        "expired": len(expired_ids),
    }

    # =====================================
    # State filter
    # =====================================

    state = data.get("state", "")

    if state == "low":

        products = low_products

    elif state == "expiring":

        products = products.filter(
            pk__in=soon_ids
        )

    elif state == "expired":

        products = products.filter(
            pk__in=expired_ids
        )

    # =====================================
    # Pagination
    # =====================================

    page, pagination = page_context(
        with_display_batches(products),
        request,
    )

    # =====================================
    # Categories
    # =====================================

    category_queryset = (
        Category.objects
        .filter(is_active=True)
        .annotate(
            ui_count=Count(
                "products",
                filter=Q(
                    products__is_active=True,
                    products__unit__is_active=True,
                ),
            )
        )
    )

    # =====================================
    # Template
    # =====================================

    return render(
        request,
        "store/catalog.html",
        base_context(
            request,

            form=form,

            cards=[
                product_card(product)
                for product in page
            ],

            counts=counts,

            # للقسمين الجديدين
            expiring_count=counts["expiring"],
            expired_count=counts["expired"],

            categories=category_queryset,

            **pagination,
        ),
    )


@store_admin_required
@require_GET
def product_detail(request, pk):
    product = get_object_or_404(with_display_batches(visible_products(request.user)), pk=pk)
    card = product_card(product)
    context = base_context(request, card=card, product=product)
    if can_view_history(request.user):
        page, pagination = page_context(batches_with_balances().filter(product=product), request, size=12)
        context.update(pagination)
        context["batch_rows"] = [batch_row(batch) for batch in page]
    return render(request, "store/product_detail.html", context)


@store_admin_required
@require_GET
def movements(request, pk):
    if not can_view_history(request.user):
        raise PermissionDenied
    product = get_object_or_404(Product.objects.select_related("unit"), pk=pk)
    qs = StockMovement.objects.filter(batch__product=product).select_related("batch", "performed_by")
    page, pagination = page_context(qs, request, size=25)
    return render(request, "store/movements.html", base_context(
        request, product=product, movements=page, **pagination,
    ))


@store_admin_required
@require_http_methods(["GET", "POST"])
def stock_operation(request, pk, operation):
    if not can_manage_stock(request.user):
        raise PermissionDenied("ليس لديك صلاحية تسجيل حركات المخزن.")
    product = get_object_or_404(Product.objects.select_related("unit", "category"), pk=pk)
    receiving = operation == "receive"
    if operation not in ("receive", "issue"):
        from django.http import Http404
        raise Http404
    form_class = WebReceiveForm if receiving else WebIssueForm
    form = form_class(request.POST if request.method == "POST" else None, product=product)
    if request.method == "POST" and form.is_valid():
        try:
            service = receive_stock if receiving else issue_stock
            result = service(product_id=product.pk, user=request.user, **form.cleaned_data)
        except ValidationError as error:
            attach_errors(form, error)
        else:
            if receiving:
                message = "تم تسجيل الوارد. رقم الدفعة: " + str(result.code)[:8]
            else:
                message = "تم تسجيل الصرف. عدد الدفعات المستخدمة: " + str(len(result))
            messages.success(request, message)
            return redirect("store:product", pk=product.pk)
    fresh = with_display_batches(products_with_balances()).get(pk=pk)
    return render(request, "store/operation.html", base_context(
        request, form=form, card=product_card(fresh), product=fresh, receiving=receiving,
        page_title="تسجيل وارد" if receiving else "صرف من المخزن",
    ))


@store_admin_required
@require_http_methods(["GET", "POST"])
def product_edit(request, pk=None):
    codename = "change_product" if pk is not None else "add_product"
    if not has_store_permission(request.user, codename):
        raise PermissionDenied
    instance = get_object_or_404(Product, pk=pk) if pk is not None else None
    form = ProductForm(request.POST if request.method == "POST" else None,
                       request.FILES if request.method == "POST" else None, instance=instance)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                product = form.save()
        except ValidationError as error:
            attach_errors(form, error)
        except IntegrityError:
            form.add_error(None, "تعذر الحفظ. راجع تكرار الاسم أو الباركود.")
        else:
            messages.success(request, "تم حفظ بيانات المنتج.")
            # An editor without history access might no longer see an archived product.
            return redirect("store:catalog")
    return render(request, "store/entity_form.html", base_context(
        request, form=form, page_title="تعديل منتج" if instance else "إضافة منتج",
        back_url=reverse("store:catalog"), multipart=True,
        help_text="حفظ المنتج لا يضيف رصيدًا. بعد الحفظ استخد زر توريد.",
    ))


ENTITY_CONFIG = {
    "categories": (Category, CategoryForm, "category", "أقسام المخزن"),
    "units": (UnitOfMeasure, UnitForm, "unitofmeasure", "وحدات القياس"),
}


def entity_config(kind):
    if kind not in ENTITY_CONFIG:
        from django.http import Http404
        raise Http404
    return ENTITY_CONFIG[kind]


@store_admin_required
@require_GET
def reference_list(request, kind):
    model, _, code, title = entity_config(kind)
    flags = {verb: has_store_permission(request.user, f"{verb}_{code}") for verb in ("add", "change", "delete")}
    if not any(flags.values()):
        raise PermissionDenied
    return render(request, "store/reference_list.html", base_context(
        request, objects=model.objects.all(), kind=kind, title=title, actions=flags,
    ))


@store_admin_required
@require_http_methods(["GET", "POST"])
def reference_edit(request, kind, pk=None):
    model, form_class, code, title = entity_config(kind)
    verb = "change" if pk is not None else "add"
    if not has_store_permission(request.user, f"{verb}_{code}"):
        raise PermissionDenied
    instance = get_object_or_404(model, pk=pk) if pk is not None else None
    form = form_class(request.POST if request.method == "POST" else None, instance=instance)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except ValidationError as error:
            attach_errors(form, error)
        except IntegrityError:
            form.add_error(None, "تعذر الحفظ. راجع تكرار البيانات.")
        else:
            messages.success(request, "تم حفظ البيانات.")
            return redirect("store:references", kind=kind)
    return render(request, "store/entity_form.html", base_context(
        request, form=form, page_title=title,
        back_url=reverse("store:references", kwargs={"kind": kind}), multipart=False,
        help_text="السجل المرتبط بحركات أو منتجات يمكن إيقافه بدلًا من حذفه.",
    ))


@store_admin_required
@require_http_methods(["GET", "POST"])
def delete_empty(request, kind, pk):
    if kind == "products":
        model, code = Product, "product"
        back_url = reverse("store:catalog")
    else:
        model, _, code, _ = entity_config(kind)
        back_url = reverse("store:references", kwargs={"kind": kind})
    if not has_store_permission(request.user, f"delete_{code}"):
        raise PermissionDenied
    obj = get_object_or_404(model, pk=pk)
    error = ""
    if request.method == "POST":
        if request.POST.get("confirm") != "yes":
            error = "حدد تأكيد الحذف أو ارجع للصفحة السابقة."
        else:
            try:
                with transaction.atomic():
                    obj.delete()
            except (ProtectedError, IntegrityError):
                error = "لا يمكن حذف سجل مرتبط ببيانات. افتح تعديل وألغِ خيار نشط بدلًا من الحذف."
            else:
                messages.success(request, "تم حذف السجل الفارغ.")
                return redirect(back_url)
    return render(request, "store/delete_confirm.html", base_context(
        request, obj=obj, error=error, back_url=back_url,
    ))

@store_admin_required
def expiring_products(request):

    expiry_data = get_expiry_groups()

    return render(
        request,
        "store/expiry_list.html",
        {
            "page_type": "expiring",
            "page_title": "قرب انتهاء الصلاحية",
            "page_icon": "⚠️",
            "batches": expiry_data["expiring"],
            "total_count": expiry_data["expiring_count"],
        },
    )


@store_admin_required
def expired_products(request):

    expiry_data = get_expiry_groups()

    return render(
        request,
        "store/expiry_list.html",
        {
            "page_type": "expired",
            "page_title": "منتجات منتهية الصلاحية",
            "page_icon": "⛔",
            "batches": expiry_data["expired"],
            "total_count": expiry_data["expired_count"],
        },
    )
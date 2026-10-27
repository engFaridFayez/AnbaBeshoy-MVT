"""Read-only stock queries; no writes or notifications during page rendering."""
from decimal import Decimal

from django.db.models import Case, DecimalField, F, Prefetch, Q, Sum, When
from django.utils import timezone

from .models import INCOMING_TYPES, ZERO, Product, StockBatch


def signed_quantity(prefix):
    return Case(
        When(**{f"{prefix}movement_type__in": INCOMING_TYPES},
             then=F(f"{prefix}quantity")),
        default=-F(f"{prefix}quantity"),
        output_field=DecimalField(max_digits=18, decimal_places=3),
    )


def products_with_balances():
    available = (
        Q(is_active=True, category__is_active=True, unit__is_active=True,
          batches__is_blocked=False)
        & (Q(batches__expiry_date__gte=timezone.localdate())
           | Q(requires_expiry_date=False, batches__expiry_date__isnull=True))
    )
    return Product.objects.select_related("category", "unit").annotate(
        ui_total=Sum(signed_quantity("batches__movements__"), default=ZERO),
        ui_available=Sum(signed_quantity("batches__movements__"),
                         filter=available, default=ZERO),
    ).order_by("name", "pk")


def batches_with_balances():
    return StockBatch.objects.select_related("product", "product__unit").annotate(
        ui_balance=Sum(signed_quantity("movements__"), default=ZERO),
        ui_received=Sum("movements__quantity",
                        filter=Q(movements__movement_type="receipt"), default=ZERO),
    ).order_by(F("expiry_date").asc(nulls_last=True), "received_date", "pk")


def expiry_product_ids(product_ids=None):
    """Only positive balances cause expiry warnings, using each product's threshold."""
    batches = batches_with_balances().filter(
        ui_balance__gt=ZERO, expiry_date__isnull=False,
    )
    if product_ids is not None:
        batches = batches.filter(product_id__in=product_ids)
    today = timezone.localdate()
    soon, expired = set(), set()
    for product_id, expiry, warning_days in batches.values_list(
        "product_id", "expiry_date", "product__expiry_warning_days"
    ):
        days = (expiry - today).days
        if days < 0:
            expired.add(product_id)
        elif days <= warning_days:
            soon.add(product_id)
    return soon, expired


def with_display_batches(queryset):
    return queryset.prefetch_related(Prefetch(
        "batches", queryset=batches_with_balances().filter(ui_balance__gt=ZERO),
        to_attr="ui_positive_batches",
    ))


def quantity_text(number):
    value = Decimal(number or 0)
    text = format(value, ".3f").rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def image_url(product):
    if not product.image:
        return ""
    try:
        return product.image.url
    except (ValueError, NotImplementedError):
        return ""


def product_card(product):
    today = timezone.localdate()
    active = bool(product.is_active and product.category.is_active and product.unit.is_active)
    batches = getattr(product, "ui_positive_batches", ())
    soon = []
    expired_count = 0
    for batch in batches:
        if not batch.expiry_date:
            continue
        days = (batch.expiry_date - today).days
        if days < 0:
            expired_count += 1
        elif days <= product.expiry_warning_days:
            soon.append(batch.expiry_date)
    low = active and product.ui_available <= product.minimum_stock
    return {
        "product": product,
        "image_url": image_url(product),
        "active": active,
        "total": quantity_text(product.ui_total),
        "available": quantity_text(product.ui_available),
        "minimum": quantity_text(product.minimum_stock),
        "low": low,
        "expiring": bool(soon),
        "expired_count": expired_count,
        "expiry_date": min(soon) if soon else None,
        "negative": product.ui_total < ZERO or product.ui_available < ZERO,
        "can_issue": active and product.ui_available > ZERO,
    }


def batch_row(batch):
    days = batch.days_to_expiry
    if batch.ui_balance < ZERO:
        state, label = "danger", "رصيد غير صحيح"
    elif batch.ui_balance == ZERO:
        state, label = "muted", "نفدت"
    elif days is not None and days < 0:
        state, label = "danger", "منتهية الصلاحية"
    elif batch.is_blocked:
        state, label = "muted", "موقوفة"
    elif batch.product.requires_expiry_date and not batch.expiry_date:
        state, label = "danger", "تاريخ الصلاحية مطلوب"
    elif days is not None and days <= batch.product.expiry_warning_days:
        state, label = "warning", "قرب انتهاء الصلاحية"
    else:
        state, label = "success", "سارية"
    return {
        "batch": batch, "state": state, "label": label,
        "received": quantity_text(batch.ui_received),
        "remaining": quantity_text(batch.ui_balance), "days": days,
    }

def get_expiry_groups():
    """
    يرجع:
    - الدفعات القريبة من انتهاء الصلاحية.
    - الدفعات المنتهية ولسه فيها رصيد.

    الصلاحية مرتبطة بالدفعة وليس المنتج كله.
    """

    signed_quantity = Case(
        When(
            movements__movement_type__in=INCOMING_TYPES,
            then=F("movements__quantity"),
        ),
        default=-F("movements__quantity"),
        output_field=DecimalField(
            max_digits=18,
            decimal_places=3,
        ),
    )

    batches = (
        StockBatch.objects
        .select_related(
            "product",
            "product__category",
            "product__unit",
        )
        .filter(
            expiry_date__isnull=False,
        )
        .annotate(
            remaining_amount=Sum(
                signed_quantity,
                default=ZERO,
            )
        )
        .filter(
            remaining_amount__gt=ZERO,
        )
        .order_by(
            "expiry_date",
            "product__name",
        )
    )

    today = timezone.localdate()

    expiring = []
    expired = []

    for batch in batches:

        days = (
            batch.expiry_date - today
        ).days

        # نسخة سهلة للاستخدام داخل الـ template
        batch.remaining_for_view = (
            batch.remaining_amount
        )

        if days < 0:

            batch.days_overdue = abs(days)

            expired.append(batch)

        elif days <= batch.product.expiry_warning_days:

            batch.days_remaining = days

            expiring.append(batch)

    return {
        "expiring": expiring,
        "expired": expired,
        "expiring_count": len(expiring),
        "expired_count": len(expired),
    }
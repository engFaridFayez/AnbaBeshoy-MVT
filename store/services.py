"""عمليات المخزون على قاعدة البيانات الافتراضية.

كل عمليات تغيير الرصيد تمر من هنا. يمنع التسجيل المباشر من Admin.
الكتابة في updated_at هي أول استعلام داخل المعاملة للحصول على قفل كتابة
قبل قراءة الرصيد، بما في ذلك SQLite. لا نرسل إشعارات خارجية داخل المعاملة.
"""

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError, connection, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from .models import (
    ZERO,
    STEP,
    MovementType,
    Product,
    StockBatch,
    StockMovement,
    validate_unit_quantity,
)


def can_manage_stock(user):
    """صلاحية عمليات المخزون، وليست مجرد صلاحية المطعم."""
    if (
        not user
        or not user.is_authenticated
        or not user.is_active
        or not user.pk
    ):
        return False

    return bool(
        user.is_superuser
        or getattr(user, "role", "") == "superadmin"
        or (
            getattr(user, "role", "") == "admin"
            and user.has_perm("store.add_stockmovement")
        )
    )


def _check_permission(user):
    if not can_manage_stock(user):
        raise PermissionDenied("ليس لديك صلاحية تسجيل حركات المخزن.")


def _quantity(value, unit):
    """لا نقرب الكسور الزائدة بصمت، ولا نقبل floats أو قيمًا سالبة."""
    if isinstance(value, (float, bool)):
        raise ValidationError("أدخل الكمية كنص أو Decimal، وليس float.")

    try:
        number = Decimal(str(value).strip())
        if not number.is_finite() or number <= ZERO:
            raise InvalidOperation
        if number > Decimal("999999999.999"):
            raise InvalidOperation
        if number != number.quantize(STEP):
            raise ValidationError("الكمية تقبل ثلاث منازل عشرية بحد أقصى.")
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("أدخل كمية موجبة صحيحة ضمن الحد المسموح.")

    validate_unit_quantity(number, unit)
    return number.quantize(STEP)


def _active_product(product):
    if not (
        product.is_active
        and product.category.is_active
        and product.unit.is_active
    ):
        raise ValidationError("المنتج أو القسم أو وحدة القياس موقوف.")


@contextmanager
def _stock_write(product_id):
    """قفل كتابة مشترك لجميع العمليات على المنتج، ثم قراءة رصيد حديث.

    يجب أن تمر جميع كتابات المخزون من هذه الخدمات.
    قفل SQLite يخص قاعدة البيانات، وليس المنتج وحده.
    """
    try:
        with transaction.atomic():
            # لا نقرأ الرصيد قبل هذا الاستعلام.
            updated = Product.objects.filter(pk=product_id).update(
                updated_at=timezone.now()
            )
            if not updated:
                raise ValidationError("المنتج غير موجود.")

            product = Product.objects.select_related(
                "category", "unit"
            ).get(pk=product_id)

            yield product

    except OperationalError as error:
        if connection.vendor == "sqlite" and "locked" in str(error).lower():
            raise ValidationError(
                "المخزن مشغول بعملية أخرى. لم تُحفظ هذه العملية؛ حاول مرة أخرى."
            ) from error
        raise


def receive_stock(
    *,
    product_id,
    quantity,
    user,
    received_date=None,
    production_date=None,
    expiry_date=None,
    source=StockBatch.Source.PURCHASE,
    supplier_name="",
    supplier_batch_number="",
    reference="",
    storage_location="",
    notes="",
):
    """إنشاء دفعة جديدة وحركة الوارد معًا. ترجع الدفعة بعد نجاح الحفظ."""
    _check_permission(user)

    with _stock_write(product_id) as product:
        _active_product(product)
        quantity = _quantity(quantity, product.unit)

        batch = StockBatch(
            product=product,
            received_date=received_date or timezone.localdate(),
            production_date=production_date,
            expiry_date=expiry_date,
            source=source,
            supplier_name=supplier_name,
            supplier_batch_number=supplier_batch_number,
            reference=reference,
            storage_location=storage_location,
            notes=notes,
        )
        batch.full_clean()

        # الوارد الجديد لا يقبل منتجًا منتهيًا.
        # يسمح بجرده كرصيد افتتاحي موقوف، مع توثيق السبب.
        if batch.is_expired:
            if source != StockBatch.Source.OPENING or not notes.strip():
                raise ValidationError(
                    "الدفعة منتهية. لا تُقبل إلا كرصيد افتتاحي موقوف مع سبب واضح."
                )
            batch.is_blocked = True

        batch.save()

        StockMovement.objects.create(
            batch=batch,
            movement_type=MovementType.RECEIPT,
            quantity=quantity,
            performed_by=user,
            reference=reference,
            notes=notes,
        )

        return batch


def issue_stock(
    *,
    product_id,
    quantity,
    user,
    recipient,
    reference="",
    notes="",
):
    """صرف الأقرب انتهاءً أولًا، ثم الأقدم استلامًا، بدون صرف جزئي.

    قد ترجع أكثر من حركة عندما تتوزع الكمية على أكثر من دفعة.
    الدفعات دون تاريخ انتهاء تأتي أخيرًا ولا تُصرف إذا كانت الصلاحية مطلوبة.
    """
    _check_permission(user)

    if not recipient or not recipient.strip():
        raise ValidationError("حدد المستلم أو جهة الصرف.")

    with _stock_write(product_id) as product:
        _active_product(product)
        requested = _quantity(quantity, product.unit)
        today = timezone.localdate()

        batches = StockBatch.objects.filter(
            product=product,
            is_blocked=False,
        )

        if product.requires_expiry_date:
            batches = batches.filter(expiry_date__gte=today)
        else:
            batches = batches.filter(
                Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)
            )

        batches = batches.order_by(
            F("expiry_date").asc(nulls_last=True),
            "received_date",
            "pk",
        )

        remaining = requested
        allocation = []

        for batch in batches:
            batch.product = product
            balance = batch.remaining_quantity
            if balance < ZERO:
                raise ValidationError("رصيد دفعة سالب؛ راجع سجل المخزن أولًا.")
            if balance == ZERO:
                continue

            taken = min(balance, remaining)
            allocation.append((batch, taken))
            remaining -= taken

            if remaining == ZERO:
                break

        if remaining > ZERO:
            raise ValidationError(
                f"الرصيد المتاح لا يكفي. المتاح: "
                f"{requested - remaining} {product.unit.symbol}."
            )

        movements = []
        for batch, taken in allocation:
            movement = StockMovement.objects.create(
                batch=batch,
                movement_type=MovementType.ISSUE,
                quantity=taken,
                performed_by=user,
                recipient=recipient.strip(),
                reference=reference,
                notes=notes,
            )
            movements.append(movement)

        return movements


def record_batch_movement(
    *,
    product_id,
    batch_id,
    movement_type,
    quantity,
    user,
    reason,
    reference="",
):
    """مرتجع / تالف / تسوية على دفعة موجودة، مع تسجيل السبب.

    المرتجع يجب أن يكون صالحًا لإعادة الإتاحة بعد فحصه من المسؤول.
    حد المرتجع محسوب على إجمالي المصروف من الدفعة ناقص ما ارتجع منها،
    وليس تتبعًا لإذن صرف بعينه في هذه المرحلة.
    """
    _check_permission(user)

    allowed_types = {
        MovementType.RETURN,
        MovementType.WASTE,
        MovementType.ADJUST_IN,
        MovementType.ADJUST_OUT,
    }
    if movement_type not in allowed_types:
        raise ValidationError("استخدم خدمة الوارد أو الصرف لنوع الحركة المطلوب.")

    if not reason or not reason.strip():
        raise ValidationError("اكتب سبب المرتجع أو التالف أو التسوية.")

    with _stock_write(product_id) as product:
        quantity = _quantity(quantity, product.unit)

        try:
            batch = StockBatch.objects.get(
                pk=batch_id,
                product=product,
            )
        except StockBatch.DoesNotExist:
            raise ValidationError("الدفعة غير موجودة أو لا تخص المنتج.")

        batch.product = product

        if movement_type == MovementType.RETURN:
            _active_product(product)

            if batch.is_blocked or batch.is_expired:
                raise ValidationError(
                    "لا تُعِد إتاحة مرتجع لدفعة موقوفة أو منتهية."
                )
            if product.requires_expiry_date and not batch.expiry_date:
                raise ValidationError("الدفعة تحتاج تاريخ صلاحية قبل المرتجع.")

            issued = batch.movements.filter(
                movement_type=MovementType.ISSUE
            ).aggregate(total=Sum("quantity", default=ZERO))["total"]

            returned = batch.movements.filter(
                movement_type=MovementType.RETURN
            ).aggregate(total=Sum("quantity", default=ZERO))["total"]

            if quantity > (issued - returned).quantize(STEP):
                raise ValidationError(
                    "المرتجع أكبر من إجمالي المصروف المتبقي دون إرجاع."
                )

        return StockMovement.objects.create(
            batch=batch,
            movement_type=movement_type,
            quantity=quantity,
            performed_by=user,
            reference=reference,
            notes=reason.strip(),
        )

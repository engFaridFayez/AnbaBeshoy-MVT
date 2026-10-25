"""Store schema, phase 1. Post stock movements only through a transactional service."""

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Case, F, Q, Sum, When
from django.utils import timezone


ZERO = Decimal("0.000")
STEP = Decimal("0.001")


class MovementType(models.TextChoices):
    RECEIPT = "receipt", "وارد"
    ISSUE = "issue", "صرف"
    RETURN = "return", "مرتجع إلى المخزن"
    WASTE = "waste", "تالف"
    ADJUST_IN = "adjust_in", "تسوية زيادة"
    ADJUST_OUT = "adjust_out", "تسوية عجز"


INCOMING_TYPES = (
    MovementType.RECEIPT,
    MovementType.RETURN,
    MovementType.ADJUST_IN,
)


def new_product_code():
    return f"PRD-{uuid4().hex.upper()}"


def movement_balance(queryset):
    signed_quantity = Case(
        When(
            movement_type__in=INCOMING_TYPES,
            then=F("quantity"),
        ),
        default=-F("quantity"),
        output_field=models.DecimalField(
            max_digits=18,
            decimal_places=3,
        ),
    )

    total = queryset.aggregate(
        total=Sum(signed_quantity, default=ZERO)
    )["total"]

    return total.quantize(STEP)


def validate_unit_quantity(quantity, unit):
    try:
        number = Decimal(quantity)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("أدخل كمية صحيحة.")

    if not number.is_finite():
        raise ValidationError("أدخل كمية صحيحة.")

    if (
        not unit.allow_fractions
        and number != number.to_integral_value()
    ):
        raise ValidationError(
            "وحدة القياس هذه لا تقبل كسورًا."
        )


class ValidatedModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


# ==================================================
# 1. Categories
# ==================================================

class Category(ValidatedModel):
    name = models.CharField(
        "اسم القسم",
        max_length=120,
        unique=True,
    )

    description = models.TextField(
        "الوصف",
        blank=True,
    )

    is_active = models.BooleanField(
        "نشط",
        default=True,
    )

    sort_order = models.PositiveSmallIntegerField(
        "ترتيب العرض",
        default=0,
    )

    class Meta:
        verbose_name = "قسم مخزن"
        verbose_name_plural = "أقسام المخزن"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


# ==================================================
# 2. Units
# ==================================================

class UnitOfMeasure(ValidatedModel):
    name = models.CharField(
        "اسم الوحدة",
        max_length=50,
        unique=True,
    )

    symbol = models.CharField(
        "رمز الوحدة",
        max_length=20,
        unique=True,
    )

    allow_fractions = models.BooleanField(
        "تقبل كسورًا",
        default=False,
    )

    is_active = models.BooleanField(
        "نشطة",
        default=True,
    )

    class Meta:
        verbose_name = "وحدة قياس"
        verbose_name_plural = "وحدات القياس"
        ordering = ["name"]

    def clean(self):
        super().clean()

        if (
            self.pk
            and self.products.filter(
                batches__isnull=False
            ).exists()
        ):
            old = type(self).objects.get(pk=self.pk)

            if (
                old.name,
                old.symbol,
                old.allow_fractions,
            ) != (
                self.name,
                self.symbol,
                self.allow_fractions,
            ):
                raise ValidationError(
                    "لا يمكن تغيير تعريف وحدة لها دفعات مسجلة. "
                    "أضف وحدة جديدة."
                )

    def __str__(self):
        return self.name


# ==================================================
# 3. Products
# ==================================================

class Product(ValidatedModel):
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="القسم",
    )

    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="وحدة القياس",
    )

    name = models.CharField(
        "اسم المنتج",
        max_length=160,
    )

    code = models.CharField(
        "الكود الداخلي",
        max_length=40,
        unique=True,
        default=new_product_code,
        editable=False,
    )

    barcode = models.CharField(
        "الباركود",
        max_length=100,
        unique=True,
        blank=True,
        null=True,
    )

    image = models.ImageField(
        "الصورة",
        upload_to="store/products/",
        blank=True,
    )

    description = models.TextField(
        "الوصف",
        blank=True,
    )

    minimum_stock = models.DecimalField(
        "الحد الأدنى",
        max_digits=12,
        decimal_places=3,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )

    requires_expiry_date = models.BooleanField(
        "يلزم تاريخ صلاحية",
        default=True,
    )

    expiry_warning_days = models.PositiveSmallIntegerField(
        "التنبيه قبل الانتهاء بأيام",
        default=7,
    )

    is_active = models.BooleanField(
        "نشط",
        default=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "منتج"
        verbose_name_plural = "منتجات المخزن"
        ordering = ["name", "pk"]

        constraints = [
            models.UniqueConstraint(
                fields=["category", "name"],
                name="store_product_name_unique",
            ),
            models.CheckConstraint(
                condition=Q(minimum_stock__gte=0),
                name="store_minimum_nonnegative",
            ),
        ]

    def clean(self):
        super().clean()

        # السماح بمنتجات متعددة بدون باركود.
        self.barcode = (self.barcode or "").strip() or None

        if self.unit_id:
            try:
                validate_unit_quantity(
                    self.minimum_stock,
                    self.unit,
                )
            except ValidationError as error:
                raise ValidationError({
                    "minimum_stock": error.messages,
                })

        # لا نغير وحدة منتج بعد تسجيل دفعات له.
        if self.pk and self.batches.exists():
            old_unit_id = (
                type(self).objects
                .values_list("unit_id", flat=True)
                .get(pk=self.pk)
            )

            if old_unit_id != self.unit_id:
                raise ValidationError({
                    "unit": "لا تغير وحدة منتج له دفعات مسجلة.",
                })

    @property
    def current_stock(self):
        """الرصيد الموجود، بما فيه الدفعات الموقوفة والمنتهية."""
        if not self.pk:
            return ZERO

        return movement_balance(
            StockMovement.objects.filter(
                batch__product=self,
            )
        )

    @property
    def available_stock(self):
        """الرصيد المتاح وفق حالة المنتج والدفعات وتواريخها."""
        if (
            not self.pk
            or not self.is_active
            or not self.category.is_active
            or not self.unit.is_active
        ):
            return ZERO

        movements = StockMovement.objects.filter(
            batch__product=self,
            batch__is_blocked=False,
        )

        if self.requires_expiry_date:
            movements = movements.filter(
                batch__expiry_date__gte=timezone.localdate(),
            )
        else:
            movements = movements.filter(
                Q(batch__expiry_date__isnull=True)
                | Q(
                    batch__expiry_date__gte=timezone.localdate()
                )
            )

        return movement_balance(movements)

    @property
    def is_low_stock(self):
        return (
            self.is_active
            and self.category.is_active
            and self.unit.is_active
            and self.available_stock <= self.minimum_stock
        )

    def __str__(self):
        return self.name


# ==================================================
# 4. Supply batches
# ==================================================

class StockBatch(ValidatedModel):
    class Source(models.TextChoices):
        PURCHASE = "purchase", "شراء"
        DONATION = "donation", "تبرع"
        OPENING = "opening", "رصيد افتتاحي"

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="batches",
        verbose_name="المنتج",
    )

    code = models.UUIDField(
        "رقم الدفعة الداخلي",
        default=uuid4,
        unique=True,
        editable=False,
    )

    supplier_batch_number = models.CharField(
        "رقم التشغيلة",
        max_length=100,
        blank=True,
    )

    received_date = models.DateField(
        "تاريخ الاستلام",
        default=timezone.localdate,
    )

    production_date = models.DateField(
        "تاريخ الإنتاج",
        null=True,
        blank=True,
    )

    expiry_date = models.DateField(
        "تاريخ الانتهاء",
        null=True,
        blank=True,
    )

    source = models.CharField(
        "نوع الوارد",
        max_length=12,
        choices=Source.choices,
        default=Source.PURCHASE,
    )

    supplier_name = models.CharField(
        "المورد / جهة التبرع",
        max_length=160,
        blank=True,
    )

    reference = models.CharField(
        "مرجع الاستلام",
        max_length=100,
        blank=True,
    )

    storage_location = models.CharField(
        "مكان التخزين",
        max_length=120,
        blank=True,
    )

    is_blocked = models.BooleanField(
        "موقوفة عن الصرف",
        default=False,
    )

    notes = models.TextField(
        "ملاحظات",
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "دفعة توريد"
        verbose_name_plural = "دفعات التوريد"
        ordering = ["-received_date", "-pk"]

        indexes = [
            models.Index(
                fields=["product", "expiry_date"],
                name="store_batch_expiry_idx",
            ),
        ]

        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(production_date__isnull=True)
                    | Q(expiry_date__isnull=True)
                    | Q(
                        expiry_date__gte=F("production_date")
                    )
                ),
                name="store_batch_dates_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(production_date__isnull=True)
                    | Q(
                        production_date__lte=F("received_date")
                    )
                ),
                name="store_produced_before_receipt",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.product_id
            and self.product.requires_expiry_date
            and not self.expiry_date
        ):
            errors["expiry_date"] = (
                "تاريخ الانتهاء مطلوب لهذا المنتج."
            )

        if (
            isinstance(self.received_date, date)
            and self.received_date > timezone.localdate()
        ):
            errors["received_date"] = (
                "لا تسجل استلامًا فعليًا بتاريخ مستقبلي."
            )

        if self.pk and self.movements.exists():
            original = (
                type(self).objects
                .values_list("product_id", flat=True)
                .get(pk=self.pk)
            )

            if original != self.product_id:
                errors["product"] = (
                    "لا يمكن نقل دفعة لها حركات إلى منتج آخر."
                )

        if errors:
            raise ValidationError(errors)

    @property
    def received_quantity(self):
        """الكمية المسجلة في حركة الوارد الأصلية."""
        if not self.pk:
            return ZERO

        return movement_balance(
            self.movements.filter(
                movement_type=MovementType.RECEIPT,
            )
        )

    @property
    def remaining_quantity(self):
        if not self.pk:
            return ZERO

        return movement_balance(self.movements.all())

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return None

        return (
            self.expiry_date - timezone.localdate()
        ).days

    @property
    def is_expired(self):
        days = self.days_to_expiry
        return days is not None and days < 0

    @property
    def is_expiring_soon(self):
        days = self.days_to_expiry

        return (
            days is not None
            and 0 <= days <= self.product.expiry_warning_days
            and self.remaining_quantity > ZERO
        )

    def __str__(self):
        return (
            f"{self.product.name} - "
            f"{str(self.code)[:8]}"
        )


# ==================================================
# 5. Stock movements
# ==================================================

class LedgerQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError(
            "لا تعدل حركة مسجلة. استخدم تسوية موثقة."
        )

    def delete(self):
        raise ValidationError(
            "لا تحذف حركة مسجلة. استخدم تسوية موثقة."
        )

    def bulk_create(self, *args, **kwargs):
        raise ValidationError(
            "سجل الحركات من خلال خدمة الوارد والصرف."
        )

    def bulk_update(self, *args, **kwargs):
        raise ValidationError(
            "لا تعدل حركة مسجلة. استخدم تسوية موثقة."
        )


class StockMovement(ValidatedModel):
    objects = LedgerQuerySet.as_manager()

    batch = models.ForeignKey(
        StockBatch,
        on_delete=models.PROTECT,
        related_name="movements",
        verbose_name="الدفعة",
    )

    movement_type = models.CharField(
        "نوع الحركة",
        max_length=12,
        choices=MovementType.choices,
    )

    quantity = models.DecimalField(
        "الكمية",
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(STEP)],
    )

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="store_movements",
        verbose_name="مسجل الحركة",
    )

    recipient = models.CharField(
        "المستلم / جهة الصرف",
        max_length=160,
        blank=True,
    )

    reference = models.CharField(
        "رقم إذن أو مرجع",
        max_length=100,
        blank=True,
    )

    notes = models.TextField(
        "السبب / ملاحظات",
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "حركة مخزن"
        verbose_name_plural = "حركات المخزن"
        ordering = ["-created_at", "-pk"]

        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="store_movement_qty_positive",
            ),
            models.CheckConstraint(
                condition=Q(
                    movement_type__in=MovementType.values
                ),
                name="store_movement_type_valid",
            ),
            models.UniqueConstraint(
                fields=["batch"],
                condition=Q(
                    movement_type=MovementType.RECEIPT
                ),
                name="store_one_receipt_per_batch",
            ),
        ]

    def clean(self):
        super().clean()

        if not self._state.adding:
            raise ValidationError(
                "الحركة المسجلة لا تُعدّل. "
                "سجّل تسوية موثقة بدلًا من ذلك."
            )

        if self.batch_id:
            batch = self.batch
            product = batch.product

            try:
                validate_unit_quantity(
                    self.quantity,
                    product.unit,
                )
            except ValidationError as error:
                raise ValidationError({
                    "quantity": error.messages,
                })

            if self.movement_type != MovementType.RECEIPT:
                has_receipt = batch.movements.filter(
                    movement_type=MovementType.RECEIPT,
                ).exists()

                if not has_receipt:
                    raise ValidationError(
                        "سجل الوارد الأصلي للدفعة أولًا."
                    )

            # فحص أولي للرصيد.
            # حماية العمليات المتزامنة تُنفذ في services.py.
            if self.movement_type in (
                MovementType.ISSUE,
                MovementType.WASTE,
                MovementType.ADJUST_OUT,
            ):
                if Decimal(self.quantity) > batch.remaining_quantity:
                    raise ValidationError({
                        "quantity": "الكمية أكبر من رصيد الدفعة.",
                    })

            if self.movement_type == MovementType.ISSUE:
                if not (
                    product.is_active
                    and product.category.is_active
                    and product.unit.is_active
                ):
                    raise ValidationError(
                        "المنتج أو القسم أو الوحدة غير نشط."
                    )

                if batch.is_blocked or batch.is_expired:
                    raise ValidationError(
                        "الدفعة موقوفة أو منتهية الصلاحية."
                    )

                if (
                    product.requires_expiry_date
                    and not batch.expiry_date
                ):
                    raise ValidationError(
                        "تاريخ الصلاحية مطلوب لهذا المنتج."
                    )

        if (
            self.movement_type == MovementType.ISSUE
            and not self.recipient.strip()
        ):
            raise ValidationError({
                "recipient": "حدد المستلم أو جهة الصرف.",
            })

        if self.movement_type in (
            MovementType.WASTE,
            MovementType.ADJUST_IN,
            MovementType.ADJUST_OUT,
        ):
            if not self.notes.strip():
                raise ValidationError({
                    "notes": "اكتب سبب التالف أو التسوية.",
                })

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "لا تحذف حركة مخزن. استخدم تسوية موثقة."
        )

    def __str__(self):
        return (
            f"{self.get_movement_type_display()} - "
            f"{self.batch.product.name} - "
            f"{self.quantity}"
        )


# ==================================================
# 6. Stock alerts
# ==================================================

class AlertType(models.TextChoices):
    LOW_STOCK = "low_stock", "مخزون منخفض"
    EXPIRING = "expiring", "قرب انتهاء الصلاحية"
    EXPIRED = "expired", "منتهي الصلاحية"


class StockAlert(ValidatedModel):
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="stock_alerts",
    )

    batch = models.ForeignKey(
        StockBatch,
        on_delete=models.PROTECT,
        related_name="stock_alerts",
        null=True,
        blank=True,
    )

    alert_type = models.CharField(
        "نوع التنبيه",
        max_length=12,
        choices=AlertType.choices,
    )

    message = models.TextField(
        "تفاصيل التنبيه",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    resolved_at = models.DateTimeField(
        "وقت انتهاء الحالة",
        null=True,
        blank=True,
    )

    last_notified_at = models.DateTimeField(
        "آخر إشعار",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "تنبيه مخزن"
        verbose_name_plural = "تنبيهات المخزن"
        ordering = ["-created_at", "-pk"]

        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        alert_type=AlertType.LOW_STOCK,
                        batch__isnull=True,
                    )
                    | Q(
                        alert_type__in=[
                            AlertType.EXPIRING,
                            AlertType.EXPIRED,
                        ],
                        batch__isnull=False,
                    )
                ),
                name="store_alert_scope_valid",
            ),
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(
                    alert_type=AlertType.LOW_STOCK,
                    resolved_at__isnull=True,
                ),
                name="store_one_open_low_alert",
            ),
            models.UniqueConstraint(
                fields=["batch"],
                condition=Q(
                    alert_type__in=[
                        AlertType.EXPIRING,
                        AlertType.EXPIRED,
                    ],
                    resolved_at__isnull=True,
                ),
                name="store_one_open_expiry_alert",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.batch_id
            and self.product_id != self.batch.product_id
        ):
            raise ValidationError({
                "batch": "الدفعة لا تخص المنتج المحدد.",
            })

    @property
    def is_open(self):
        return self.resolved_at is None

    def __str__(self):
        return (
            f"{self.get_alert_type_display()} - "
            f"{self.product.name}"
        )
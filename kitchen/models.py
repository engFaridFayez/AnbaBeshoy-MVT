from django.db import models
from django.core.validators import MinValueValidator
from api import settings
from django.core.exceptions import ValidationError
# Create your models here.

class MealType(models.TextChoices):
    BREAKFAST = "breakfast", "فطار"
    LUNCH = "lunch", "غداء"
    DINNER = "dinner", "عشاء"


class ItemCategory(models.TextChoices):
    FOOD = "food", "أكل"
    DRINKS = "drinks", "مشروبات"
    DESSERT = "dessert", "حلو"

class MenuItem(models.Model):
    name = models.CharField(max_length=255,verbose_name="اسم الصنف")
    category = models.CharField(max_length=20, choices=ItemCategory.choices, verbose_name="نوع الصنف")
    icon = models.ImageField(upload_to='menu_icons/', blank=True, null=True, verbose_name="أيقونة الصنف")
    is_active = models.BooleanField(
        default=True,
        verbose_name="صنف نشط",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["category", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "category"],
                name="unique_menu_item_name_category",
            )
        ]

    def __str__(self):
        return self.name

class DailyMenu(models.Model):

    date = models.DateField(
        verbose_name="التاريخ",
    )

    meal_type = models.CharField(
        max_length=10,
        choices=MealType.choices,
        verbose_name="الوجبة",
    )

    is_published = models.BooleanField(
        default=False,
        verbose_name="القائمة منشورة",
    )

    ordering_deadline = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="آخر موعد للطلب",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "meal_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["date", "meal_type"],
                name="unique_daily_meal",
            )
        ]

    def __str__(self):
        return f"{self.get_meal_type_display()} - {self.date}"


class DailyMenuItem(models.Model):

    daily_menu = models.ForeignKey(
        DailyMenu,
        on_delete=models.CASCADE,
        related_name="entries",
    )

    item = models.ForeignKey(
        MenuItem,
        on_delete=models.PROTECT,
        related_name="daily_entries",
    )

    is_available = models.BooleanField(
        default=True,
        verbose_name="متاح للطلب",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["daily_menu", "item"],
                name="unique_item_per_daily_menu",
            )
        ]

    def __str__(self):
        return f"{self.item.name} - {self.daily_menu}"


class Order(models.Model):

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "تم الإرسال"
        CANCELLED = "cancelled", "ملغي"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )

    daily_menu = models.ForeignKey(
        DailyMenu,
        on_delete=models.PROTECT,
        related_name="orders",
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.SUBMITTED,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "daily_menu"],
                name="unique_user_daily_meal_order",
            )
        ]

    def __str__(self):
        return (
            f"طلب {self.user} - "
            f"{self.daily_menu}"
        )

class OrderItem(models.Model):

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )

    daily_menu_item = models.ForeignKey(
        DailyMenuItem,
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    quantity = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="الكمية",
    )

    item_name_snapshot = models.CharField(
        max_length=120,
        verbose_name="اسم الصنف وقت الطلب",
    )

    category_snapshot = models.CharField(
        max_length=10,
        choices=ItemCategory.choices,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order", "daily_menu_item"],
                name="unique_item_per_order",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="order_item_positive_quantity",
            ),
        ]

    def clean(self):
        super().clean()

        if self.order_id and self.daily_menu_item_id:
            if (
                self.order.daily_menu_id
                != self.daily_menu_item.daily_menu_id
            ):
                raise ValidationError({
                    "daily_menu_item":
                    "الصنف لا ينتمي لقائمة الوجبة المحددة."
                })

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.item_name_snapshot = (
                self.daily_menu_item.item.name
            )
            self.category_snapshot = (
                self.daily_menu_item.item.category
            )

        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.item_name_snapshot} "
            f"× {self.quantity}"
        )
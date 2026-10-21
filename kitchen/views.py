
from datetime import date
from urllib.parse import urlencode
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.db import transaction
from django.db.models import Count, Sum, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
)
from django import forms
from accounts.models import User

from .models import (
    DailyMenu,
    DailyMenuItem,
    MenuItem,
    MealType,
    ItemCategory,
    Order,
    OrderItem,
)


MAX_QUANTITY = 99

MEAL_TYPES = {
    "breakfast": "فطار",
    "lunch": "غداء",
    "dinner": "عشاء",
}


def ordering_is_open(menu):
    if menu is None:
        return False

    if not menu.is_published:
        return False

    if menu.ordering_deadline:
        if timezone.now() >= menu.ordering_deadline:
            return False

    return True


@login_required
@require_http_methods(["GET", "POST"])
def menu_view(request):

    today = timezone.localdate()

    meal_type = request.GET.get("meal", "breakfast")

    if request.method == "POST":
        meal_type = request.POST.get(
            "meal_type", "breakfast"
        )

    if meal_type not in MEAL_TYPES:
        raise Http404("الوجبة غير موجودة.")

    # Get today's menu
    daily_menu = DailyMenu.objects.filter(
        date=today,
        meal_type=meal_type,
    ).first()

    # Fetch existing order
    existing_order = None

    if daily_menu:
        existing_order = (
            Order.objects
            .filter(
                user=request.user,
                daily_menu=daily_menu,
            )
            .first()
        )

    # Available items
    available_items = []

    if daily_menu:
        available_items = list(
            DailyMenuItem.objects
            .filter(
                daily_menu=daily_menu,
                is_available=True,
                item__is_active=True,
            )
            .select_related("item")
            .order_by(
                "item__category",
                "item__name",
            )
        )

    # ======================================
    # Submit / Update Order
    # ======================================

    if request.method == "POST":

        if not ordering_is_open(daily_menu):
            messages.error(
                request,
                "الطلب غير متاح لهذه الوجبة حاليًا."
            )
            return redirect(
                f"/kitchen/?meal={meal_type}"
            )

        if (
            existing_order
            and existing_order.status
            == Order.Status.CANCELLED
        ):
            messages.error(
                request,
                "الطلب ملغي. تواصل مع المسؤول."
            )
            return redirect(
                f"/kitchen/?meal={meal_type}"
            )

        selected_items = []
        has_error = False

        for entry in available_items:

            field_name = f"quantity_{entry.id}"

            raw_quantity = request.POST.get(
                field_name, "0"
            )

            try:
                quantity = int(raw_quantity)
            except (ValueError, TypeError):
                has_error = True
                break

            if (
                quantity < 0
                or quantity > MAX_QUANTITY
            ):
                has_error = True
                break

            if quantity > 0:
                selected_items.append(
                    (entry, quantity)
                )

        if has_error:
            messages.error(
                request,
                "تأكد من صحة الكميات المدخلة."
            )
            return redirect(
                f"/kitchen/?meal={meal_type}"
            )

        if not selected_items:
            messages.error(
                request,
                "اختار صنف واحد على الأقل."
            )
            return redirect(
                f"/kitchen/?meal={meal_type}"
            )

        # Save order and items together
        with transaction.atomic():

            order, created = (
                Order.objects.get_or_create(
                    user=request.user,
                    daily_menu=daily_menu,
                    defaults={
                        "status": Order.Status.SUBMITTED,
                    },
                )
            )

            if order.status == Order.Status.CANCELLED:
                messages.error(
                    request,
                    "الطلب ملغي. تواصل مع المسؤول."
                )
                return redirect(
                    f"/kitchen/?meal={meal_type}"
                )

            # Replace previous selections
            order.items.all().delete()

            for entry, quantity in selected_items:

                OrderItem.objects.create(
                    order=order,
                    daily_menu_item=entry,
                    quantity=quantity,
                )

        messages.success(
            request,
            "تم حفظ طلبك بنجاح."
        )

        return redirect(
            f"/kitchen/?meal={meal_type}"
        )

    # ======================================
    # Prepare existing quantities
    # ======================================

    selected_quantities = {}

    if existing_order:

        for order_item in existing_order.items.all():
            selected_quantities[
                order_item.daily_menu_item_id
            ] = order_item.quantity

    for entry in available_items:
        entry.selected_quantity = (
            selected_quantities.get(entry.id, 0)
        )

    can_order = ordering_is_open(daily_menu)

    if (
        existing_order
        and existing_order.status
        == Order.Status.CANCELLED
    ):
        can_order = False

    context = {
        "today": today,
        "meal_type": meal_type,
        "meal_types": MEAL_TYPES,
        "meal_name": MEAL_TYPES[meal_type],
        "daily_menu": daily_menu,
        "available_items": available_items,
        "existing_order": existing_order,
        "can_order": can_order,
        "max_quantity": MAX_QUANTITY,
    }

    return render(
        request,
        "kitchen/menu.html",
        context,
    )




# ==========================================
# RESTAURANT ADMIN DASHBOARD
# ==========================================


@login_required
@require_GET
def restaurant_dashboard(request):

    # ======================================
    # 1. Permission Check
    # ======================================

    allowed_roles = [
        User.Role.ADMIN,
        User.Role.SUPERADMIN,
    ]

    if request.user.role not in allowed_roles:
        raise PermissionDenied(
            "ليس لديك صلاحية الدخول للوحة المطعم."
        )

    # ======================================
    # 2. Report Filters
    # ======================================

    valid_meals = [
        "all",
        MealType.BREAKFAST,
        MealType.LUNCH,
        MealType.DINNER,
    ]

    # --------------------------------------
    # Selected Meal - Session
    # --------------------------------------

    requested_meal = request.GET.get("meal")

    if requested_meal is not None:

        if requested_meal in valid_meals:
            selected_meal = requested_meal
        else:
            selected_meal = "all"

        # Save selected meal
        request.session["report_meal"] = selected_meal

    else:

        # Restore previous selection
        selected_meal = request.session.get(
            "report_meal",
            "all",
        )

        if selected_meal not in valid_meals:
            selected_meal = "all"

    # --------------------------------------
    # Selected Date - Session
    # --------------------------------------

    requested_date = request.GET.get("date")

    if requested_date is not None:

        try:
            selected_date = date.fromisoformat(
                requested_date
            )

        except (ValueError, TypeError):
            selected_date = timezone.localdate()

        # Save selected date
        request.session["report_date"] = (
            selected_date.isoformat()
        )

    else:

        saved_date = request.session.get(
            "report_date"
        )

        try:
            selected_date = date.fromisoformat(
                saved_date
            )

        except (ValueError, TypeError):
            selected_date = timezone.localdate()

    # ======================================
    # 3. Daily Menus
    # ======================================

    daily_menus = (
        DailyMenu.objects
        .filter(
            date=selected_date
        )
        .annotate(
            available_count=Count(
                "entries",
                filter=Q(
                    entries__is_available=True,
                    entries__item__is_active=True,
                ),
                distinct=True,
            )
        )
        .order_by("meal_type")
    )

    # ======================================
    # 4. Orders Queryset
    # ======================================

    orders = Order.objects.filter(
        daily_menu__date=selected_date,
        status=Order.Status.SUBMITTED,
    )

    # Filter by meal
    if selected_meal != "all":

        orders = orders.filter(
            daily_menu__meal_type=selected_meal
        )

    # ======================================
    # 5. Summary Statistics
    # ======================================

    # Total number of orders
    total_orders = orders.count()

    # Total unique monks
    total_monks = (
        orders
        .values("user_id")
        .distinct()
        .count()
    )

    # ======================================
    # 6. Order Items Queryset
    # ======================================

    order_items = OrderItem.objects.filter(
        order__daily_menu__date=selected_date,
        order__status=Order.Status.SUBMITTED,
    )

    if selected_meal != "all":

        order_items = order_items.filter(
            order__daily_menu__meal_type=selected_meal
        )

    # Total quantity
    total_quantity = (
        order_items.aggregate(
            total=Sum("quantity")
        )["total"] or 0
    )

    # ======================================
    # 7. Grouped Kitchen Totals
    # ======================================

    totals_query = (
        order_items
        .values(
            "order__daily_menu__meal_type",
            "category_snapshot",
            "item_name_snapshot",
        )
        .annotate(
            total_quantity=Sum("quantity")
        )
        .order_by(
            "order__daily_menu__meal_type",
            "category_snapshot",
            "item_name_snapshot",
        )
    )

    kitchen_totals = []

    for row in totals_query:

        meal_type = row[
            "order__daily_menu__meal_type"
        ]

        category = row[
            "category_snapshot"
        ]

        kitchen_totals.append({
            "meal": MealType(meal_type).label,
            "category": ItemCategory(category).label,
            "item": row["item_name_snapshot"],
            "quantity": row["total_quantity"],
        })

    # ======================================
    # 8. Group Orders By Monk
    # ======================================

    # Fetch orders with related data
    detailed_query = (
        orders
        .select_related(
            "user",
            "daily_menu",
        )
        .prefetch_related("items")
        .order_by(
            "user__display_name",
            "user__username",
            "daily_menu__meal_type",
        )
    )

    grouped_orders = {}

    for order in detailed_query:

        user_id = order.user_id

        # Create one row for each monk
        if user_id not in grouped_orders:

            grouped_orders[user_id] = {
                "monk": (
                    order.user.display_name
                    or order.user.username
                ),
                "meals": [],
            }

        # Collect items for this meal
        meal_items = []

        for item in order.items.all():

            meal_items.append({
                "name": item.item_name_snapshot,
                "quantity": item.quantity,
            })

        # Add meal and its items
        if meal_items:

            grouped_orders[user_id]["meals"].append({
                "name": (
                    order.daily_menu
                    .get_meal_type_display()
                ),
                "items": meal_items,
            })

    # Convert dictionary to list
    detailed_orders = list(
        grouped_orders.values()
    )

    # ======================================
    # 9. Template Context
    # ======================================

    context = {

        # Filters
        "selected_date": selected_date,
        "selected_meal": selected_meal,

        # Daily menus
        "daily_menus": daily_menus,

        # Statistics
        "total_orders": total_orders,
        "total_monks": total_monks,
        "total_quantity": total_quantity,

        # Reports
        "kitchen_totals": kitchen_totals,
        "detailed_orders": detailed_orders,

        # Permissions
        "is_superadmin": (
            request.user.role
            == User.Role.SUPERADMIN
        ),
    }

    # ======================================
    # 10. Render Dashboard
    # ======================================

    return render(
        request,
        "kitchen/dashboard.html",
        context,
    )


# ==========================================
# DAILY MENU MANAGEMENT
# ==========================================

@login_required
@require_http_methods(["GET", "POST"])
def manage_daily_menu(request):
    if request.user.role not in (
        User.Role.ADMIN,
        User.Role.SUPERADMIN,
    ):
        raise PermissionDenied(
            "ليس لديك صلاحية إدارة وجبات المطعم."
        )

    params = (
        request.POST
        if request.method == "POST"
        else request.GET
    )

    raw_date = params.get("date")

    try:
        selected_date = (
            date.fromisoformat(raw_date)
            if raw_date
            else timezone.localdate()
        )
    except ValueError:
        messages.error(request, "التاريخ غير صحيح.")
        return redirect("kitchen:manage_menu")

    selected_meal = params.get(
        "meal",
        MealType.BREAKFAST,
    )

    if selected_meal not in MealType.values:
        raise Http404("الوجبة غير موجودة.")

    meal_name = dict(MealType.choices)[selected_meal]

    page_url = (
        reverse("kitchen:manage_menu")
        + "?"
        + urlencode({
            "date": selected_date.isoformat(),
            "meal": selected_meal,
        })
    )

    def back(message, level=messages.SUCCESS):
        messages.add_message(request, level, message)
        return redirect(page_url)

    if request.method == "POST":
        action = request.POST.get("action")

        allowed_actions = {
            "save_meal",
            "add_item",
            "publish",
            "unpublish",
        }

        if action not in allowed_actions:
            return back(
                "العملية غير صحيحة. حدّث الصفحة وحاول مرة أخرى.",
                messages.ERROR,
            )

        # التحقق من الأصناف قبل إجراء أي تعديل.
        if action == "save_meal":
            try:
                selected_ids = {
                    int(value)
                    for value in request.POST.getlist("item_ids")
                }

                if any(
                    item_id < 1 or item_id > 9223372036854775807
                    for item_id in selected_ids
                ):
                    raise ValueError

            except (TypeError, ValueError):
                return back(
                    "بيانات الأصناف غير صحيحة.",
                    messages.ERROR,
                )

            allowed_ids = set(
                MenuItem.objects.filter(
                    pk__in=selected_ids,
                    is_active=True,
                ).values_list("pk", flat=True)
            )

            if selected_ids != allowed_ids:
                return back(
                    "أحد الأصناف لم يعد متاحًا. حدّث الصفحة.",
                    messages.ERROR,
                )

        # التحقق من بيانات الصنف الجديد.
        elif action == "add_item":
            item_name = " ".join(
                request.POST.get("new_item_name", "").split()
            )

            category = request.POST.get(
                "category",
                ItemCategory.FOOD,
            )

            max_name_length = (
                MenuItem._meta.get_field("name").max_length
            )

            if (
                not item_name
                or len(item_name) > max_name_length
                or category not in ItemCategory.values
            ):
                return back(
                    "أدخل اسم صنف صحيحًا واختر القسم المناسب.",
                    messages.ERROR,
                )

        with transaction.atomic():
            daily_menu, _ = DailyMenu.objects.get_or_create(
                date=selected_date,
                meal_type=selected_meal,
            )

            if action == "save_meal":
                # إلغاء إتاحة الأصناف غير المختارة.
                # لا نحذف السجلات المرتبطة بالطلبات السابقة.
                daily_menu.entries.exclude(
                    item_id__in=selected_ids,
                ).update(
                    is_available=False,
                )

                # إتاحة الأصناف المختارة في هذه الوجبة فقط.
                for item_id in sorted(selected_ids):
                    DailyMenuItem.objects.update_or_create(
                        daily_menu=daily_menu,
                        item_id=item_id,
                        defaults={
                            "is_available": True,
                        },
                    )

                # القائمة الخالية لا تظل مفتوحة للطلبات.
                if not selected_ids:
                    daily_menu.is_published = False
                    daily_menu.save(
                        update_fields=["is_published"],
                    )

                    result_message = (
                        f"تم حفظ قائمة {meal_name} بدون أصناف "
                        "وإغلاق الطلبات."
                    )
                else:
                    result_message = (
                        f"تم حفظ أصناف {meal_name} بنجاح."
                    )

            elif action == "add_item":
                uploaded_icon = request.FILES.get("icon")

                # حد اخترناه للمشروع: 5 ميجابايت للصورة.
                if uploaded_icon and uploaded_icon.size > 5 * 1024 * 1024:
                    return back(
                        "حجم الصورة أكبر من المسموح. الحد الأقصى 5 ميجابايت.",
                        messages.ERROR,
                    )

                # التحقق من أن الملف المرفوع صورة قابلة للقراءة.
                try:
                    uploaded_icon = forms.ImageField(
                        required=False,
                        max_length=MenuItem._meta.get_field("icon").max_length,
                    ).clean(uploaded_icon)

                except ValidationError:
                    return back(
                        "ملف الصورة غير صالح. جرّب صورة JPG أو PNG.",
                        messages.ERROR,
                    )

                item, _ = MenuItem.objects.get_or_create(
                    name=item_name,
                    category=category,
                    defaults={
                        "is_active": True,
                    },
                )

                if not item.is_active:
                    return back(
                        "الصنف موجود لكنه موقوف. "
                        "يجب تفعيله من إدارة الأصناف أولًا.",
                        messages.ERROR,
                    )

                # لا نمسح الصورة القديمة إذا لم تُرفع صورة جديدة.
                if uploaded_icon is not None:
                    item.icon = uploaded_icon
                    item.save(update_fields=["icon"])

                DailyMenuItem.objects.update_or_create(
                    daily_menu=daily_menu,
                    item=item,
                    defaults={
                        "is_available": True,
                    },
                )

                result_message = (
                    f"تمت إضافة {item.name} إلى قائمة {meal_name}."
                )
            elif action == "publish":
                has_items = daily_menu.entries.filter(
                    is_available=True,
                    item__is_active=True,
                ).exists()

                if not has_items:
                    return back(
                        "اختَر صنفًا واحدًا على الأقل "
                        "واحفظه قبل فتح الطلبات.",
                        messages.ERROR,
                    )

                if (
                    daily_menu.ordering_deadline
                    and timezone.now()
                    >= daily_menu.ordering_deadline
                ):
                    return back(
                        "موعد الطلب انتهى. "
                        "عدّل الموعد قبل إعادة فتح الطلبات.",
                        messages.ERROR,
                    )

                daily_menu.is_published = True
                daily_menu.save(
                    update_fields=["is_published"],
                )

                result_message = (
                    f"تم فتح طلبات {meal_name} للتاريخ المختار."
                )

            else:  # unpublish
                daily_menu.is_published = False
                daily_menu.save(
                    update_fields=["is_published"],
                )

                result_message = (
                    f"تم إغلاق طلبات {meal_name}. "
                    "الطلبات المسجلة سابقًا محفوظة."
                )

        return back(result_message)

    # تجهيز صفحة العرض.
    daily_menu = DailyMenu.objects.filter(
        date=selected_date,
        meal_type=selected_meal,
    ).first()

    available_ids = set()

    if daily_menu:
        available_ids = set(
            daily_menu.entries.filter(
                is_available=True,
            ).values_list("item_id", flat=True)
        )

    category_order = {
        value: index
        for index, value in enumerate(ItemCategory.values)
    }

    catalog_items = list(
        MenuItem.objects.filter(is_active=True)
    )

    catalog_items.sort(
        key=lambda item: (
            category_order.get(item.category, 99),
            item.name,
        )
    )

    for item in catalog_items:
        item.available_today = item.pk in available_ids

    total_available = sum(
        item.available_today
        for item in catalog_items
    )

    return render(
        request,
        "kitchen/manage_menu.html",
        {
            "selected_date": selected_date,
            "selected_meal": selected_meal,
            "meal_name": meal_name,
            "meal_choices": MealType.choices,
            "category_choices": ItemCategory.choices,
            "daily_menu": daily_menu,
            "catalog_items": catalog_items,
            "total_available": total_available,
        },
    )
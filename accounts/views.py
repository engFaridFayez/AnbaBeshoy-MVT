
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import render,redirect
from django.urls import reverse
from django.views.decorators.http import require_GET
from django.db.models import Count, Q
from django.utils import timezone

from kitchen.models import DailyMenu, MealType, Order
from .models import User
from .forms import LoginForm
from .models import User


# ==========================================
# Role Helpers
# ==========================================

def is_admin(user):
    """
    True for admin and superadmin.
    """
    return (
        user.is_authenticated
        and user.role in [
            User.Role.ADMIN,
            User.Role.SUPERADMIN,
        ]
    )


def is_superadmin(user):
    """
    True only for superadmin.
    """
    return (
        user.is_authenticated
        and user.role == User.Role.SUPERADMIN
    )


# ==========================================
# Login View
# ==========================================

class UserLoginView(LoginView):

    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return (
            self.get_redirect_url()
            or reverse("accounts:home")
        )


# ==========================================
# Home View
# ==========================================

@login_required
@require_GET
def home(request):
    today = timezone.localdate()
    now = timezone.now()

    # قوائم اليوم وعدد الأصناف المتاحة في كل قائمة.
    daily_menus = {
        menu.meal_type: menu
        for menu in DailyMenu.objects.filter(
            date=today,
        ).annotate(
            available_count=Count(
                "entries",
                filter=Q(
                    entries__is_available=True,
                    entries__item__is_active=True,
                ),
                distinct=True,
            )
        )
    }

    # الطلبات المسجلة للمستخدم الحالي فقط.
    order_statuses = dict(
        Order.objects.filter(
            user=request.user,
            daily_menu__date=today,
        ).values_list(
            "daily_menu__meal_type",
            "status",
        )
    )

    icons = {
        MealType.BREAKFAST: "🌤️",
        MealType.LUNCH: "☀️",
        MealType.DINNER: "🌙",
    }

    meals = []

    for meal_type, meal_name in MealType.choices:
        menu = daily_menus.get(meal_type)

        has_order = meal_type in order_statuses

        order_cancelled = (
            order_statuses.get(meal_type)
            == Order.Status.CANCELLED
        )

        deadline_passed = bool(
            menu
            and menu.ordering_deadline
            and now >= menu.ordering_deadline
        )

        is_open = bool(
            menu
            and menu.is_published
            and menu.available_count > 0
            and not deadline_passed
            and not order_cancelled
        )

        if order_cancelled:
            status_text = "طلبك ملغي — راجع المسؤول"
        elif is_open:
            status_text = "الطلبات مفتوحة"
        elif deadline_passed:
            status_text = "انتهى موعد الطلب"
        elif menu and menu.is_published:
            status_text = "لا توجد أصناف متاحة"
        else:
            status_text = "الطلبات مغلقة"

        if is_open and has_order:
            button_text = "عرض أو تعديل طلبي"
        elif is_open:
            button_text = "اطلب وجبتك"
        elif has_order:
            button_text = "عرض طلبي"
        else:
            button_text = "الطلب غير متاح"

        meals.append({
            "value": meal_type,
            "name": meal_name,
            "icon": icons.get(meal_type, "🍽️"),
            "is_open": is_open,
            "has_order": has_order,
            "can_visit": is_open or has_order,
            "status_text": status_text,
            "button_text": button_text,
        })

    return render(
        request,
        "accounts/home.html",
        {
            "current_user": request.user,
            "today": today,
            "meals": meals,
            "is_restaurant_admin": request.user.role in (
                User.Role.ADMIN,
                User.Role.SUPERADMIN,
            ),
            "is_superadmin": (
                request.user.role == User.Role.SUPERADMIN
            ),
        },
    )
# ==========================================
# Admin Dashboard
# ==========================================


@login_required
@require_GET
def admin_dashboard(request):

    if request.user.role not in [
        User.Role.ADMIN,
        User.Role.SUPERADMIN,
    ]:
        raise PermissionDenied(
            "ليس لديك صلاحية الدخول للوحة المسؤول."
        )

    return redirect("kitchen:dashboard")

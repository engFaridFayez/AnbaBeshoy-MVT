"""صلاحيات واجهة المخزن."""

from django.core.exceptions import PermissionDenied


def can_access_store(user):
    """
    المخزن متاح فقط:
    - للراهب المسؤول admin
    - للمطور superadmin
    - Django superuser
    """

    if not user:
        return False

    if not user.is_authenticated:
        return False

    if not user.is_active:
        return False

    if user.is_superuser:
        return True

    return getattr(user, "role", "") in (
        "admin",
        "superadmin",
    )


def require_store_access(user):
    if not can_access_store(user):
        raise PermissionDenied(
            "ليس لديك صلاحية الدخول إلى المخزن."
        )


def is_developer(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (
            user.is_superuser
            or getattr(user, "role", "") == "superadmin"
        )
    )


def has_store_permission(user, codename=None):
    """
    طالما المستخدم admin أو superadmin
    فهو مسؤول مخزن في واجهة التطبيق.
    """

    return can_access_store(user)


def can_view_history(user):
    return can_access_store(user)


def can_see_inactive(user):
    return can_access_store(user)


def access_flags(user):
    allowed = can_access_store(user)

    return {
        "can_access_store": allowed,

        "can_operate": allowed,
        "can_view_history": allowed,

        "can_add_product": allowed,
        "can_edit_product": allowed,
        "can_delete_product": allowed,

        "can_manage_categories": allowed,
        "can_manage_units": allowed,

        "can_see_inactive": allowed,
    }
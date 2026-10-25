"""Authorization for the store website, independent of Django Admin access."""
from .services import can_manage_stock


def is_developer(user):
    return bool(
        user.is_authenticated and user.is_active
        and (user.is_superuser or getattr(user, "role", "") == "superadmin")
    )


def has_store_permission(user, codename):
    if is_developer(user):
        return True
    return bool(
        user.is_authenticated and user.is_active
        and getattr(user, "role", "") == "admin"
        and user.has_perm(f"store.{codename}")
    )


def can_view_history(user):
    return can_manage_stock(user) or has_store_permission(user, "view_stockmovement")


def can_see_inactive(user):
    return can_manage_stock(user) or has_store_permission(user, "change_product")


def access_flags(user):
    return {
        "can_operate": can_manage_stock(user),
        "can_view_history": can_view_history(user),
        "can_add_product": has_store_permission(user, "add_product"),
        "can_edit_product": has_store_permission(user, "change_product"),
        "can_delete_product": has_store_permission(user, "delete_product"),
        "can_manage_categories": any(
            has_store_permission(user, f"{verb}_category")
            for verb in ("add", "change", "delete")
        ),
        "can_manage_units": any(
            has_store_permission(user, f"{verb}_unitofmeasure")
            for verb in ("add", "change", "delete")
        ),
        "can_see_inactive": can_see_inactive(user),
    }

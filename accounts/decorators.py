
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required

from .models import User


def admin_required(view_func):

    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):

        if request.user.role not in [
            User.Role.ADMIN,
            User.Role.SUPERADMIN,
        ]:
            raise PermissionDenied(
                "هذه الصفحة للمسؤولين فقط."
            )

        return view_func(request, *args, **kwargs)

    return wrapper


def superadmin_required(view_func):

    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):

        if request.user.role != User.Role.SUPERADMIN:
            raise PermissionDenied(
                "هذه الصفحة للمطور فقط."
            )

        return view_func(request, *args, **kwargs)

    return wrapper

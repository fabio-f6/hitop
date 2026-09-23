from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from website.models import UserProfile


def is_administrator(user):
    """Return whether a user has the application's canonical admin role."""
    if not user.is_authenticated:
        return False

    try:
        return user.userprofile.user_type == "admin"
    except UserProfile.DoesNotExist:
        return False


def can_master_reset(user):
    """Require both the operational role and Django's staff privilege."""
    return is_administrator(user) and user.is_staff


def administrator_required(view_func):
    """Require login and the operational Administrator role for a view."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("website:home")

        if not is_administrator(request.user):
            raise PermissionDenied

        return view_func(request, *args, **kwargs)

    return wrapper


def master_reset_required(view_func):
    """Restrict a view to the deliberately narrower Master Reset role."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("website:home")

        if not can_master_reset(request.user):
            raise PermissionDenied

        return view_func(request, *args, **kwargs)

    return wrapper

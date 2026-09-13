from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import UserProfile


PENDING_VERIFICATION_MESSAGE = (
    "A sua conta aguarda verificação por um administrador. "
    "Ainda não tem acesso à plataforma."
)


def is_unverified_professional(user):
    if not user.is_authenticated:
        return False

    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        return False

    return profile.user_type == "professional" and not profile.is_verified


def verified_professional_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("website:home")

        try:
            profile = request.user.userprofile
        except UserProfile.DoesNotExist:
            messages.error(request, "Acesso negado.")
            return redirect("website:home")

        if profile.user_type != "professional":
            messages.error(request, "Acesso negado.")
            return redirect("website:home")

        if not profile.is_verified:
            logout(request)
            messages.error(request, PENDING_VERIFICATION_MESSAGE)
            return redirect("website:home")

        return view_func(request, *args, **kwargs)

    return wrapper

def user_is_patient(view_func):
    def wrapper(request, *args, **kwargs):
        if hasattr(request.user, 'userprofile') and request.user.userprofile.user_type == 'patient':
            return view_func(request, *args, **kwargs)
        raise PermissionDenied
    return wrapper

def user_is_professional(view_func):
    def wrapper(request, *args, **kwargs):
        if (
            hasattr(request.user, 'userprofile')
            and request.user.userprofile.user_type == 'professional'
            and request.user.userprofile.is_verified
        ):
            return view_func(request, *args, **kwargs)
        raise PermissionDenied
    return wrapper

def user_is_admin(view_func):
    def wrapper(request, *args, **kwargs):
        if hasattr(request.user, 'userprofile') and request.user.userprofile.user_type == 'admin':
            return view_func(request, *args, **kwargs)
        raise PermissionDenied
    return wrapper

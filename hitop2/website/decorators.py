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


def can_use_general_collections(user):
    """Return the single effective authorization rule for Coletas Gerais."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        return False
    return (
        profile.user_type == "professional"
        and profile.is_verified
        and profile.is_researcher
    )


def collection_owner_is_authorized(collection):
    """Apply the correct owner authorization for a collection environment."""
    owner = collection.owner
    if not owner.is_active:
        return False
    if collection.is_test_data:
        try:
            return owner.userprofile.user_type == "admin"
        except UserProfile.DoesNotExist:
            return False
    return can_use_general_collections(owner)


def researcher_required(view_func):
    """Require an approved professional with the additional researcher grant."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("website:home")
        if not can_use_general_collections(request.user):
            raise PermissionDenied
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

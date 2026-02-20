from django.core.exceptions import PermissionDenied

def user_is_patient(view_func):
    def wrapper(request, *args, **kwargs):
        if hasattr(request.user, 'userprofile') and request.user.userprofile.user_type == 'patient':
            return view_func(request, *args, **kwargs)
        raise PermissionDenied
    return wrapper

def user_is_professional(view_func):
    def wrapper(request, *args, **kwargs):
        if hasattr(request.user, 'userprofile') and request.user.userprofile.user_type == 'professional':
            return view_func(request, *args, **kwargs)
        raise PermissionDenied
    return wrapper

def user_is_admin(view_func):
    def wrapper(request, *args, **kwargs):
        if hasattr(request.user, 'userprofile') and request.user.userprofile.user_type == 'admin':
            return view_func(request, *args, **kwargs)
        raise PermissionDenied
    return wrapper
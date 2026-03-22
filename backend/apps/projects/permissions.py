from rest_framework import permissions
from .models import ProjectMember


class IsProjectMember(permissions.BasePermission):
    """Allow access only to members (any role) of the project."""
    message = 'You are not a member of this project.'

    def has_object_permission(self, request, view, obj):
        if obj.owner == request.user:
            return True
        return obj.memberships.filter(user=request.user).exists()


class IsProjectAdminOrOwner(permissions.BasePermission):
    """Allow write access only to admin/owner members."""
    message = 'You must be an admin or owner of this project.'

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            if obj.owner == request.user:
                return True
            return obj.memberships.filter(user=request.user).exists()
        if obj.owner == request.user:
            return True
        return obj.memberships.filter(user=request.user, role__in=['owner', 'admin']).exists()


class IsProjectOwner(permissions.BasePermission):
    """Allow only the project owner."""
    message = 'Only the project owner can perform this action.'

    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user

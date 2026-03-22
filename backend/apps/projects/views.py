import logging
from django.db.models import Q
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Project, ProjectMember
from .serializers import (
    ProjectSerializer, ProjectDetailSerializer,
    ProjectMemberSerializer, AddMemberSerializer
)
from .permissions import IsProjectAdminOrOwner, IsProjectOwner
from apps.core.cache import (
    get_project_list, set_project_list,
    get_project_detail, set_project_detail,
    invalidate_project,
)

logger = logging.getLogger('apps.projects')


class ProjectViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Project.objects.filter(
            Q(owner=user) | Q(members=user)
        ).distinct().select_related('owner').prefetch_related('memberships__user', 'tasks')
        # Filters
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ProjectDetailSerializer
        return ProjectSerializer

    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsProjectAdminOrOwner()]
        return [permissions.IsAuthenticated()]

    def perform_destroy(self, instance):
        if instance.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Only the project owner can delete this project.')
        member_ids = list(instance.members.values_list('id', flat=True))
        member_ids.append(instance.owner_id)
        invalidate_project(str(instance.id), member_ids)
        logger.info('Project %s deleted by user %s', instance.id, self.request.user.id)
        instance.delete()

    @action(detail=True, methods=['post'], url_path='members/add')
    def add_member(self, request, pk=None):
        project = self.get_object()
        self._check_admin_permission(request, project)
        serializer = AddMemberSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user_to_add = serializer.context['member_user']
        if ProjectMember.objects.filter(project=project, user=user_to_add).exists():
            return Response({'error': 'User is already a member.'}, status=status.HTTP_400_BAD_REQUEST)
        if project.owner == user_to_add:
            return Response({'error': 'User is already the owner.'}, status=status.HTTP_400_BAD_REQUEST)
        member = ProjectMember.objects.create(
            project=project,
            user=user_to_add,
            role=serializer.validated_data['role']
        )
        return Response(ProjectMemberSerializer(member).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path='members/(?P<member_id>[^/.]+)/remove')
    def remove_member(self, request, pk=None, member_id=None):
        project = self.get_object()
        self._check_admin_permission(request, project)
        try:
            member = ProjectMember.objects.get(id=member_id, project=project)
        except ProjectMember.DoesNotExist:
            return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)
        if member.user == project.owner:
            return Response({'error': 'Cannot remove the project owner.'}, status=status.HTTP_400_BAD_REQUEST)
        member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['patch'], url_path='members/(?P<member_id>[^/.]+)/role')
    def update_member_role(self, request, pk=None, member_id=None):
        project = self.get_object()
        self._check_admin_permission(request, project)
        try:
            member = ProjectMember.objects.get(id=member_id, project=project)
        except ProjectMember.DoesNotExist:
            return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)
        role = request.data.get('role')
        if role not in ['admin', 'member', 'viewer']:
            return Response({'error': 'Invalid role.'}, status=status.HTTP_400_BAD_REQUEST)
        member.role = role
        member.save()
        return Response(ProjectMemberSerializer(member).data)

    @action(detail=True, methods=['post'], url_path='leave')
    def leave_project(self, request, pk=None):
        project = self.get_object()
        if project.owner == request.user:
            return Response({'error': 'Owner cannot leave. Transfer ownership or delete the project.'}, status=status.HTTP_400_BAD_REQUEST)
        deleted, _ = ProjectMember.objects.filter(project=project, user=request.user).delete()
        if not deleted:
            return Response({'error': 'You are not a member of this project.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': 'You have left the project.'})

    def _check_admin_permission(self, request, project):
        from rest_framework.exceptions import PermissionDenied
        is_owner = project.owner == request.user
        is_admin = project.memberships.filter(user=request.user, role__in=['owner', 'admin']).exists()
        if not (is_owner or is_admin):
            raise PermissionDenied('Only admins or the owner can manage members.')

import logging
from django.db.models import Q
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied

from .models import Task, Comment, TaskActivity
from .serializers import (
    TaskSerializer, TaskDetailSerializer,
    CommentSerializer, TaskActivitySerializer,
    BulkStatusUpdateSerializer
)
from apps.projects.models import Project
from apps.core.cache import invalidate_tasks

logger = logging.getLogger('apps.tasks')


def get_project_or_403(project_id, user):
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        from rest_framework.exceptions import NotFound
        raise NotFound('Project not found.')
    if not (project.owner == user or project.members.filter(id=user.id).exists()):
        raise PermissionDenied('You are not a member of this project.')
    return project


class TaskViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Task.objects.filter(
            Q(project__owner=user) | Q(project__members=user)
        ).distinct().select_related('project', 'reporter', 'assignee')

        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        priority = self.request.query_params.get('priority')
        if priority:
            qs = qs.filter(priority=priority)

        assignee = self.request.query_params.get('assignee')
        if assignee == 'me':
            qs = qs.filter(assignee=user)
        elif assignee:
            qs = qs.filter(assignee_id=assignee)

        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search))

        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return TaskDetailSerializer
        return TaskSerializer

    def perform_create(self, serializer):
        project_id = self.request.data.get('project')
        if not project_id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'project': 'Project is required.'})
        get_project_or_403(project_id, self.request.user)
        task = serializer.save()
        invalidate_tasks(str(project_id))
        # Notify assignee if one was set at creation
        if task.assignee_id and task.assignee_id != self.request.user.id:
            try:
                from .tasks import notify_task_assigned
                notify_task_assigned.delay(
                    str(task.id), str(task.assignee_id), str(self.request.user.id)
                )
            except Exception:
                logger.warning('Could not queue assignment notification for task %s', task.id)

    def perform_update(self, serializer):
        old_assignee = serializer.instance.assignee_id
        task = serializer.save()
        invalidate_tasks(str(task.project_id))
        # Notify new assignee if changed
        if task.assignee_id and task.assignee_id != old_assignee:
            try:
                from .tasks import notify_task_assigned
                notify_task_assigned.delay(
                    str(task.id), str(task.assignee_id), str(self.request.user.id)
                )
            except Exception:
                logger.warning('Could not queue assignment notification for task %s', task.id)

    def perform_destroy(self, instance):
        user = self.request.user
        is_reporter = instance.reporter == user
        is_admin = instance.project.memberships.filter(
            user=user, role__in=['owner', 'admin']
        ).exists()
        is_owner = instance.project.owner == user
        if not (is_reporter or is_admin or is_owner):
            raise PermissionDenied('You can only delete tasks you reported, or if you are an admin/owner.')
        instance.delete()

    @action(detail=False, methods=['post'], url_path='bulk-status')
    def bulk_status_update(self, request):
        serializer = BulkStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task_ids = serializer.validated_data['task_ids']
        new_status = serializer.validated_data['status']
        user = request.user

        tasks = Task.objects.filter(
            id__in=task_ids
        ).filter(Q(project__owner=user) | Q(project__members=user))

        updated_count = tasks.update(status=new_status)
        activities = [
            TaskActivity(task=task, actor=user, verb='bulk status update',
                         detail={'to': new_status})
            for task in tasks
        ]
        TaskActivity.objects.bulk_create(activities)
        return Response({'updated': updated_count})

    @action(detail=True, methods=['get', 'post'], url_path='comments')
    def comments(self, request, pk=None):
        task = self.get_object()
        if request.method == 'GET':
            comments = task.comments.select_related('author').all()
            serializer = CommentSerializer(comments, many=True)
            return Response(serializer.data)
        serializer = CommentSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(task=task, author=request.user)
        TaskActivity.objects.create(
            task=task, actor=request.user,
            verb='added comment', detail={'comment_id': str(comment.id)}
        )
        # Fire async notification (non-blocking)
        try:
            from .tasks import notify_task_comment
            notify_task_comment.delay(str(comment.id))
        except Exception:
            logger.warning('Could not queue comment notification for comment %s', comment.id)
        return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['put', 'patch', 'delete'],
            url_path='comments/(?P<comment_id>[^/.]+)')
    def comment_detail(self, request, pk=None, comment_id=None):
        task = self.get_object()
        try:
            comment = Comment.objects.get(id=comment_id, task=task)
        except Comment.DoesNotExist:
            return Response({'error': 'Comment not found.'}, status=status.HTTP_404_NOT_FOUND)

        if comment.author != request.user:
            raise PermissionDenied('You can only edit or delete your own comments.')

        if request.method == 'DELETE':
            comment.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = CommentSerializer(comment, data=request.data,
                                       partial=(request.method == 'PATCH'),
                                       context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='activity')
    def activity(self, request, pk=None):
        task = self.get_object()
        activities = task.activities.select_related('actor').all()
        serializer = TaskActivitySerializer(activities, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='my-tasks')
    def my_tasks(self, request):
        tasks = self.get_queryset().filter(assignee=request.user)
        page = self.paginate_queryset(tasks)
        if page is not None:
            serializer = TaskSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = TaskSerializer(tasks, many=True, context={'request': request})
        return Response(serializer.data)

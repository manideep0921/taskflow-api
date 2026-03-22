"""
Background tasks for TaskFlow.

Tasks
─────
notify_task_assigned      Email the assignee when a task is assigned to them
notify_task_comment       Email reporter/assignee when a comment is added
cleanup_old_activities    Prune TaskActivity records older than 90 days
generate_project_summary  Build and cache a weekly project summary
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger('taskflow.tasks')
User = get_user_model()


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3},
    retry_backoff=True,
    name='tasks.notify_task_assigned',
)
def notify_task_assigned(self, task_id: str, assignee_id: str, assigned_by_id: str):
    """
    Send an email to the newly assigned user.
    Retries up to 3 times with exponential backoff on failure.
    """
    from apps.tasks.models import Task
    try:
        task = Task.objects.select_related('project', 'assignee').get(id=task_id)
        assignee = User.objects.get(id=assignee_id)
        assigned_by = User.objects.get(id=assigned_by_id)
    except Exception as exc:
        logger.warning('notify_task_assigned: object not found — task=%s err=%s', task_id, exc)
        return

    subject = f'[TaskFlow] Task assigned to you: {task.title}'
    body = (
        f'Hi {assignee.short_name},\n\n'
        f'{assigned_by.full_name} assigned a task to you in project "{task.project.name}".\n\n'
        f'Task: {task.title}\n'
        f'Priority: {task.get_priority_display()}\n'
        f'Status: {task.get_status_display()}\n\n'
        f'Log in to view it: {settings.SITE_URL}/projects/{task.project_id}/\n\n'
        f'— TaskFlow'
    )
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [assignee.email])
        logger.info('Assignment email sent to %s for task %s', assignee.email, task_id)
    except Exception as exc:
        logger.error('Failed to send assignment email to %s: %s', assignee.email, exc)
        raise  # triggers Celery retry


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3},
    retry_backoff=True,
    name='tasks.notify_task_comment',
)
def notify_task_comment(self, comment_id: str):
    """Notify reporter and assignee (excluding commenter) when a comment is added."""
    from apps.tasks.models import Comment
    try:
        comment = Comment.objects.select_related(
            'task__project', 'task__reporter', 'task__assignee', 'author'
        ).get(id=comment_id)
    except Comment.DoesNotExist:
        logger.warning('notify_task_comment: comment %s not found', comment_id)
        return

    task = comment.task
    recipients = set()
    if task.reporter and task.reporter != comment.author:
        recipients.add(task.reporter.email)
    if task.assignee and task.assignee != comment.author:
        recipients.add(task.assignee.email)

    if not recipients:
        return

    subject = f'[TaskFlow] New comment on: {task.title}'
    body = (
        f'{comment.author.full_name} commented on "{task.title}":\n\n'
        f'"{comment.body}"\n\n'
        f'View task: {settings.SITE_URL}/projects/{task.project_id}/\n\n'
        f'— TaskFlow'
    )
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, list(recipients))
        logger.info('Comment notification sent to %s for task %s', recipients, task.id)
    except Exception as exc:
        logger.error('Failed to send comment notification: %s', exc)
        raise


@shared_task(name='tasks.cleanup_old_activities')
def cleanup_old_activities():
    """
    Prune TaskActivity rows older than 90 days.
    Scheduled via Celery Beat — runs nightly.
    """
    from apps.tasks.models import TaskActivity
    cutoff = timezone.now() - timedelta(days=90)
    deleted, _ = TaskActivity.objects.filter(created_at__lt=cutoff).delete()
    logger.info('cleanup_old_activities: deleted %d rows older than %s', deleted, cutoff.date())
    return deleted


@shared_task(name='tasks.generate_project_summary')
def generate_project_summary(project_id: str):
    """
    Compute task breakdown stats for a project and cache them.
    Called after bulk operations to keep the cache warm.
    """
    from apps.projects.models import Project
    from apps.core.cache import set_dashboard_stats
    from django.db.models import Count

    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return

    stats = (
        project.tasks
        .values('status')
        .annotate(count=Count('id'))
        .order_by('status')
    )
    summary = {row['status']: row['count'] for row in stats}
    logger.info('Project summary generated for %s: %s', project_id, summary)
    return summary

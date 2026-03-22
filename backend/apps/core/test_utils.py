"""
Shared test utilities — factory helpers and a base TestCase
with convenience methods used across all test modules.
"""
import uuid
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.projects.models import Project, ProjectMember
from apps.tasks.models import Task, Comment

User = get_user_model()


# ── Factories ─────────────────────────────────────────────────────────────────

def make_user(email=None, full_name='Test User', password='TestPass1!', **kwargs):
    email = email or f'user_{uuid.uuid4().hex[:8]}@test.com'
    return User.objects.create_user(email=email, full_name=full_name, password=password, **kwargs)


def make_project(owner, name=None, status='active', **kwargs):
    name = name or f'Project {uuid.uuid4().hex[:6]}'
    project = Project.objects.create(owner=owner, name=name, status=status, **kwargs)
    ProjectMember.objects.create(project=project, user=owner, role='owner')
    return project


def add_member(project, user, role='member'):
    return ProjectMember.objects.create(project=project, user=user, role=role)


def make_task(project, reporter, title=None, status='todo', priority='medium', **kwargs):
    title = title or f'Task {uuid.uuid4().hex[:6]}'
    return Task.objects.create(
        project=project, reporter=reporter,
        title=title, status=status, priority=priority, **kwargs
    )


def make_comment(task, author, body='Test comment'):
    return Comment.objects.create(task=task, author=author, body=body)


# ── Auth helpers ──────────────────────────────────────────────────────────────

def auth_client(user):
    """Return an APIClient pre-authenticated with JWT for the given user."""
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')
    return client

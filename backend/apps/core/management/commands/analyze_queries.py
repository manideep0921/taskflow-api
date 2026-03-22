"""
python manage.py analyze_queries

Runs the three most common API query patterns, counts DB hits,
measures wall time, and flags N+1 problems.

Used during development to catch regressions before deploy.
Output is printed to stdout — pipe to a file for CI artifacts.
"""
import time
from django.core.management.base import BaseCommand
from django.db import connection, reset_queries
from django.test.utils import override_settings
from django.contrib.auth import get_user_model

User = get_user_model()


def _measure(label, fn):
    """Run fn(), count queries, return (result, query_count, elapsed_ms)."""
    reset_queries()
    t0 = time.perf_counter()
    result = fn()
    elapsed = (time.perf_counter() - t0) * 1000
    queries = len(connection.queries)
    return result, queries, elapsed


class Command(BaseCommand):
    help = 'Analyze query count and timing for common API patterns'

    def add_arguments(self, parser):
        parser.add_argument(
            '--warn-threshold', type=int, default=5,
            help='Warn if query count exceeds this number (default: 5)'
        )

    def handle(self, *args, **options):
        threshold = options['warn_threshold']

        with override_settings(DEBUG=True):
            self._run(threshold)

    def _run(self, threshold):
        from apps.projects.models import Project
        from apps.tasks.models import Task

        self.stdout.write('\n' + '═' * 60)
        self.stdout.write('  TaskFlow Query Analysis')
        self.stdout.write('═' * 60)

        user = User.objects.first()
        if not user:
            self.stdout.write(self.style.ERROR(
                'No users found. Run `python manage.py seed` first.'
            ))
            return

        tests = [
            (
                'Project list (owner + member projects)',
                lambda: list(
                    Project.objects.filter(
                        __import__('django.db.models', fromlist=['Q']).Q(owner=user) |
                        __import__('django.db.models', fromlist=['Q']).Q(members=user)
                    ).distinct()
                     .select_related('owner')
                     .prefetch_related('memberships__user', 'tasks')
                )
            ),
            (
                'Task list for first project (with related)',
                lambda: list(
                    Task.objects.filter(
                        project=Project.objects.filter(owner=user).first()
                    ).select_related('project', 'reporter', 'assignee')
                ) if Project.objects.filter(owner=user).exists() else []
            ),
            (
                'Task list WITHOUT select_related (N+1 demo)',
                lambda: [
                    {'title': t.title, 'reporter': t.reporter.email}
                    for t in Task.objects.filter(
                        project=Project.objects.filter(owner=user).first()
                    )
                ] if Project.objects.filter(owner=user).exists() else []
            ),
            (
                'My tasks (assignee=user, cross-project)',
                lambda: list(
                    Task.objects.filter(assignee=user)
                         .select_related('project', 'reporter')
                )
            ),
            (
                'Task detail (single task + comments + activity)',
                lambda: _fetch_task_detail(user)
            ),
        ]

        all_ok = True
        for label, fn in tests:
            try:
                result, q_count, elapsed = _measure(label, fn)
                rows = len(result) if hasattr(result, '__len__') else '?'
                status = self.style.SUCCESS('OK') if q_count <= threshold else self.style.WARNING('WARN')
                flag = '' if q_count <= threshold else f'  ← {q_count - threshold} extra queries!'
                if q_count > threshold:
                    all_ok = False
                self.stdout.write(
                    f'\n  [{status}] {label}\n'
                    f'       Queries : {q_count}{flag}\n'
                    f'       Time    : {elapsed:.1f}ms\n'
                    f'       Rows    : {rows}'
                )
                if q_count > threshold:
                    self._show_slow_queries(q_count)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'\n  [ERROR] {label}: {exc}'))

        self.stdout.write('\n' + '═' * 60)
        if all_ok:
            self.stdout.write(self.style.SUCCESS(
                f'  ✓ All patterns within {threshold}-query budget\n'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'  ⚠ Some patterns exceeded {threshold}-query budget — review above\n'
            ))

    def _show_slow_queries(self, count):
        """Print the raw SQL for the last `count` queries."""
        self.stdout.write('       Queries executed:')
        for i, q in enumerate(connection.queries[-count:], 1):
            sql = q['sql']
            trimmed = (sql[:120] + '…') if len(sql) > 120 else sql
            self.stdout.write(f'         {i}. [{q["time"]}s] {trimmed}')


def _fetch_task_detail(user):
    from apps.tasks.models import Task
    from apps.projects.models import Project
    task = Task.objects.filter(
        project__owner=user
    ).prefetch_related('comments__author', 'activities__actor').first()
    if not task:
        return []
    # Force evaluation of prefetched data
    return list(task.comments.all()) + list(task.activities.all())

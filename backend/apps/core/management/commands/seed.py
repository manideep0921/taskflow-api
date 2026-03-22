import random
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.projects.models import Project, ProjectMember
from apps.tasks.models import Task

User = get_user_model()

PROJECTS = [
    ('TaskFlow Backend', 'Core API development and infrastructure'),
    ('Mobile App', 'iOS and Android client development'),
    ('Marketing Site', 'Landing page and blog redesign'),
]

TASKS = [
    ('Set up CI/CD pipeline', 'in_progress', 'high'),
    ('Write API documentation', 'todo', 'medium'),
    ('Fix authentication bug', 'done', 'critical'),
    ('Add pagination to endpoints', 'done', 'medium'),
    ('Design database schema', 'done', 'high'),
    ('Implement search feature', 'in_review', 'medium'),
    ('Set up monitoring', 'todo', 'low'),
    ('Performance testing', 'backlog', 'medium'),
    ('Security audit', 'todo', 'high'),
    ('Write unit tests', 'in_progress', 'high'),
]


class Command(BaseCommand):
    help = 'Seed the database with demo data'

    def handle(self, *args, **options):
        self.stdout.write('Seeding database...')

        # Create demo users
        admin, _ = User.objects.get_or_create(
            email='admin@taskflow.dev',
            defaults={'full_name': 'Alex Admin', 'is_staff': True, 'is_superuser': True}
        )
        admin.set_password('Admin1234!')
        admin.save()

        dev, _ = User.objects.get_or_create(
            email='dev@taskflow.dev',
            defaults={'full_name': 'Dev User'}
        )
        dev.set_password('Dev12345!')
        dev.save()

        # Create projects
        for name, description in PROJECTS:
            project, created = Project.objects.get_or_create(
                name=name,
                owner=admin,
                defaults={'description': description, 'status': 'active'}
            )
            if created:
                ProjectMember.objects.get_or_create(
                    project=project, user=admin, defaults={'role': 'owner'}
                )
                ProjectMember.objects.get_or_create(
                    project=project, user=dev, defaults={'role': 'member'}
                )
                for i, (title, status, priority) in enumerate(TASKS):
                    Task.objects.create(
                        project=project,
                        title=title,
                        description=f'Description for: {title}',
                        status=status,
                        priority=priority,
                        reporter=admin,
                        assignee=random.choice([admin, dev, None]),
                        order=i,
                    )

        self.stdout.write(self.style.SUCCESS(
            '\nDemo data created!\n'
            '  Admin: admin@taskflow.dev / Admin1234!\n'
            '  Dev:   dev@taskflow.dev  / Dev12345!'
        ))

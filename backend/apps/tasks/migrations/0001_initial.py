import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('projects', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Task',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=500)),
                ('description', models.TextField(blank=True)),
                ('status', models.CharField(
                    choices=[('backlog','Backlog'),('todo','To Do'),('in_progress','In Progress'),
                             ('in_review','In Review'),('done','Done'),('cancelled','Cancelled')],
                    db_index=True, default='todo', max_length=20)),
                ('priority', models.CharField(
                    choices=[('low','Low'),('medium','Medium'),('high','High'),('critical','Critical')],
                    db_index=True, default='medium', max_length=20)),
                ('due_date', models.DateField(blank=True, null=True)),
                ('estimated_hours', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('tags', models.JSONField(blank=True, default=list)),
                ('order', models.PositiveIntegerField(db_index=True, default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assignee', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='assigned_tasks', to=settings.AUTH_USER_MODEL)),
                ('project', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name='tasks', to='projects.project')),
                ('reporter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='reported_tasks', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'tasks', 'ordering': ['order', '-created_at']},
        ),
        migrations.CreateModel(
            name='Comment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('body', models.TextField()),
                ('edited', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='task_comments', to=settings.AUTH_USER_MODEL)),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='comments', to='tasks.task')),
            ],
            options={'db_table': 'task_comments', 'ordering': ['created_at']},
        ),
        migrations.CreateModel(
            name='TaskActivity',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('verb', models.CharField(max_length=100)),
                ('detail', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='task_activities', to=settings.AUTH_USER_MODEL)),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='activities', to='tasks.task')),
            ],
            options={'db_table': 'task_activities', 'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='task',
            index=models.Index(fields=['project', 'status'], name='tasks_project_status_idx'),
        ),
        migrations.AddIndex(
            model_name='task',
            index=models.Index(fields=['project', 'assignee'], name='tasks_project_assignee_idx'),
        ),
        migrations.AddIndex(
            model_name='task',
            index=models.Index(fields=['project', 'priority'], name='tasks_project_priority_idx'),
        ),
        migrations.AddIndex(
            model_name='task',
            index=models.Index(fields=['due_date'], name='tasks_due_date_idx'),
        ),
    ]

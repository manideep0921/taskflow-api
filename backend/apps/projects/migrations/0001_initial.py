import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('status', models.CharField(
                    choices=[('active','Active'),('on_hold','On Hold'),('completed','Completed'),('archived','Archived')],
                    db_index=True, default='active', max_length=20)),
                ('due_date', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='owned_projects', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'projects', 'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='ProjectMember',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('role', models.CharField(
                    choices=[('owner','Owner'),('admin','Admin'),('member','Member'),('viewer','Viewer')],
                    default='member', max_length=20)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='memberships', to='projects.project')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='project_memberships', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'project_members', 'ordering': ['joined_at'],
                     'unique_together': {('project', 'user')}},
        ),
        migrations.AddField(
            model_name='project',
            name='members',
            field=models.ManyToManyField(blank=True, related_name='projects',
                through='projects.ProjectMember', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddIndex(
            model_name='project',
            index=models.Index(fields=['owner', 'status'], name='projects_owner_status_idx'),
        ),
        migrations.AddIndex(
            model_name='project',
            index=models.Index(fields=['status', 'created_at'], name='projects_status_created_idx'),
        ),
    ]

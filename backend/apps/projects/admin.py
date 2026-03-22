from django.contrib import admin
from .models import Project, ProjectMember


class ProjectMemberInline(admin.TabularInline):
    model = ProjectMember
    extra = 0
    fields = ('user', 'role', 'joined_at')
    readonly_fields = ('joined_at',)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'status', 'task_count', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'description', 'owner__email')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ProjectMemberInline]
    ordering = ('-created_at',)


@admin.register(ProjectMember)
class ProjectMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'project', 'role', 'joined_at')
    list_filter = ('role',)
    search_fields = ('user__email', 'project__name')

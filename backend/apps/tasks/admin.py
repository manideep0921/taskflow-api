from django.contrib import admin
from .models import Task, Comment, TaskActivity


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    fields = ('author', 'body', 'edited', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'project', 'status', 'priority', 'assignee', 'due_date', 'created_at')
    list_filter = ('status', 'priority', 'project')
    search_fields = ('title', 'description', 'assignee__email', 'reporter__email')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [CommentInline]
    ordering = ('-created_at',)
    list_select_related = ('project', 'assignee', 'reporter')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('task', 'author', 'edited', 'created_at')
    search_fields = ('body', 'author__email', 'task__title')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(TaskActivity)
class TaskActivityAdmin(admin.ModelAdmin):
    list_display = ('task', 'actor', 'verb', 'created_at')
    list_filter = ('verb',)
    search_fields = ('task__title', 'actor__email')
    readonly_fields = ('created_at',)

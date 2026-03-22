from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Task, Comment, TaskActivity
from apps.accounts.serializers import UserSerializer

User = get_user_model()


class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = Comment
        fields = ('id', 'author', 'body', 'edited', 'created_at', 'updated_at')
        read_only_fields = ('id', 'author', 'edited', 'created_at', 'updated_at')

    def update(self, instance, validated_data):
        instance.body = validated_data.get('body', instance.body)
        instance.edited = True
        instance.save()
        return instance


class TaskActivitySerializer(serializers.ModelSerializer):
    actor = UserSerializer(read_only=True)

    class Meta:
        model = TaskActivity
        fields = ('id', 'actor', 'verb', 'detail', 'created_at')
        read_only_fields = fields


class TaskSerializer(serializers.ModelSerializer):
    reporter = UserSerializer(read_only=True)
    assignee = UserSerializer(read_only=True)
    assignee_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    comment_count = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = (
            'id', 'project', 'title', 'description', 'status', 'priority',
            'assignee', 'assignee_id', 'reporter', 'due_date',
            'estimated_hours', 'tags', 'order', 'comment_count',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'reporter', 'created_at', 'updated_at', 'comment_count')

    def get_comment_count(self, obj):
        return obj.comments.count()

    def validate_assignee_id(self, value):
        if value is None:
            return value
        project_id = self.initial_data.get('project') or (self.instance.project_id if self.instance else None)
        if project_id:
            from apps.projects.models import Project
            try:
                project = Project.objects.get(id=project_id)
                if not (project.members.filter(id=value).exists() or str(project.owner_id) == str(value)):
                    raise serializers.ValidationError('Assignee must be a member of the project.')
            except Project.DoesNotExist:
                pass
        return value

    def validate_tags(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('Tags must be a list.')
        if len(value) > 10:
            raise serializers.ValidationError('Maximum 10 tags allowed.')
        return [str(tag).strip().lower() for tag in value if str(tag).strip()]

    def create(self, validated_data):
        request = self.context['request']
        validated_data['reporter'] = request.user
        assignee_id = validated_data.pop('assignee_id', None)
        task = Task.objects.create(**validated_data)
        if assignee_id:
            try:
                task.assignee = User.objects.get(id=assignee_id)
                task.save()
            except User.DoesNotExist:
                pass
        TaskActivity.objects.create(
            task=task, actor=request.user,
            verb='created task', detail={}
        )
        return task

    def update(self, instance, validated_data):
        request = self.context['request']
        assignee_id = validated_data.pop('assignee_id', 'UNCHANGED')
        changes = {}

        tracked = ['status', 'priority', 'assignee', 'title']
        for field in tracked:
            old_val = getattr(instance, field)
            if field in validated_data and validated_data[field] != old_val:
                changes[field] = {
                    'from': str(old_val) if old_val else None,
                    'to': str(validated_data[field]),
                }

        if assignee_id != 'UNCHANGED':
            old_assignee = str(instance.assignee_id) if instance.assignee_id else None
            new_assignee = str(assignee_id) if assignee_id else None
            if old_assignee != new_assignee:
                changes['assignee_id'] = {'from': old_assignee, 'to': new_assignee}
            if assignee_id:
                try:
                    instance.assignee = User.objects.get(id=assignee_id)
                except User.DoesNotExist:
                    pass
            else:
                instance.assignee = None

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if changes:
            TaskActivity.objects.create(
                task=instance, actor=request.user,
                verb='updated task', detail=changes
            )
        return instance


class TaskDetailSerializer(TaskSerializer):
    comments = CommentSerializer(many=True, read_only=True)
    activities = TaskActivitySerializer(many=True, read_only=True)

    class Meta(TaskSerializer.Meta):
        fields = TaskSerializer.Meta.fields + ('comments', 'activities')


class BulkStatusUpdateSerializer(serializers.Serializer):
    task_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=100)
    status = serializers.ChoiceField(choices=[c[0] for c in Task.STATUS_CHOICES])

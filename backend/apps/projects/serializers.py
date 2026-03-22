from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Project, ProjectMember
from apps.accounts.serializers import UserSerializer

User = get_user_model()


class ProjectMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = ProjectMember
        fields = ('id', 'user', 'user_id', 'role', 'joined_at')
        read_only_fields = ('id', 'joined_at')


class ProjectSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    member_count = serializers.SerializerMethodField()
    task_count = serializers.IntegerField(read_only=True)
    completed_task_count = serializers.IntegerField(read_only=True)
    user_role = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = (
            'id', 'name', 'description', 'status', 'owner',
            'due_date', 'member_count', 'task_count',
            'completed_task_count', 'user_role', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'owner', 'created_at', 'updated_at')

    def get_member_count(self, obj):
        return obj.memberships.count()

    def get_user_role(self, obj):
        request = self.context.get('request')
        if not request:
            return None
        membership = obj.memberships.filter(user=request.user).first()
        if membership:
            return membership.role
        if obj.owner == request.user:
            return 'owner'
        return None

    def create(self, validated_data):
        request = self.context['request']
        project = Project.objects.create(owner=request.user, **validated_data)
        # Auto-add owner as member with 'owner' role
        ProjectMember.objects.create(project=project, user=request.user, role='owner')
        return project


class ProjectDetailSerializer(ProjectSerializer):
    members = ProjectMemberSerializer(source='memberships', many=True, read_only=True)

    class Meta(ProjectSerializer.Meta):
        fields = ProjectSerializer.Meta.fields + ('members',)


class AddMemberSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=['admin', 'member', 'viewer'], default='member')

    def validate_email(self, value):
        try:
            user = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError('No user found with this email.')
        self.context['member_user'] = user
        return value

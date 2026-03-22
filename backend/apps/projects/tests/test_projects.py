"""
tests/projects — CRUD, member management, role-based access.

Scenarios tested
────────────────
List       : owner sees own projects, member sees joined projects, no leakage
Create     : happy path, missing name, auto-adds owner as member
Retrieve   : member can read, non-member cannot
Update     : admin can update, member cannot, non-member gets 403/404
Delete     : owner can delete, admin cannot, member cannot
Members    : add by email, add non-existent user, remove, update role, leave
"""
from django.test import TestCase
from rest_framework import status

from apps.core.test_utils import make_user, make_project, add_member, auth_client


LIST_URL   = '/api/v1/projects/'
DETAIL_URL = lambda pk: f'/api/v1/projects/{pk}/'
MEMBERS_ADD_URL    = lambda pk: f'/api/v1/projects/{pk}/members/add/'
MEMBERS_REMOVE_URL = lambda pk, mid: f'/api/v1/projects/{pk}/members/{mid}/remove/'
MEMBERS_ROLE_URL   = lambda pk, mid: f'/api/v1/projects/{pk}/members/{mid}/role/'
LEAVE_URL          = lambda pk: f'/api/v1/projects/{pk}/leave/'


class ProjectListCreateTests(TestCase):
    def setUp(self):
        self.owner = make_user(email='owner@test.com')
        self.other = make_user(email='other@test.com')
        self.project = make_project(self.owner, name='My Project')

    def test_list_own_projects(self):
        client = auth_client(self.owner)
        res = client.get(LIST_URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        names = [p['name'] for p in res.json()['results']]
        self.assertIn('My Project', names)

    def test_list_does_not_include_unrelated_projects(self):
        stranger = make_user()
        make_project(stranger, name='Stranger Project')
        client = auth_client(self.owner)
        res = client.get(LIST_URL)
        names = [p['name'] for p in res.json()['results']]
        self.assertNotIn('Stranger Project', names)

    def test_member_sees_joined_project(self):
        member = make_user()
        add_member(self.project, member)
        client = auth_client(member)
        res = client.get(LIST_URL)
        ids = [p['id'] for p in res.json()['results']]
        self.assertIn(str(self.project.id), ids)

    def test_create_project_success(self):
        client = auth_client(self.owner)
        res = client.post(LIST_URL, {'name': 'New Project', 'description': 'Desc'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()
        self.assertEqual(data['name'], 'New Project')
        self.assertEqual(data['owner']['email'], 'owner@test.com')

    def test_create_project_auto_adds_owner_as_member(self):
        from apps.projects.models import ProjectMember
        client = auth_client(self.owner)
        res = client.post(LIST_URL, {'name': 'Auto Member Test'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        pid = res.json()['id']
        self.assertTrue(
            ProjectMember.objects.filter(project_id=pid, user=self.owner, role='owner').exists()
        )

    def test_create_project_missing_name(self):
        client = auth_client(self.owner)
        res = client.post(LIST_URL, {'description': 'No name'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_requires_auth(self):
        from rest_framework.test import APIClient
        res = APIClient().get(LIST_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_search_filter(self):
        make_project(self.owner, name='Alpha Project')
        make_project(self.owner, name='Beta Project')
        client = auth_client(self.owner)
        res = client.get(LIST_URL + '?search=Alpha')
        names = [p['name'] for p in res.json()['results']]
        self.assertIn('Alpha Project', names)
        self.assertNotIn('Beta Project', names)

    def test_status_filter(self):
        make_project(self.owner, name='Active', status='active')
        make_project(self.owner, name='Archived', status='archived')
        client = auth_client(self.owner)
        res = client.get(LIST_URL + '?status=archived')
        names = [p['name'] for p in res.json()['results']]
        self.assertIn('Archived', names)
        self.assertNotIn('Active', names)


class ProjectRetrieveTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.member = make_user()
        self.stranger = make_user()
        self.project = make_project(self.owner)
        add_member(self.project, self.member)

    def test_owner_can_retrieve(self):
        res = auth_client(self.owner).get(DETAIL_URL(self.project.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_member_can_retrieve(self):
        res = auth_client(self.member).get(DETAIL_URL(self.project.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_stranger_cannot_retrieve(self):
        res = auth_client(self.stranger).get(DETAIL_URL(self.project.id))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_detail_contains_members(self):
        res = auth_client(self.owner).get(DETAIL_URL(self.project.id))
        data = res.json()
        self.assertIn('members', data)


class ProjectUpdateDeleteTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.admin = make_user()
        self.member = make_user()
        self.stranger = make_user()
        self.project = make_project(self.owner)
        add_member(self.project, self.admin, role='admin')
        add_member(self.project, self.member, role='member')

    def test_owner_can_update(self):
        res = auth_client(self.owner).patch(DETAIL_URL(self.project.id), {'name': 'Updated'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()['name'], 'Updated')

    def test_admin_can_update(self):
        res = auth_client(self.admin).patch(DETAIL_URL(self.project.id), {'name': 'Admin Update'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_member_cannot_update(self):
        res = auth_client(self.member).patch(DETAIL_URL(self.project.id), {'name': 'Nope'}, format='json')
        self.assertIn(res.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_owner_can_delete(self):
        res = auth_client(self.owner).delete(DETAIL_URL(self.project.id))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        from apps.projects.models import Project
        self.assertFalse(Project.objects.filter(id=self.project.id).exists())

    def test_admin_cannot_delete(self):
        res = auth_client(self.admin).delete(DETAIL_URL(self.project.id))
        self.assertIn(res.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_stranger_cannot_delete(self):
        res = auth_client(self.stranger).delete(DETAIL_URL(self.project.id))
        self.assertIn(res.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])


class ProjectMemberManagementTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.project = make_project(self.owner)
        self.new_user = make_user(email='newguy@test.com')

    def test_owner_can_add_member(self):
        res = auth_client(self.owner).post(
            MEMBERS_ADD_URL(self.project.id),
            {'email': 'newguy@test.com', 'role': 'member'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.json()['role'], 'member')

    def test_add_nonexistent_user(self):
        res = auth_client(self.owner).post(
            MEMBERS_ADD_URL(self.project.id),
            {'email': 'nobody@test.com'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_duplicate_member(self):
        add_member(self.project, self.new_user)
        res = auth_client(self.owner).post(
            MEMBERS_ADD_URL(self.project.id),
            {'email': 'newguy@test.com'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remove_member(self):
        membership = add_member(self.project, self.new_user)
        res = auth_client(self.owner).delete(
            MEMBERS_REMOVE_URL(self.project.id, membership.id)
        )
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

    def test_cannot_remove_owner(self):
        from apps.projects.models import ProjectMember
        owner_membership = ProjectMember.objects.get(project=self.project, user=self.owner)
        res = auth_client(self.owner).delete(
            MEMBERS_REMOVE_URL(self.project.id, owner_membership.id)
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_member_role(self):
        membership = add_member(self.project, self.new_user, role='member')
        res = auth_client(self.owner).patch(
            MEMBERS_ROLE_URL(self.project.id, membership.id),
            {'role': 'admin'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()['role'], 'admin')

    def test_member_cannot_add_members(self):
        plain_member = make_user()
        add_member(self.project, plain_member, role='member')
        another = make_user(email='another@test.com')
        res = auth_client(plain_member).post(
            MEMBERS_ADD_URL(self.project.id),
            {'email': 'another@test.com'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_leave_project(self):
        member = make_user()
        add_member(self.project, member)
        res = auth_client(member).post(LEAVE_URL(self.project.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        from apps.projects.models import ProjectMember
        self.assertFalse(ProjectMember.objects.filter(project=self.project, user=member).exists())

    def test_owner_cannot_leave(self):
        res = auth_client(self.owner).post(LEAVE_URL(self.project.id))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

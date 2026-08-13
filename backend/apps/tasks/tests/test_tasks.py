"""
tests/tasks — CRUD, filters, comments, bulk ops, permissions.

Scenarios tested
────────────────
Create     : happy path, non-member blocked, project required
List       : filters by project/status/priority/assignee/search
Retrieve   : member can read, non-member cannot
Update     : reporter can update own, admin can update any
Delete     : reporter can delete own, member cannot delete others'
Comments   : add, edit (own only), delete (own only)
Bulk status: valid update, cross-project leakage blocked
My tasks   : only returns tasks assigned to me
"""
from django.test import TestCase
from rest_framework import status as http_status

from apps.core.test_utils import (
    make_user, make_project, add_member,
    make_task, make_comment, auth_client
)

LIST_URL           = '/api/v1/tasks/'
DETAIL_URL         = lambda pk: f'/api/v1/tasks/{pk}/'
COMMENTS_URL       = lambda pk: f'/api/v1/tasks/{pk}/comments/'
COMMENT_DETAIL_URL = lambda pk, cid: f'/api/v1/tasks/{pk}/comments/{cid}/'
BULK_URL           = '/api/v1/tasks/bulk-status/'
MY_TASKS_URL       = '/api/v1/tasks/my-tasks/'
ACTIVITY_URL       = lambda pk: f'/api/v1/tasks/{pk}/activity/'


class TaskCreateTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.member = make_user()
        self.stranger = make_user()
        self.project = make_project(self.owner)
        add_member(self.project, self.member)

    def _payload(self, **kwargs):
        return {
            'project': str(self.project.id),
            'title': 'Test Task',
            'priority': 'medium',
            'status': 'todo',
            **kwargs,
        }

    def test_owner_can_create_task(self):
        res = auth_client(self.owner).post(LIST_URL, self._payload(), format='json')
        self.assertEqual(res.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(res.json()['title'], 'Test Task')

    def test_member_can_create_task(self):
        res = auth_client(self.member).post(LIST_URL, self._payload(), format='json')
        self.assertEqual(res.status_code, http_status.HTTP_201_CREATED)

    def test_stranger_cannot_create_task(self):
        res = auth_client(self.stranger).post(LIST_URL, self._payload(), format='json')
        self.assertIn(res.status_code, [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])

    def test_create_task_missing_project(self):
        res = auth_client(self.owner).post(LIST_URL, {'title': 'No Project'}, format='json')
        self.assertEqual(res.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_create_task_records_reporter(self):
        res = auth_client(self.member).post(LIST_URL, self._payload(), format='json')
        self.assertEqual(res.json()['reporter']['email'], self.member.email)

    def test_create_task_sets_tags(self):
        res = auth_client(self.owner).post(LIST_URL, self._payload(tags=['backend', 'urgent']), format='json')
        self.assertEqual(res.status_code, http_status.HTTP_201_CREATED)
        self.assertListEqual(res.json()['tags'], ['backend', 'urgent'])

    def test_create_task_too_many_tags(self):
        res = auth_client(self.owner).post(
            LIST_URL,
            self._payload(tags=[f'tag{i}' for i in range(11)]),
            format='json'
        )
        self.assertEqual(res.status_code, http_status.HTTP_400_BAD_REQUEST)


class TaskListFilterTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.project = make_project(self.owner)
        self.t1 = make_task(self.project, self.owner, title='Alpha', status='todo', priority='high')
        self.t2 = make_task(self.project, self.owner, title='Beta', status='done', priority='low')
        self.t3 = make_task(self.project, self.owner, title='Gamma', status='in_progress', priority='high')
        self.client = auth_client(self.owner)

    def test_filter_by_project(self):
        other_project = make_project(self.owner)
        make_task(other_project, self.owner, title='Other')
        res = self.client.get(LIST_URL + f'?project={self.project.id}')
        titles = [t['title'] for t in res.json()['results']]
        self.assertNotIn('Other', titles)
        self.assertIn('Alpha', titles)

    def test_filter_by_status(self):
        res = self.client.get(LIST_URL + '?status=done')
        titles = [t['title'] for t in res.json()['results']]
        self.assertIn('Beta', titles)
        self.assertNotIn('Alpha', titles)

    def test_filter_by_priority(self):
        res = self.client.get(LIST_URL + '?priority=high')
        titles = [t['title'] for t in res.json()['results']]
        self.assertIn('Alpha', titles)
        self.assertIn('Gamma', titles)
        self.assertNotIn('Beta', titles)

    def test_search_filter(self):
        res = self.client.get(LIST_URL + '?search=alph')
        titles = [t['title'] for t in res.json()['results']]
        self.assertIn('Alpha', titles)
        self.assertNotIn('Beta', titles)

    def test_assignee_me_filter(self):
        self.t1.assignee = self.owner
        self.t1.save()
        res = self.client.get(LIST_URL + '?assignee=me')
        ids = [t['id'] for t in res.json()['results']]
        self.assertIn(str(self.t1.id), ids)
        self.assertNotIn(str(self.t2.id), ids)


class TaskUpdateDeleteTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.reporter = make_user()
        self.admin = make_user()
        self.viewer = make_user()
        self.project = make_project(self.owner)
        add_member(self.project, self.reporter, role='member')
        add_member(self.project, self.admin, role='admin')
        add_member(self.project, self.viewer, role='viewer')
        self.task = make_task(self.project, self.reporter)

    def test_reporter_can_update_own_task(self):
        res = auth_client(self.reporter).patch(
            DETAIL_URL(self.task.id), {'title': 'Updated'}, format='json'
        )
        self.assertEqual(res.status_code, http_status.HTTP_200_OK)
        self.assertEqual(res.json()['title'], 'Updated')

    def test_admin_can_update_any_task(self):
        res = auth_client(self.admin).patch(
            DETAIL_URL(self.task.id), {'status': 'done'}, format='json'
        )
        self.assertEqual(res.status_code, http_status.HTTP_200_OK)
        self.assertEqual(res.json()['status'], 'done')

    def test_update_creates_activity_log(self):
        from apps.tasks.models import TaskActivity
        auth_client(self.reporter).patch(
            DETAIL_URL(self.task.id), {'status': 'in_progress'}, format='json'
        )
        self.assertTrue(
            TaskActivity.objects.filter(task=self.task, verb='updated task').exists()
        )

    def test_reporter_can_delete_own_task(self):
        res = auth_client(self.reporter).delete(DETAIL_URL(self.task.id))
        self.assertEqual(res.status_code, http_status.HTTP_204_NO_CONTENT)

    def test_viewer_cannot_delete_task(self):
        other_task = make_task(self.project, self.owner)
        res = auth_client(self.viewer).delete(DETAIL_URL(other_task.id))
        self.assertEqual(res.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_stranger_cannot_retrieve_task(self):
        stranger = make_user()
        res = auth_client(stranger).get(DETAIL_URL(self.task.id))
        self.assertIn(res.status_code, [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])


class TaskDetailTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.project = make_project(self.owner)
        self.task = make_task(self.project, self.owner)
        self.client = auth_client(self.owner)

    def test_detail_contains_comments_and_activities(self):
        make_comment(self.task, self.owner, body='Hello')
        res = self.client.get(DETAIL_URL(self.task.id))
        self.assertEqual(res.status_code, http_status.HTTP_200_OK)
        data = res.json()
        self.assertIn('comments', data)
        self.assertIn('activities', data)
        self.assertEqual(len(data['comments']), 1)
        self.assertEqual(data['comments'][0]['body'], 'Hello')


class CommentTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.other = make_user()
        self.project = make_project(self.owner)
        add_member(self.project, self.other)
        self.task = make_task(self.project, self.owner)

    def test_add_comment(self):
        res = auth_client(self.owner).post(
            COMMENTS_URL(self.task.id), {'body': 'My comment'}, format='json'
        )
        self.assertEqual(res.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(res.json()['body'], 'My comment')

    def test_list_comments(self):
        make_comment(self.task, self.owner, 'First')
        make_comment(self.task, self.other, 'Second')
        res = auth_client(self.owner).get(COMMENTS_URL(self.task.id))
        self.assertEqual(res.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(res.json()), 2)

    def test_owner_can_edit_own_comment(self):
        comment = make_comment(self.task, self.owner, 'Original')
        res = auth_client(self.owner).patch(
            COMMENT_DETAIL_URL(self.task.id, comment.id),
            {'body': 'Edited'},
            format='json'
        )
        self.assertEqual(res.status_code, http_status.HTTP_200_OK)
        self.assertEqual(res.json()['body'], 'Edited')
        self.assertTrue(res.json()['edited'])

    def test_cannot_edit_others_comment(self):
        comment = make_comment(self.task, self.owner, 'Owner comment')
        res = auth_client(self.other).patch(
            COMMENT_DETAIL_URL(self.task.id, comment.id),
            {'body': 'Hijack'},
            format='json'
        )
        self.assertEqual(res.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_can_delete_own_comment(self):
        comment = make_comment(self.task, self.owner)
        res = auth_client(self.owner).delete(COMMENT_DETAIL_URL(self.task.id, comment.id))
        self.assertEqual(res.status_code, http_status.HTTP_204_NO_CONTENT)

    def test_cannot_delete_others_comment(self):
        comment = make_comment(self.task, self.other)
        res = auth_client(self.owner).delete(COMMENT_DETAIL_URL(self.task.id, comment.id))
        self.assertEqual(res.status_code, http_status.HTTP_403_FORBIDDEN)


class BulkStatusTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.project = make_project(self.owner)
        self.t1 = make_task(self.project, self.owner)
        self.t2 = make_task(self.project, self.owner)
        self.client = auth_client(self.owner)

    def test_bulk_update_status(self):
        res = self.client.post(BULK_URL, {
            'task_ids': [str(self.t1.id), str(self.t2.id)],
            'status': 'done',
        }, format='json')
        self.assertEqual(res.status_code, http_status.HTTP_200_OK)
        self.assertEqual(res.json()['updated'], 2)
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t1.status, 'done')
        self.assertEqual(self.t2.status, 'done')

    def test_bulk_update_cannot_affect_others_tasks(self):
        stranger = make_user()
        other_project = make_project(stranger)
        other_task = make_task(other_project, stranger)
        res = self.client.post(BULK_URL, {
            'task_ids': [str(other_task.id)],
            'status': 'done',
        }, format='json')
        self.assertEqual(res.status_code, http_status.HTTP_200_OK)
        self.assertEqual(res.json()['updated'], 0)  # 0 tasks updated — leak blocked
        other_task.refresh_from_db()
        self.assertNotEqual(other_task.status, 'done')

    def test_bulk_update_invalid_status(self):
        res = self.client.post(BULK_URL, {
            'task_ids': [str(self.t1.id)],
            'status': 'flying',
        }, format='json')
        self.assertEqual(res.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_bulk_update_empty_list(self):
        res = self.client.post(BULK_URL, {'task_ids': [], 'status': 'done'}, format='json')
        self.assertEqual(res.status_code, http_status.HTTP_400_BAD_REQUEST)


class MyTasksTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user()
        self.project = make_project(self.user)
        add_member(self.project, self.other)
        self.mine = make_task(self.project, self.user, assignee=self.user)
        self.not_mine = make_task(self.project, self.user, assignee=self.other)
        self.client = auth_client(self.user)

    def test_my_tasks_only_returns_mine(self):
        res = self.client.get(MY_TASKS_URL)
        self.assertEqual(res.status_code, http_status.HTTP_200_OK)
        ids = [t['id'] for t in res.json()['results']]
        self.assertIn(str(self.mine.id), ids)
        self.assertNotIn(str(self.not_mine.id), ids)

    def test_my_tasks_status_filter(self):
        done_task = make_task(self.project, self.user, assignee=self.user, status='done')
        res = self.client.get(MY_TASKS_URL + '?status=done')
        ids = [t['id'] for t in res.json()['results']]
        self.assertIn(str(done_task.id), ids)
        self.assertNotIn(str(self.mine.id), ids)


class ActivityLogTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.project = make_project(self.owner)
        self.task = make_task(self.project, self.owner)
        self.client = auth_client(self.owner)

    def test_activity_log_created_on_task_create(self):
        from apps.tasks.models import TaskActivity
        # Activity logging happens in TaskSerializer.create(), which only runs
        # via the API — make_task() creates the Task directly via the ORM in
        # setUp() and bypasses it. Create through the client instead so this
        # actually exercises the real creation path.
        res = self.client.post(LIST_URL, {
            'project': str(self.project.id), 'title': 'Logged task',
        }, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertTrue(
            TaskActivity.objects.filter(task_id=res.json()['id'], verb='created task').exists()
        )

    def test_activity_log_on_status_change(self):
        from apps.tasks.models import TaskActivity
        self.client.patch(DETAIL_URL(self.task.id), {'status': 'in_progress'}, format='json')
        self.assertTrue(
            TaskActivity.objects.filter(task=self.task, verb='updated task').exists()
        )

    def test_activity_endpoint_returns_log(self):
        self.client.patch(DETAIL_URL(self.task.id), {'status': 'done'}, format='json')
        res = self.client.get(ACTIVITY_URL(self.task.id))
        self.assertEqual(res.status_code, http_status.HTTP_200_OK)
        self.assertGreaterEqual(len(res.json()), 1)

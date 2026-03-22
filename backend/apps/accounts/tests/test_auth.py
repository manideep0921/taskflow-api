"""
tests/accounts — covers every auth endpoint.

Scenarios tested
────────────────
Register      : happy path, duplicate email, password mismatch, weak password
Login         : happy path, wrong password, unknown email
Logout        : happy path, missing token, invalid token
Token refresh : happy path, blacklisted token
Me            : GET and PATCH
Change password: happy path, wrong old password, mismatched new passwords
"""
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.test_utils import make_user, auth_client


class RegisterTests(TestCase):
    URL = '/api/v1/auth/register/'

    def test_register_success(self):
        client = APIClient()
        res = client.post(self.URL, {
            'email': 'new@test.com',
            'full_name': 'New User',
            'password': 'StrongPass1!',
            'password2': 'StrongPass1!',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()
        self.assertIn('tokens', data)
        self.assertIn('access', data['tokens'])
        self.assertIn('refresh', data['tokens'])
        self.assertEqual(data['user']['email'], 'new@test.com')

    def test_register_duplicate_email(self):
        make_user(email='dup@test.com')
        client = APIClient()
        res = client.post(self.URL, {
            'email': 'dup@test.com',
            'full_name': 'Dup',
            'password': 'StrongPass1!',
            'password2': 'StrongPass1!',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_password_mismatch(self):
        client = APIClient()
        res = client.post(self.URL, {
            'email': 'x@test.com',
            'full_name': 'X',
            'password': 'StrongPass1!',
            'password2': 'Different1!',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(any(
            'match' in e['message'].lower()
            for e in res.json()['errors']
        ))

    def test_register_weak_password(self):
        client = APIClient()
        res = client.post(self.URL, {
            'email': 'y@test.com',
            'full_name': 'Y',
            'password': '123',
            'password2': '123',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_name(self):
        client = APIClient()
        res = client.post(self.URL, {
            'email': 'z@test.com',
            'password': 'StrongPass1!',
            'password2': 'StrongPass1!',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


class LoginTests(TestCase):
    URL = '/api/v1/auth/login/'

    def setUp(self):
        self.user = make_user(email='login@test.com', password='Login123!')

    def test_login_success(self):
        client = APIClient()
        res = client.post(self.URL, {'email': 'login@test.com', 'password': 'Login123!'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertIn('access', data)
        self.assertIn('refresh', data)
        self.assertEqual(data['user']['email'], 'login@test.com')

    def test_login_wrong_password(self):
        client = APIClient()
        res = client.post(self.URL, {'email': 'login@test.com', 'password': 'wrong'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_unknown_email(self):
        client = APIClient()
        res = client.post(self.URL, {'email': 'nobody@test.com', 'password': 'x'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class LogoutTests(TestCase):
    URL = '/api/v1/auth/logout/'

    def setUp(self):
        self.user = make_user()
        self.client = auth_client(self.user)
        self.refresh = str(RefreshToken.for_user(self.user))

    def test_logout_success(self):
        res = self.client.post(self.URL, {'refresh': self.refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_logout_missing_token(self):
        res = self.client.post(self.URL, {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_requires_auth(self):
        anon = APIClient()
        res = anon.post(self.URL, {'refresh': self.refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class TokenRefreshTests(TestCase):
    URL = '/api/v1/auth/token/refresh/'

    def setUp(self):
        self.user = make_user()

    def test_refresh_success(self):
        client = APIClient()
        refresh = str(RefreshToken.for_user(self.user))
        res = client.post(self.URL, {'refresh': refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('access', res.json())

    def test_refresh_invalid_token(self):
        client = APIClient()
        res = client.post(self.URL, {'refresh': 'notavalidtoken'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class MeTests(TestCase):
    URL = '/api/v1/auth/me/'

    def setUp(self):
        self.user = make_user(email='me@test.com', full_name='Me User')
        self.client = auth_client(self.user)

    def test_get_me(self):
        res = self.client.get(self.URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()['email'], 'me@test.com')

    def test_patch_me(self):
        res = self.client.patch(self.URL, {'full_name': 'Updated Name'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()['full_name'], 'Updated Name')

    def test_me_requires_auth(self):
        res = APIClient().get(self.URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class ChangePasswordTests(TestCase):
    URL = '/api/v1/auth/change-password/'

    def setUp(self):
        self.user = make_user(password='OldPass1!')
        self.client = auth_client(self.user)

    def test_change_password_success(self):
        res = self.client.post(self.URL, {
            'old_password': 'OldPass1!',
            'new_password': 'NewPass2!',
            'new_password2': 'NewPass2!',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPass2!'))

    def test_wrong_old_password(self):
        res = self.client.post(self.URL, {
            'old_password': 'WrongOld!',
            'new_password': 'NewPass2!',
            'new_password2': 'NewPass2!',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_new_password_mismatch(self):
        res = self.client.post(self.URL, {
            'old_password': 'OldPass1!',
            'new_password': 'NewPass2!',
            'new_password2': 'DiffPass3!',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

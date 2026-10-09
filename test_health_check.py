import unittest
from app import create_app

class HealthCheckTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_index_returns_200(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def test_auth_role_owner_returns_200(self):
        response = self.client.get('/auth/role/owner')
        self.assertEqual(response.status_code, 200)

    def test_notices_redirects_without_login(self):
        response = self.client.get('/notices')
        self.assertIn(response.status_code, (302, 308))

    def test_admin_notices_requires_login(self):
        response = self.client.get('/admin/notices')
        self.assertIn(response.status_code, (302, 401))

    def test_owner_residents_requires_login(self):
        response = self.client.get('/owner/residents')
        self.assertIn(response.status_code, (302, 401))

if __name__ == '__main__':
    unittest.main()

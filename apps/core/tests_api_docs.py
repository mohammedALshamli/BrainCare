from django.test import Client, SimpleTestCase


class ApiDocumentationTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()

    def test_schema_is_public_and_contains_core_paths(self):
        response = self.client.get("/api/schema/")
        self.assertEqual(response.status_code, 200)
        schema = response.content.decode()
        for path in (
            "/api/v1/auth/login/",
            "/api/v1/medications/",
            "/api/v1/water/intake/",
            "/api/v1/sync/changes/",
        ):
            self.assertIn(path, schema)
        self.assertIn("jwtAuth", schema)

    def test_swagger_ui_is_public(self):
        response = self.client.get("/api/docs/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Swagger", response.content.decode())

    def test_admin_is_not_documented_when_disabled(self):
        response = self.client.get("/api/schema/")
        self.assertNotIn("/admin/", response.content.decode())

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import store
import config


class ImportIdentityTests(unittest.TestCase):
    def test_host_defaults_to_localhost(self):
        self.assertEqual(config.HOST, "127.0.0.1")

    def test_missing_url_uses_synthetic_md(self):
        from backend.app.main import _resolve_import_identity

        url, kind = _resolve_import_identity(None, None)
        self.assertTrue(url.startswith("que://md/"))
        self.assertEqual(len(url), len("que://md/") + 32)
        self.assertEqual(kind, "md")

    def test_http_url_detects_kind(self):
        from backend.app.main import _resolve_import_identity

        url, kind = _resolve_import_identity("https://www.youtube.com/watch?v=abc", None)
        self.assertEqual(url, "https://www.youtube.com/watch?v=abc")
        self.assertEqual(kind, "youtube")

    def test_kind_override_and_rejects_non_http(self):
        from backend.app.main import _resolve_import_identity

        url, kind = _resolve_import_identity("https://example.com/x", "web")
        self.assertEqual(kind, "web")
        with self.assertRaises(ValueError):
            _resolve_import_identity("ftp://example.com/x", None)
        with self.assertRaises(ValueError):
            _resolve_import_identity(None, "pdf")


class ImportStoreTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = path
        self._orig = store.DB_PATH
        store.DB_PATH = Path(path)
        store.init_db()

    def tearDown(self):
        store.DB_PATH = self._orig
        os.unlink(self.db_path)

    def test_stores_markdown_verbatim_and_always_inserts(self):
        body = "---\ntitle: \"Kept\"\n---\n\n# Hello\n\n> [!quote]\n> keep me\n"
        first = store.add_imported_item(
            url="https://example.com/note",
            kind="web",
            title="Hello",
            markdown=body,
            author="Ada",
        )
        second = store.add_imported_item(
            url="https://example.com/note",
            kind="web",
            title="Hello again",
            markdown=body,
        )
        self.assertNotEqual(first, second)
        row = store.get_item(first)
        self.assertEqual(row["status"], "extracted")
        self.assertEqual(row["markdown"], body)
        self.assertEqual(row["title"], "Hello")
        self.assertEqual(row["author"], "Ada")
        self.assertTrue(row["share_code"])
        self.assertEqual(store.get_item(second)["title"], "Hello again")


class ImportApiTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = path
        self._orig_db = store.DB_PATH
        store.DB_PATH = Path(path)
        store.init_db()

        import backend.app.main as appmod
        from fastapi.testclient import TestClient

        self.appmod = appmod
        self._token = appmod._API_TOKEN
        appmod._API_TOKEN = "test-token"
        self.client = TestClient(appmod.app)

    def tearDown(self):
        self.client.close()
        self.appmod._API_TOKEN = self._token
        store.DB_PATH = self._orig_db
        os.unlink(self.db_path)

    def test_v1_import_and_auth(self):
        payload = {
            "title": "Imported note",
            "markdown": "# Keep\n\nverbatim body\n",
        }
        denied = self.client.post("/api/v1/items", json=payload)
        self.assertEqual(denied.status_code, 401)

        created = self.client.post(
            "/api/v1/items",
            json=payload,
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(created.status_code, 201)
        data = created.json()
        self.assertEqual(data["status"], "extracted")
        self.assertEqual(data["kind"], "md")
        self.assertTrue(data["url"].startswith("que://md/"))
        row = store.get_item(data["id"])
        self.assertEqual(row["markdown"], payload["markdown"])
        self.assertEqual(row["title"], "Imported note")

        session_import = self.client.post("/api/items/import", json=payload)
        self.assertEqual(session_import.status_code, 201)

    def test_import_validation(self):
        headers = {"Authorization": "Bearer test-token"}
        empty = self.client.post(
            "/api/v1/items",
            json={"title": "X", "markdown": "   "},
            headers=headers,
        )
        self.assertEqual(empty.status_code, 400)
        no_title = self.client.post(
            "/api/v1/items",
            json={"title": "  ", "markdown": "body"},
            headers=headers,
        )
        self.assertEqual(no_title.status_code, 400)

        with patch.object(self.appmod, "MAX_IMPORT_BYTES", 8):
            too_big = self.client.post(
                "/api/v1/items",
                json={"title": "X", "markdown": "0123456789"},
                headers=headers,
            )
        self.assertEqual(too_big.status_code, 400)

    def test_source_host_blank_for_synthetic_url(self):
        import legacy_main as legacy

        self.assertEqual(legacy._source_host("que://md/abcd"), "")
        self.assertEqual(legacy._source_host("https://www.example.com/x"), "example.com")
        self.assertEqual(legacy._kind_label("md"), "Markdown")

    def test_list_response_includes_total_count(self):
        store.add_imported_item(
            url="que://md/one",
            kind="md",
            title="One",
            markdown="# One\n",
        )
        store.add_imported_item(
            url="que://md/two",
            kind="md",
            title="Two",
            markdown="# Two\n",
        )
        response = self.client.get("/api/items?limit=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_count"], 2)

    def test_translation_api_is_temporarily_disabled(self):
        import backend.app.main as appmod

        item_id = store.add_imported_item(
            url="que://md/translation-disabled",
            kind="md",
            title="No translation",
            markdown="# Original\n",
        )
        self.assertEqual(self.client.post(f"/api/items/{item_id}/translate").status_code, 410)
        self.assertEqual(self.client.get(f"/api/items/{item_id}/translate").status_code, 410)

        detail = self.client.get(f"/api/items/{item_id}?view=ko")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["body"]["view"], "orig")
        self.assertNotIn("translation", detail.json())


if __name__ == "__main__":
    unittest.main()

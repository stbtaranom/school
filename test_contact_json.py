import json
import tempfile
import unittest
from pathlib import Path

from app import app


class ContactJsonStorageTests(unittest.TestCase):
    def test_contact_is_appended_to_json_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "contacts.json"
            app.config["CONTACTS_JSON_PATH"] = str(json_path)
            app.config.update(TESTING=True)

            response = app.test_client().post(
                "/api/contact",
                json={
                    "name": "علی آزمون",
                    "phone": "09120000000",
                    "subject": "تست ثبت اطلاعات",
                    "message": "این پیام باید در فایل JSON ذخیره شود.",
                },
            )

            self.assertEqual(response.status_code, 201)
            self.assertTrue(json_path.exists())

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["name"], "علی آزمون")
            self.assertEqual(payload[0]["subject"], "تست ثبت اطلاعات")


if __name__ == "__main__":
    unittest.main()

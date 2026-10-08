import importlib
import os
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import check_password_hash


class StudentAreaTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db = Path(self.temp_dir.name) / "school.db"
        os.environ["SQLITE_PATH"] = str(self.temp_db)
        os.environ["CONTACTS_JSON_PATH"] = str(Path(self.temp_dir.name) / "contacts.json")
        os.environ["STUDENT_DEMO_PASSWORD"] = "student123"
        import app as app_module

        self.app_module = importlib.reload(app_module)
        self.client = self.app_module.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_student_can_login_and_view_only_own_grades(self):
        login_page = self.client.get("/student/login")
        self.assertEqual(login_page.status_code, 200)
        csrf_token = self.client.get("/student/login").data.decode("utf-8").split('name="csrf_token" value="')[1].split('"')[0]

        response = self.client.post(
            "/student/login",
            data={"student_number": "1001", "password": "student123", "csrf_token": csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("داشبورد دانش‌آموز", response.get_data(as_text=True))

        grades = self.client.get("/student/grades")
        self.assertEqual(grades.status_code, 200)
        self.assertIn("ریاضی", grades.get_data(as_text=True))
        self.assertIn("90", grades.get_data(as_text=True))

        response = self.client.get("/student/quiz/1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("۳ × ۲ چند می‌شود؟", response.get_data(as_text=True))

        quiz_token = response.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        submission = self.client.post(
            "/student/quiz/1",
            data={"answer_1": "۶", "answer_2": "۳", "csrf_token": quiz_token},
            follow_redirects=True,
        )
        self.assertEqual(submission.status_code, 200)
        self.assertIn("نتیجه آزمون", submission.get_data(as_text=True))
        self.assertIn("2 از 2", submission.get_data(as_text=True))

        with self.app_module.get_db() as connection:
            row = self.app_module.execute(connection, "SELECT * FROM student_quiz_attempts WHERE student_id = 1 AND quiz_id = 1").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["score"], 2)

        self.assertTrue(check_password_hash(self.app_module.get_student_password_hash("1001"), "student123"))

    def test_student_cannot_access_other_student_data(self):
        login_page = self.client.get("/student/login")
        login_token = login_page.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        self.client.post("/student/login", data={"student_number": "1001", "password": "student123", "csrf_token": login_token}, follow_redirects=False)
        unauthorized = self.client.get("/student/profile/2")
        self.assertEqual(unauthorized.status_code, 403)

        quiz = self.client.get("/student/quiz/2")
        self.assertEqual(quiz.status_code, 403)


if __name__ == "__main__":
    unittest.main()

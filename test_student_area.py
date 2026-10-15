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
        os.environ["TEACHER_USERNAME"] = "teacher-test"
        os.environ["TEACHER_PASSWORD"] = "teacher-pass-test"
        os.environ["TEACHER_NAME"] = "دبیر آزمایشی"
        os.environ["TEACHER_INVITE_CODE"] = "school-invite-test"
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

    def test_student_can_view_full_exam_history_and_attempt_details(self):
        login_page = self.client.get("/student/login")
        csrf_token = login_page.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        self.client.post("/student/login", data={"student_number": "1001", "password": "student123", "csrf_token": csrf_token}, follow_redirects=True)

        history = self.client.get("/student/history")
        self.assertEqual(history.status_code, 200)
        self.assertIn("سابقه آزمون‌ها", history.get_data(as_text=True))

        quiz_page = self.client.get("/student/quiz/1")
        quiz_token = quiz_page.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        result = self.client.post(
            "/student/quiz/1",
            data={"answer_1": "۶", "answer_2": "۳", "csrf_token": quiz_token},
            follow_redirects=False,
        )
        attempt_id = result.headers.get("Location").split("/")[-1]
        attempt = self.client.get(f"/student/attempts/{attempt_id}")
        self.assertEqual(attempt.status_code, 200)
        self.assertIn("۶", attempt.get_data(as_text=True))
        self.assertIn("نتیجه آزمون", attempt.get_data(as_text=True))

        other_student = self.client.get(f"/student/attempts/{int(attempt_id) + 100}")
        self.assertEqual(other_student.status_code, 404)

    def test_student_cannot_access_other_student_data(self):
        login_page = self.client.get("/student/login")
        login_token = login_page.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        self.client.post("/student/login", data={"student_number": "1001", "password": "student123", "csrf_token": login_token}, follow_redirects=False)
        unauthorized = self.client.get("/student/profile/2")
        self.assertEqual(unauthorized.status_code, 403)

        quiz = self.client.get("/student/quiz/2")
        self.assertEqual(quiz.status_code, 403)

    def test_teacher_can_grade_class_and_publish_quiz_for_students(self):
        login_page = self.client.get("/teacher/login")
        self.assertEqual(login_page.status_code, 200)
        teacher_token = login_page.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        self.client.post("/teacher/login", data={
            "username": "teacher-test",
            "password": "teacher-pass-test",
            "csrf_token": teacher_token,
        }, follow_redirects=True)

        teacher_page = self.client.get("/teacher")
        self.assertEqual(teacher_page.status_code, 200)
        self.assertIn("فاطمه رضایی", teacher_page.get_data(as_text=True))
        teacher_token = teacher_page.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        grade_response = self.client.post("/teacher", data={
            "csrf_token": teacher_token,
            "action": "grade",
            "class_name": "پایه دهم - علوم",
            "student_id": "1",
            "course_name": "ریاضی",
            "score": "18",
            "total_score": "20",
            "activity": "تکلیف آزمایشی",
        })
        self.assertEqual(grade_response.status_code, 302)
        invalid_grade = self.client.post("/teacher", data={
            "csrf_token": teacher_token,
            "action": "grade",
            "class_name": "پایه دهم - علوم",
            "student_id": "1",
            "course_name": "ریاضی",
            "score": "21",
            "total_score": "20",
            "activity": "نمره نامعتبر",
        })
        self.assertEqual(invalid_grade.status_code, 400)
        wrong_class_grade = self.client.post("/teacher", data={
            "csrf_token": teacher_token,
            "action": "grade",
            "class_name": "کلاس اشتباه",
            "student_id": "1",
            "course_name": "ریاضی",
            "score": "18",
            "total_score": "20",
            "activity": "تلاش نامعتبر",
        })
        self.assertEqual(wrong_class_grade.status_code, 404)

        quiz_response = self.client.post("/teacher", data={
            "csrf_token": teacher_token,
            "action": "quiz",
            "class_name": "پایه دهم - علوم",
            "title": "آزمون کلاسی آزمایشی",
            "course_name": "علوم",
            "description": "آزمون ساخته‌شده توسط دبیر",
            "question_text": ["آب در چند درجه می‌جوشد؟", "زمین به دور چه می‌چرخد؟"],
            "options_0": ["100", "50"],
            "options_1": ["خورشید", "ماه"],
            "correct_answer": ["100", "خورشید"],
        })
        self.assertEqual(quiz_response.status_code, 302)

        self.client.post("/teacher/logout", data={"csrf_token": teacher_token})
        student_login = self.client.get("/student/login")
        student_token = student_login.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        dashboard = self.client.post("/student/login", data={
            "student_number": "1001",
            "password": "student123",
            "csrf_token": student_token,
        }, follow_redirects=True)
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("آزمون کلاسی آزمایشی", dashboard.get_data(as_text=True))
        self.assertIn("تکلیف آزمایشی", self.client.get("/student/grades").get_data(as_text=True))

        with self.app_module.get_db() as connection:
            quiz = self.app_module.execute(connection, "SELECT id FROM quizzes WHERE title = ?", ("آزمون کلاسی آزمایشی",)).fetchone()
        quiz_page = self.client.get(f"/student/quiz/{quiz['id']}")
        self.assertEqual(quiz_page.status_code, 200)
        self.assertIn("آب در چند درجه می‌جوشد؟", quiz_page.get_data(as_text=True))

    def test_student_can_create_account_and_login_with_chosen_username(self):
        registration = self.client.get("/student/register")
        self.assertEqual(registration.status_code, 200)
        csrf_token = registration.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        created = self.client.post("/student/register", data={
            "csrf_token": csrf_token,
            "student_number": "1002",
            "current_password": "student456",
            "username": "zahra.student",
            "password": "new-student-pass",
            "password_confirmation": "new-student-pass",
        }, follow_redirects=True)
        self.assertEqual(created.status_code, 200)
        self.assertIn("زهرا محمدی", created.get_data(as_text=True))

        self.client.post("/student/logout", data={"csrf_token": self.client.get("/student").get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]})
        login_page = self.client.get("/student/login")
        login_token = login_page.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        logged_in = self.client.post("/student/login", data={
            "csrf_token": login_token,
            "username": "zahra.student",
            "password": "new-student-pass",
        }, follow_redirects=True)
        self.assertEqual(logged_in.status_code, 200)
        self.assertIn("داشبورد دانش‌آموز", logged_in.get_data(as_text=True))
        with self.app_module.get_db() as connection:
            student = self.app_module.execute(connection, "SELECT username, password_hash FROM students WHERE student_number = ?", ("1002",)).fetchone()
        self.assertEqual(student["username"], "zahra.student")
        self.assertTrue(check_password_hash(student["password_hash"], "new-student-pass"))

    def test_teacher_can_register_with_invite_and_login_later(self):
        registration = self.client.get("/teacher/register")
        self.assertEqual(registration.status_code, 200)
        csrf_token = registration.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        created = self.client.post("/teacher/register", data={
            "csrf_token": csrf_token,
            "name": "معلم جدید",
            "username": "new.teacher",
            "password": "new-teacher-pass",
            "password_confirmation": "new-teacher-pass",
            "invite_code": "school-invite-test",
        }, follow_redirects=True)
        self.assertEqual(created.status_code, 200)
        self.assertIn("معلم جدید", created.get_data(as_text=True))
        dashboard = created.get_data(as_text=True)
        logout_token = dashboard.split('name="csrf_token" value="')[1].split('"')[0]
        self.client.post("/teacher/logout", data={"csrf_token": logout_token})

        login_page = self.client.get("/teacher/login")
        login_token = login_page.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
        logged_in = self.client.post("/teacher/login", data={
            "csrf_token": login_token,
            "username": "new.teacher",
            "password": "new-teacher-pass",
        }, follow_redirects=True)
        self.assertEqual(logged_in.status_code, 200)
        self.assertIn("سلام، معلم جدید", logged_in.get_data(as_text=True))
        with self.app_module.get_db() as connection:
            teacher = self.app_module.execute(connection, "SELECT password_hash FROM teachers WHERE username = ?", ("new.teacher",)).fetchone()
        self.assertTrue(check_password_hash(teacher["password_hash"], "new-teacher-pass"))


if __name__ == "__main__":
    unittest.main()

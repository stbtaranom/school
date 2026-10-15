from datetime import datetime
from contextlib import contextmanager
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SQLITE_PATH", BASE_DIR / "school.db"))
CONTACTS_JSON_PATH = Path(os.getenv("CONTACTS_JSON_PATH", BASE_DIR / "contacts.json"))
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
TEACHER_USERNAME = os.getenv("TEACHER_USERNAME", "")
TEACHER_PASSWORD = os.getenv("TEACHER_PASSWORD", "")
TEACHER_NAME = os.getenv("TEACHER_NAME", "معلم")
TEACHER_INVITE_CODE = os.getenv("TEACHER_INVITE_CODE", "")
app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    CONTACTS_JSON_PATH=str(CONTACTS_JSON_PATH),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "1" if os.getenv("RENDER") else "0") == "1",
    PERMANENT_SESSION_LIFETIME=3600,
)


@contextmanager
def get_db():
    if DATABASE_URL:
        import psycopg
        from psycopg.rows import dict_row

        database_url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        connection = psycopg.connect(database_url, row_factory=dict_row)
    else:
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def execute(connection, statement, parameters=()):
    if DATABASE_URL:
        statement = statement.replace("?", "%s")
    return connection.execute(statement, parameters)


def init_db():
    with get_db() as connection:
        identity_column = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
        execute(connection, f"""
            CREATE TABLE IF NOT EXISTS contacts (
                id {identity_column}, name TEXT NOT NULL, phone TEXT NOT NULL,
                subject TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
            )
            """)
        execute(connection, f"""
            CREATE TABLE IF NOT EXISTS notices (
                id {identity_column}, title TEXT NOT NULL, summary TEXT NOT NULL,
                category TEXT NOT NULL, date_text TEXT NOT NULL, created_at TEXT NOT NULL
            )
            """)
        execute(connection, f"""
            CREATE TABLE IF NOT EXISTS students (
                id {identity_column}, student_number TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL, password_hash TEXT NOT NULL, class_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """)
        execute(connection, f"""
            CREATE TABLE IF NOT EXISTS teachers (
                id {identity_column}, username TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL, password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """)
        if DATABASE_URL:
            execute(connection, "ALTER TABLE students ADD COLUMN IF NOT EXISTS username TEXT")
        else:
            try:
                execute(connection, "ALTER TABLE students ADD COLUMN username TEXT")
            except sqlite3.OperationalError:
                pass
        execute(connection, "CREATE UNIQUE INDEX IF NOT EXISTS students_username_unique ON students (username)")
        execute(connection, "CREATE UNIQUE INDEX IF NOT EXISTS teachers_username_lower_unique ON teachers (lower(username))")
        execute(connection, f"""
            CREATE TABLE IF NOT EXISTS student_grades (
                id {identity_column}, student_id INTEGER NOT NULL,
                course_name TEXT NOT NULL, score INTEGER NOT NULL,
                total_score INTEGER NOT NULL, term TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students (id)
            )
            """)
        execute(connection, f"""
            CREATE TABLE IF NOT EXISTS quizzes (
                id {identity_column}, title TEXT NOT NULL, course_name TEXT NOT NULL,
                description TEXT NOT NULL, questions TEXT NOT NULL,
                student_id INTEGER, created_at TEXT NOT NULL
            )
            """)
        if DATABASE_URL:
            execute(connection, "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS student_id INTEGER")
            execute(connection, "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS class_name TEXT")
        else:
            for statement in (
                "ALTER TABLE quizzes ADD COLUMN student_id INTEGER",
                "ALTER TABLE quizzes ADD COLUMN class_name TEXT",
            ):
                try:
                    execute(connection, statement)
                except sqlite3.OperationalError:
                    pass
        execute(connection, f"""
            CREATE TABLE IF NOT EXISTS student_quiz_attempts (
                id {identity_column}, student_id INTEGER NOT NULL, quiz_id INTEGER NOT NULL,
                answers TEXT NOT NULL, score INTEGER NOT NULL, total_score INTEGER NOT NULL,
                submitted_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students (id),
                FOREIGN KEY (quiz_id) REFERENCES quizzes (id)
            )
            """)
        if TEACHER_USERNAME and TEACHER_PASSWORD:
            teacher = execute(connection, "SELECT id FROM teachers WHERE username = ?", (TEACHER_USERNAME,)).fetchone()
            if teacher is None:
                execute(connection, "INSERT INTO teachers (username, name, password_hash, created_at) VALUES (?, ?, ?, ?)", (
                    TEACHER_USERNAME, TEACHER_NAME, generate_password_hash(TEACHER_PASSWORD), datetime.now().isoformat(),
                ))
        count = execute(connection, "SELECT COUNT(*) AS count FROM notices").fetchone()["count"] if DATABASE_URL else execute(connection, "SELECT COUNT(*) FROM notices").fetchone()[0]
        if count == 0:
            initial_notices = [
                ("آغاز ثبت‌نام کلاس‌های فوق‌برنامه", "جزئیات زمان‌بندی و نحوه ثبت‌نام کلاس‌های ترم پاییز را از این بخش دنبال کنید.", "اطلاعیه", "۲۲ مهر ۱۴۰۴", datetime.now().isoformat()),
                ("جشن آغاز سال تحصیلی جدید", "گزارش تصویری از اولین گردهمایی خانواده بزرگ شاهد فاطمیه.", "رویداد", "۱۵ مهر ۱۴۰۴", datetime.now().isoformat()),
                ("برنامه جلسات اولیا و مربیان", "زمان‌بندی جلسات آشنایی خانواده‌ها با دبیران و کادر آموزشی اعلام شد.", "اطلاعیه", "۰۸ مهر ۱۴۰۴", datetime.now().isoformat()),
                ("بازدید علمی از مرکز نوآوری", "دانش‌آموزان پایه دهم در یک بازدید علمی با دنیای فناوری آشنا شدند.", "رویداد", "۲۹ شهریور ۱۴۰۴", datetime.now().isoformat()),
            ]
            for notice in initial_notices:
                execute(connection, "INSERT INTO notices (title, summary, category, date_text, created_at) VALUES (?, ?, ?, ?, ?)", notice)

        student_count = execute(connection, "SELECT COUNT(*) AS count FROM students").fetchone()["count"] if DATABASE_URL else execute(connection, "SELECT COUNT(*) FROM students").fetchone()[0]
        if student_count == 0:
            student_password = os.getenv("STUDENT_DEMO_PASSWORD", "student123")
            student_hash = generate_password_hash(student_password)
            execute(connection, "INSERT INTO students (student_number, name, password_hash, class_name, created_at) VALUES (?, ?, ?, ?, ?)", (
                "1001", "فاطمه رضایی", student_hash, "پایه دهم - علوم", datetime.now().isoformat(),
            ))
            execute(connection, "INSERT INTO students (student_number, name, password_hash, class_name, created_at) VALUES (?, ?, ?, ?, ?)", (
                "1002", "زهرا محمدی", generate_password_hash("student456"), "پایه دهم - علوم", datetime.now().isoformat(),
            ))

            execute(connection, "INSERT INTO student_grades (student_id, course_name, score, total_score, term, created_at) VALUES (?, ?, ?, ?, ?, ?)", (1, "ریاضی", 90, 100, "ترم اول", datetime.now().isoformat()))
            execute(connection, "INSERT INTO student_grades (student_id, course_name, score, total_score, term, created_at) VALUES (?, ?, ?, ?, ?, ?)", (1, "علوم", 88, 100, "ترم اول", datetime.now().isoformat()))
            execute(connection, "INSERT INTO student_grades (student_id, course_name, score, total_score, term, created_at) VALUES (?, ?, ?, ?, ?, ?)", (2, "ریاضی", 82, 100, "ترم اول", datetime.now().isoformat()))

            quiz_questions = json.dumps([{"id": 1, "question": "۳ × ۲ چند می‌شود؟", "options": ["۱", "۳", "۴", "۶"], "answer": "۶"}, {"id": 2, "question": "مقدار عددی ۲ + ۱ چند است؟", "options": ["۱", "۲", "۳", "۴"], "answer": "۳"}])
            execute(connection, "INSERT INTO quizzes (title, course_name, description, questions, student_id, created_at) VALUES (?, ?, ?, ?, ?, ?)", (
                "آزمون کوتاه ریاضی", "ریاضی", "دو سوال کوتاه از فصل ضرب و جمع", quiz_questions, 1, datetime.now().isoformat(),
            ))
            execute(connection, "INSERT INTO quizzes (title, course_name, description, questions, student_id, created_at) VALUES (?, ?, ?, ?, ?, ?)", (
                "آزمون آزمایشی", "فیزیک", "این آزمون فقط برای دانش‌آموز شماره 1002 در دسترس است.", json.dumps([]), 2, datetime.now().isoformat(),
            ))


init_db()


@app.get("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/api/notices")
def notices():
    category = request.args.get("category")
    with get_db() as connection:
        if category and category != "all":
            rows = execute(connection,
                "SELECT id, title, summary, category, date_text FROM notices WHERE category = ? ORDER BY id DESC",
                (category,),
            ).fetchall()
        else:
            rows = execute(connection,
                "SELECT id, title, summary, category, date_text FROM notices ORDER BY id DESC"
            ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/contact")
def create_contact():
    payload = request.get_json(silent=True) or request.form
    fields = {key: str(payload.get(key, "")).strip() for key in ("name", "phone", "subject", "message")}
    if any(not value for value in fields.values()):
        return jsonify({"ok": False, "message": "لطفاً همه فیلدهای ضروری را کامل کنید."}), 400

    record = {
        "name": fields["name"],
        "phone": fields["phone"],
        "subject": fields["subject"],
        "message": fields["message"],
        "created_at": datetime.now().isoformat(),
    }
    json_path = Path(app.config["CONTACTS_JSON_PATH"])
    json_path.parent.mkdir(parents=True, exist_ok=True)
    if json_path.exists():
        with json_path.open("r", encoding="utf-8") as file:
            records = json.load(file)
        if not isinstance(records, list):
            records = []
    else:
        records = []
    records.append(record)
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)

    with get_db() as connection:
        execute(connection,
            "INSERT INTO contacts (name, phone, subject, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (*fields.values(), datetime.now().isoformat()),
        )
    return jsonify({"ok": True, "message": "پیام شما با موفقیت ثبت شد."}), 201


def valid_csrf_token():
    submitted_token = request.form.get("csrf_token", "")
    stored_token = session.get("csrf_token", "")
    return bool(stored_token and hmac.compare_digest(submitted_token, stored_token))


def get_student_password_hash(student_number):
    with get_db() as connection:
        row = execute(connection, "SELECT password_hash FROM students WHERE student_number = ?", (student_number,)).fetchone()
        if row is None:
            return None
        return row["password_hash"] if DATABASE_URL else row[0]


def student_required():
    if not session.get("student_id"):
        return redirect(url_for("student_login"))
    return None


def teacher_required():
    if not session.get("teacher_id"):
        return redirect(url_for("teacher_login"))
    return None


@app.route("/teacher/login", methods=["GET", "POST"])
def teacher_login():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    error = None
    if request.method == "POST":
        if not valid_csrf_token():
            abort(400, "درخواست نامعتبر است. صفحه را تازه کنید و دوباره تلاش کنید.")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with get_db() as connection:
            teacher = execute(connection, "SELECT id, name, password_hash FROM teachers WHERE username = ?", (username,)).fetchone()
        if teacher and check_password_hash(teacher["password_hash"], password):
            session.clear()
            session["teacher_id"] = teacher["id"]
            session["teacher_name"] = teacher["name"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = True
            return redirect(url_for("teacher_dashboard"))
        error = "نام کاربری یا رمز عبور درست نیست."
    return render_template("teacher_login.html", csrf_token=session["csrf_token"], error=error)


def valid_account_fields(username, password):
    return bool(
        re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{2,39}", username)
        and len(password) >= 8
    )


@app.route("/student/register", methods=["GET", "POST"])
def student_register():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    error = None
    if request.method == "POST":
        if not valid_csrf_token():
            abort(400, "درخواست نامعتبر است. صفحه را تازه کنید و دوباره تلاش کنید.")
        student_number = request.form.get("student_number", "").strip()
        current_password = request.form.get("current_password", "")
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        password_confirmation = request.form.get("password_confirmation", "")
        if not valid_account_fields(username, password):
            error = "نام کاربری باید با حرف انگلیسی شروع شود و ۳ تا ۴۰ نویسه باشد؛ رمز باید دست‌کم ۸ نویسه داشته باشد."
        elif password != password_confirmation:
            error = "تکرار رمز عبور یکسان نیست."
        else:
            with get_db() as connection:
                student = execute(connection, "SELECT id, password_hash, username FROM students WHERE student_number = ?", (student_number,)).fetchone()
                username_exists = execute(connection, "SELECT id FROM students WHERE lower(username) = ? OR student_number = ?", (username, username)).fetchone()
                if student is None or not check_password_hash(student["password_hash"], current_password):
                    error = "شماره دانش‌آموزی یا رمز فعلی معتبر نیست."
                elif student["username"]:
                    error = "برای این دانش‌آموز قبلاً حساب کاربری ساخته شده است."
                elif username_exists:
                    error = "این نام کاربری قبلاً انتخاب شده است."
                else:
                    execute(connection, "UPDATE students SET username = ?, password_hash = ? WHERE id = ?", (
                        username, generate_password_hash(password), student["id"],
                    ))
                    session.clear()
                    session["student_id"] = student["id"]
                    session["student_name"] = execute(connection, "SELECT name FROM students WHERE id = ?", (student["id"],)).fetchone()["name"]
                    session["student_class"] = execute(connection, "SELECT class_name FROM students WHERE id = ?", (student["id"],)).fetchone()["class_name"]
                    session["csrf_token"] = secrets.token_urlsafe(32)
                    session.permanent = True
                    return redirect(url_for("student_dashboard"))
    return render_template("student_register.html", csrf_token=session["csrf_token"], error=error)


@app.route("/teacher/register", methods=["GET", "POST"])
def teacher_register():
    if not TEACHER_INVITE_CODE:
        abort(503, "ثبت‌نام معلم فعال نیست؛ مدیر سامانه باید کد دعوت را تنظیم کند.")
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    error = None
    if request.method == "POST":
        if not valid_csrf_token():
            abort(400, "درخواست نامعتبر است. صفحه را تازه کنید و دوباره تلاش کنید.")
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        password_confirmation = request.form.get("password_confirmation", "")
        invite_code = request.form.get("invite_code", "")
        if not hmac.compare_digest(invite_code, TEACHER_INVITE_CODE):
            error = "کد دعوت معتبر نیست."
        elif not name or not valid_account_fields(username, password):
            error = "نام لازم است؛ نام کاربری باید ۳ تا ۴۰ نویسه انگلیسی و رمز دست‌کم ۸ نویسه باشد."
        elif password != password_confirmation:
            error = "تکرار رمز عبور یکسان نیست."
        else:
            with get_db() as connection:
                exists = execute(connection, "SELECT id FROM teachers WHERE lower(username) = ?", (username,)).fetchone()
                if exists:
                    error = "این نام کاربری قبلاً انتخاب شده است."
                else:
                    execute(connection, "INSERT INTO teachers (username, name, password_hash, created_at) VALUES (?, ?, ?, ?)", (
                        username, name, generate_password_hash(password), datetime.now().isoformat(),
                    ))
                    teacher = execute(connection, "SELECT id FROM teachers WHERE username = ?", (username,)).fetchone()
                    session.clear()
                    session["teacher_id"] = teacher["id"]
                    session["teacher_name"] = name
                    session["csrf_token"] = secrets.token_urlsafe(32)
                    session.permanent = True
                    return redirect(url_for("teacher_dashboard"))
    return render_template("teacher_register.html", csrf_token=session["csrf_token"], error=error)


@app.route("/teacher/logout", methods=["POST"])
def teacher_logout():
    if not valid_csrf_token():
        abort(400, "درخواست نامعتبر است. صفحه را تازه کنید.")
    session.clear()
    return redirect(url_for("teacher_login"))


@app.route("/teacher", methods=["GET", "POST"])
def teacher_dashboard():
    required = teacher_required()
    if required:
        return required
    if request.method == "POST":
        if not valid_csrf_token():
            abort(400, "درخواست نامعتبر است. صفحه را تازه کنید.")
        action = request.form.get("action", "")
        if action == "grade":
            try:
                student_id = int(request.form.get("student_id", ""))
                score = int(request.form.get("score", ""))
                total_score = int(request.form.get("total_score", ""))
            except ValueError:
                abort(400, "نمره واردشده معتبر نیست.")
            course_name = request.form.get("course_name", "").strip()
            activity = request.form.get("activity", "").strip()
            class_name = request.form.get("class_name", "").strip()
            if not course_name or not activity or not class_name or total_score <= 0 or score < 0 or score > total_score:
                abort(400, "اطلاعات نمره کامل یا معتبر نیست.")
            with get_db() as connection:
                student = execute(connection, "SELECT id FROM students WHERE id = ? AND class_name = ?", (student_id, class_name)).fetchone()
                if student is None:
                    abort(404, "دانش‌آموز در کلاس انتخاب‌شده پیدا نشد.")
                execute(connection, "INSERT INTO student_grades (student_id, course_name, score, total_score, term, created_at) VALUES (?, ?, ?, ?, ?, ?)", (
                    student_id, course_name, score, total_score, f"فعالیت: {activity}", datetime.now().isoformat(),
                ))
            return redirect(url_for("teacher_dashboard", class_name=class_name, saved="grade"))
        if action == "quiz":
            title = request.form.get("title", "").strip()
            course_name = request.form.get("course_name", "").strip()
            description = request.form.get("description", "").strip()
            class_name = request.form.get("class_name", "").strip()
            question_texts = request.form.getlist("question_text")
            option_groups = [request.form.getlist(f"options_{index}") for index in range(len(question_texts))]
            correct_answers = request.form.getlist("correct_answer")
            questions = []
            for index, question_text in enumerate(question_texts):
                options = [option.strip() for option in option_groups[index] if option.strip()]
                if not question_text.strip():
                    continue
                if len(options) < 2 or index >= len(correct_answers) or correct_answers[index] not in options:
                    abort(400, "برای هر سؤال دست‌کم دو گزینه و یک پاسخ درست تعیین کنید.")
                questions.append({"id": len(questions) + 1, "question": question_text.strip(), "options": options, "answer": correct_answers[index]})
            if not title or not course_name or not class_name or not questions:
                abort(400, "عنوان، درس، کلاس و دست‌کم یک سؤال لازم است.")
            with get_db() as connection:
                execute(connection, "INSERT INTO quizzes (title, course_name, description, questions, student_id, class_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (
                    title, course_name, description, json.dumps(questions, ensure_ascii=False), None, class_name, datetime.now().isoformat(),
                ))
            return redirect(url_for("teacher_dashboard", class_name=class_name, saved="quiz"))
        abort(400, "عملیات درخواست‌شده شناخته نشد.")

    with get_db() as connection:
        classes = [row["class_name"] for row in execute(connection, "SELECT DISTINCT class_name FROM students ORDER BY class_name").fetchall()]
        class_name = request.args.get("class_name", classes[0] if classes else "")
        if class_name not in classes:
            class_name = classes[0] if classes else ""
        students = execute(connection, "SELECT id, student_number, name, class_name FROM students WHERE class_name = ? ORDER BY name", (class_name,)).fetchall() if class_name else []
        grades = execute(connection, "SELECT g.student_id, s.name AS student_name, g.course_name, g.score, g.total_score, g.term, g.created_at FROM student_grades AS g JOIN students AS s ON s.id = g.student_id WHERE s.class_name = ? ORDER BY g.id DESC", (class_name,)).fetchall() if class_name else []
        attempts = execute(connection, "SELECT s.name AS student_name, q.title, q.course_name, a.score, a.total_score, a.submitted_at FROM student_quiz_attempts AS a JOIN students AS s ON s.id = a.student_id JOIN quizzes AS q ON q.id = a.quiz_id WHERE s.class_name = ? ORDER BY a.id DESC", (class_name,)).fetchall() if class_name else []
        quizzes = execute(connection, "SELECT id, title, course_name, created_at FROM quizzes WHERE class_name = ? ORDER BY id DESC", (class_name,)).fetchall() if class_name else []
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template("teacher_dashboard.html", teacher_name=session.get("teacher_name", TEACHER_NAME), classes=classes, class_name=class_name, students=students, grades=grades, attempts=attempts, quizzes=quizzes, csrf_token=session["csrf_token"], saved=request.args.get("saved"))


@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    error = None
    if request.method == "POST":
        if not valid_csrf_token():
            abort(400, "درخواست نامعتبر است. صفحه را تازه کنید و دوباره تلاش کنید.")
        username = request.form.get("username", request.form.get("student_number", "")).strip().lower()
        student_password = request.form.get("password", "")
        with get_db() as connection:
            row = execute(connection, "SELECT id, name, password_hash, class_name FROM students WHERE username = ?", (username,)).fetchone()
            if row is None:
                row = execute(connection, "SELECT id, name, password_hash, class_name FROM students WHERE username IS NULL AND student_number = ?", (username,)).fetchone()
        if row is not None:
            stored_hash = row["password_hash"] if DATABASE_URL else row[2]
            if check_password_hash(stored_hash, student_password):
                session.clear()
                session["student_id"] = row["id"] if DATABASE_URL else row[0]
                session["student_name"] = row["name"] if DATABASE_URL else row[1]
                session["student_class"] = row["class_name"] if DATABASE_URL else row[3]
                session.permanent = True
                return redirect(url_for("student_dashboard"))
        error = "شماره دانش‌آموزی یا رمز عبور اشتباه است."
    return render_template("student_login.html", csrf_token=session["csrf_token"], error=error)


@app.route("/student/logout", methods=["POST"])
def student_logout():
    if not valid_csrf_token():
        abort(400, "درخواست نامعتبر است. صفحه را تازه کنید.")
    session.clear()
    return redirect(url_for("student_login"))


@app.route("/student")
def student_dashboard():
    student_id = session.get("student_id")
    if not student_id:
        return redirect(url_for("student_login"))
    with get_db() as connection:
        student = execute(connection, "SELECT id, student_number, name, class_name FROM students WHERE id = ?", (student_id,)).fetchone()
        grades = execute(connection, "SELECT course_name, score, total_score, term FROM student_grades WHERE student_id = ? ORDER BY id DESC", (student_id,)).fetchall()
        attempts = execute(connection, "SELECT a.id AS attempt_id, q.title, q.course_name, a.score, a.total_score, a.submitted_at FROM student_quiz_attempts AS a JOIN quizzes AS q ON q.id = a.quiz_id WHERE a.student_id = ? ORDER BY a.id DESC", (student_id,)).fetchall()
        available_quizzes = execute(connection, "SELECT id, title, course_name, description FROM quizzes WHERE (student_id IS NULL AND (class_name IS NULL OR class_name = ?)) OR student_id = ? ORDER BY id DESC", (session.get("student_class", ""), student_id)).fetchall()
    if student is None:
        session.clear()
        return redirect(url_for("student_login"))
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template("student_dashboard.html", student=student, grades=grades, attempts=attempts, available_quizzes=available_quizzes, csrf_token=session["csrf_token"])


@app.route("/student/grades")
def student_grades():
    if not session.get("student_id"):
        return redirect(url_for("student_login"))
    with get_db() as connection:
        grades = execute(connection, "SELECT course_name, score, total_score, term FROM student_grades WHERE student_id = ? ORDER BY id DESC", (session["student_id"],)).fetchall()
    return render_template("student_grades.html", grades=grades)


@app.route("/student/profile/<int:student_id>")
def student_profile(student_id):
    if not session.get("student_id"):
        return redirect(url_for("student_login"))
    if student_id != session.get("student_id"):
        abort(403, "شما به اطلاعات دانش‌آموز دیگری دسترسی ندارید.")
    with get_db() as connection:
        student = execute(connection, "SELECT id, student_number, name, class_name FROM students WHERE id = ?", (student_id,)).fetchone()
    if student is None:
        abort(404, "دانش‌آموز موردنظر یافت نشد.")
    return render_template("student_profile.html", student=student)


@app.route("/student/quiz/<int:quiz_id>", methods=["GET", "POST"])
def student_quiz(quiz_id):
    if not session.get("student_id"):
        return redirect(url_for("student_login"))
    with get_db() as connection:
        quiz = execute(connection, "SELECT id, title, course_name, description, questions, student_id, class_name FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
        existing_attempt = execute(connection, "SELECT id FROM student_quiz_attempts WHERE student_id = ? AND quiz_id = ?", (session["student_id"], quiz_id)).fetchone()
    if quiz is None:
        abort(404, "آزمون موردنظر وجود ندارد.")
    if quiz["student_id"] not in (None, session["student_id"]) or (quiz["class_name"] and quiz["class_name"] != session.get("student_class")):
        abort(403, "شما به این آزمون دسترسی ندارید.")
    if existing_attempt:
        return redirect(url_for("student_dashboard"))
    questions = json.loads(quiz["questions"])
    if request.method == "POST":
        if not valid_csrf_token():
            abort(400, "درخواست نامعتبر است. صفحه را تازه کنید.")
        score = 0
        answers = {}
        for item in questions:
            answer = request.form.get(f"answer_{item['id']}", "")
            answers[str(item["id"])] = answer
            if answer == item["answer"]:
                score += 1
        with get_db() as connection:
            execute(connection, "INSERT INTO student_quiz_attempts (student_id, quiz_id, answers, score, total_score, submitted_at) VALUES (?, ?, ?, ?, ?, ?)", (
                session["student_id"], quiz_id, json.dumps(answers, ensure_ascii=False), score, len(questions), datetime.now().isoformat(),
            ))
            attempt = execute(connection, "SELECT id FROM student_quiz_attempts WHERE student_id = ? AND quiz_id = ? ORDER BY id DESC LIMIT 1", (session["student_id"], quiz_id)).fetchone()
        if attempt is None:
            abort(500, "نتیجه آزمون ثبت شد اما امکان مشاهده آن وجود ندارد.")
        return redirect(url_for("student_attempt", attempt_id=attempt["id"] if DATABASE_URL else attempt[0]))
    session["csrf_token"] = secrets.token_urlsafe(32)
    return render_template("student_quiz.html", quiz=quiz, questions=questions, csrf_token=session["csrf_token"])


@app.route("/student/history")
def student_history():
    if not session.get("student_id"):
        return redirect(url_for("student_login"))
    with get_db() as connection:
        attempts = execute(connection, "SELECT a.id AS attempt_id, q.title, q.course_name, a.score, a.total_score, a.submitted_at FROM student_quiz_attempts AS a JOIN quizzes AS q ON q.id = a.quiz_id WHERE a.student_id = ? ORDER BY a.id DESC", (session["student_id"],)).fetchall()
    return render_template("student_history.html", attempts=attempts)


@app.route("/student/attempts/<int:attempt_id>")
def student_attempt(attempt_id):
    if not session.get("student_id"):
        return redirect(url_for("student_login"))
    with get_db() as connection:
        attempt = execute(connection, "SELECT a.id, q.id AS quiz_id, q.title, q.course_name, q.questions, a.answers, a.score, a.total_score, a.submitted_at FROM student_quiz_attempts AS a JOIN quizzes AS q ON q.id = a.quiz_id WHERE a.id = ? AND a.student_id = ?", (attempt_id, session["student_id"])).fetchone()
    if attempt is None:
        abort(404, "تلاش آزمون موردنظر یافت نشد.")
    answers = json.loads(attempt["answers"] if DATABASE_URL else attempt["answers"])
    questions = json.loads(attempt["questions"])
    return render_template("student_attempt_detail.html", attempt=attempt, questions=questions, answers=answers)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not ADMIN_PASSWORD:
        abort(503, "برای فعال‌کردن پنل، متغیر ADMIN_PASSWORD را در تنظیمات سرویس تعیین کنید.")

    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    error = None
    if request.method == "POST":
        if not valid_csrf_token():
            abort(400, "درخواست نامعتبر است. صفحه را تازه کنید و دوباره تلاش کنید.")
        if hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session.clear()
            session["is_admin"] = True
            session.permanent = True
            return redirect(url_for("admin_messages"))
        error = "رمز عبور صحیح نیست."
    return render_template("admin_login.html", csrf_token=session["csrf_token"], error=error)


@app.route("/admin", methods=["GET", "POST"])
def admin_messages():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        if not valid_csrf_token():
            abort(400, "درخواست نامعتبر است. صفحه را تازه کنید.")
        session.clear()
        return redirect(url_for("admin_login"))

    with get_db() as connection:
        messages = execute(connection,
            "SELECT id, name, phone, subject, message, created_at FROM contacts ORDER BY id DESC"
        ).fetchall()
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template("admin_messages.html", messages=messages, csrf_token=session["csrf_token"])


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(BASE_DIR, filename)


if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )

from datetime import datetime
from contextlib import contextmanager
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SQLITE_PATH", BASE_DIR / "school.db"))
CONTACTS_JSON_PATH = Path(os.getenv("CONTACTS_JSON_PATH", BASE_DIR / "contacts.json"))
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
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

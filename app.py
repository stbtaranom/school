from datetime import datetime
import os
from pathlib import Path
import sqlite3

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "school.db"
app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")


def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                category TEXT NOT NULL,
                date_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        count = connection.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
        if count == 0:
            connection.executemany(
                "INSERT INTO notices (title, summary, category, date_text, created_at) VALUES (?, ?, ?, ?, ?)",
                [
                    ("آغاز ثبت‌نام کلاس‌های فوق‌برنامه", "جزئیات زمان‌بندی و نحوه ثبت‌نام کلاس‌های ترم پاییز را از این بخش دنبال کنید.", "اطلاعیه", "۲۲ مهر ۱۴۰۴", datetime.now().isoformat()),
                    ("جشن آغاز سال تحصیلی جدید", "گزارش تصویری از اولین گردهمایی خانواده بزرگ شاهد فاطمیه.", "رویداد", "۱۵ مهر ۱۴۰۴", datetime.now().isoformat()),
                    ("برنامه جلسات اولیا و مربیان", "زمان‌بندی جلسات آشنایی خانواده‌ها با دبیران و کادر آموزشی اعلام شد.", "اطلاعیه", "۰۸ مهر ۱۴۰۴", datetime.now().isoformat()),
                    ("بازدید علمی از مرکز نوآوری", "دانش‌آموزان پایه دهم در یک بازدید علمی با دنیای فناوری آشنا شدند.", "رویداد", "۲۹ شهریور ۱۴۰۴", datetime.now().isoformat()),
                ],
            )


init_db()


@app.get("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/api/notices")
def notices():
    category = request.args.get("category")
    with get_db() as connection:
        if category and category != "all":
            rows = connection.execute(
                "SELECT id, title, summary, category, date_text FROM notices WHERE category = ? ORDER BY id DESC",
                (category,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT id, title, summary, category, date_text FROM notices ORDER BY id DESC"
            ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/contact")
def create_contact():
    payload = request.get_json(silent=True) or request.form
    fields = {key: str(payload.get(key, "")).strip() for key in ("name", "phone", "subject", "message")}
    if any(not value for value in fields.values()):
        return jsonify({"ok": False, "message": "لطفاً همه فیلدهای ضروری را کامل کنید."}), 400

    with get_db() as connection:
        connection.execute(
            "INSERT INTO contacts (name, phone, subject, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (*fields.values(), datetime.now().isoformat()),
        )
    return jsonify({"ok": True, "message": "پیام شما با موفقیت ثبت شد."}), 201


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(BASE_DIR, filename)


if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )

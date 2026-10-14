"""
Citizen Complaint System - Street Light & Civic Issues
Roles: Citizen + Engineer
Stack: Flask + SQLite
"""
import os
import sqlite3
import time
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "complaint-system-secret-key-change-this")

START_TIME = time.time()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "complaints.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

CATEGORIES = ["Street Light", "Water Supply", "Road Damage", "Garbage", "Drainage", "Other"]
STATUSES = ["Pending", "In Progress", "Completed"]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('citizen','engineer')),
            created_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            citizen_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            area TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            remark TEXT DEFAULT '',
            image_path TEXT DEFAULT '',
            latitude REAL DEFAULT NULL,
            longitude REAL DEFAULT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (citizen_id) REFERENCES users(id)
        )
    """)
    # Migrate old DBs missing new columns
    cols = [r[1] for r in db.execute("PRAGMA table_info(complaints)").fetchall()]
    if "image_path" not in cols:
        db.execute("ALTER TABLE complaints ADD COLUMN image_path TEXT DEFAULT ''")
    if "latitude" not in cols:
        db.execute("ALTER TABLE complaints ADD COLUMN latitude REAL DEFAULT NULL")
    if "longitude" not in cols:
        db.execute("ALTER TABLE complaints ADD COLUMN longitude REAL DEFAULT NULL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS esp_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ip TEXT NOT NULL,
            area TEXT DEFAULT '',
            added_by INTEGER,
            created_at TEXT NOT NULL
        )
    """)
    db.commit()
    db.close()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(role):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if session.get("role") != role:
                flash("Access denied.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


@app.route("/")
def home():
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) as c FROM complaints").fetchone()["c"]
        pending = db.execute("SELECT COUNT(*) as c FROM complaints WHERE status='Pending'").fetchone()["c"]
        inprog = db.execute("SELECT COUNT(*) as c FROM complaints WHERE status='In Progress'").fetchone()["c"]
        done = db.execute("SELECT COUNT(*) as c FROM complaints WHERE status='Completed'").fetchone()["c"]
        recent = db.execute(
            "SELECT c.*, u.name as citizen_name FROM complaints c JOIN users u ON c.citizen_id=u.id ORDER BY c.id DESC LIMIT 3"
        ).fetchall()
    except Exception:
        total = pending = inprog = done = 0
        recent = []
    # Logged-in users still see hero but with dashboard link; don't force redirect
    # so the Alderway hero stays visible as landing.
    return render_template("home.html", total=total, pending=pending,
                           inprog=inprog, done=done, recent=recent)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "citizen")

        if role not in ("citizen", "engineer"):
            role = "citizen"
        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return render_template("register.html")
        if len(password) < 4:
            flash("Password must be at least 4 characters.", "danger")
            return render_template("register.html")

        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (name, email, password, role, created_at) VALUES (?,?,?,?,?)",
                (name, email, generate_password_hash(password), role, datetime.now().isoformat(timespec="seconds")),
            )
            db.commit()
            flash("Registered successfully! Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered.", "danger")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["role"] = user["role"]
            flash(f'Welcome, {user["name"]}!', "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    if session.get("role") == "engineer":
        return redirect(url_for("engineer_dashboard"))
    return redirect(url_for("citizen_dashboard"))


# ---------- CITIZEN ----------
@app.route("/citizen")
@login_required
@role_required("citizen")
def citizen_dashboard():
    db = get_db()
    status_filter = request.args.get("status", "All")
    if status_filter in STATUSES:
        complaints = db.execute(
            "SELECT * FROM complaints WHERE citizen_id=? AND status=? ORDER BY id DESC",
            (session["user_id"], status_filter),
        ).fetchall()
    else:
        complaints = db.execute(
            "SELECT * FROM complaints WHERE citizen_id=? ORDER BY id DESC",
            (session["user_id"],),
        ).fetchall()
        status_filter = "All"

    counts = {}
    for s in STATUSES:
        row = db.execute(
            "SELECT COUNT(*) as c FROM complaints WHERE citizen_id=? AND status=?",
            (session["user_id"], s),
        ).fetchone()
        counts[s] = row["c"]

    return render_template("citizen_dashboard.html", complaints=complaints,
                           counts=counts, status_filter=status_filter, statuses=STATUSES)


@app.route("/citizen/new", methods=["GET", "POST"])
@login_required
@role_required("citizen")
def new_complaint():
    if request.method == "POST":
        import uuid
        from werkzeug.utils import secure_filename
        category = request.form.get("category", "")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        area = request.form.get("area", "").strip()
        lat_raw = request.form.get("latitude", "").strip()
        lng_raw = request.form.get("longitude", "").strip()

        if category not in CATEGORIES:
            flash("Please select a valid category.", "danger")
            return render_template("new_complaint.html", categories=CATEGORIES)
        if not title or not description or not area:
            flash("Title, description and area are required.", "danger")
            return render_template("new_complaint.html", categories=CATEGORIES)

        try:
            latitude = float(lat_raw) if lat_raw else None
            longitude = float(lng_raw) if lng_raw else None
        except ValueError:
            latitude, longitude = None, None

        # Photo upload / take photo (mobile camera via capture attr in form)
        image_path = ""
        photo = request.files.get("photo")
        if photo and photo.filename:
            if not allowed_file(photo.filename):
                flash("Photo must be png/jpg/jpeg/gif/webp.", "danger")
                return render_template("new_complaint.html", categories=CATEGORIES)
            ext = photo.filename.rsplit(".", 1)[1].lower()
            fname = f"{uuid.uuid4().hex}.{ext}"
            photo.save(os.path.join(app.config["UPLOAD_FOLDER"], secure_filename(fname)))
            image_path = f"uploads/{fname}"

        now = datetime.now().isoformat(timespec="seconds")
        db = get_db()
        db.execute(
            """INSERT INTO complaints
               (citizen_id, category, title, description, area, status, remark, image_path, latitude, longitude, created_at, updated_at)
               VALUES (?,?,?,?,?,'Pending','',?,?,?, ?,?)""",
            (session["user_id"], category, title, description, area, image_path, latitude, longitude, now, now),
        )
        db.commit()
        flash("Complaint submitted successfully with photo & location!", "success")
        return redirect(url_for("citizen_dashboard"))

    return render_template("new_complaint.html", categories=CATEGORIES)


@app.route("/citizen/complaint/<int:cid>")
@login_required
@role_required("citizen")
def citizen_view_complaint(cid):
    db = get_db()
    c = db.execute(
        "SELECT c.*, u.name as citizen_name FROM complaints c JOIN users u ON c.citizen_id=u.id WHERE c.id=? AND c.citizen_id=?",
        (cid, session["user_id"]),
    ).fetchone()
    if not c:
        flash("Complaint not found.", "danger")
        return redirect(url_for("citizen_dashboard"))
    return render_template("view_complaint.html", c=c, is_engineer=False)


# ---------- ENGINEER ----------
@app.route("/engineer")
@login_required
@role_required("engineer")
def engineer_dashboard():
    db = get_db()
    status_filter = request.args.get("status", "All")
    category_filter = request.args.get("category", "All")

    query = """SELECT c.*, u.name as citizen_name FROM complaints c
               JOIN users u ON c.citizen_id=u.id WHERE 1=1"""
    params = []
    if status_filter in STATUSES:
        query += " AND c.status=?"
        params.append(status_filter)
    if category_filter in CATEGORIES:
        query += " AND c.category=?"
        params.append(category_filter)
    query += " ORDER BY c.id DESC"

    complaints = db.execute(query, params).fetchall()

    counts = {}
    for s in STATUSES:
        row = db.execute("SELECT COUNT(*) as c FROM complaints WHERE status=?", (s,)).fetchone()
        counts[s] = row["c"]
    total = db.execute("SELECT COUNT(*) as c FROM complaints").fetchone()["c"]

    return render_template("engineer_dashboard.html", complaints=complaints,
                           counts=counts, total=total,
                           status_filter=status_filter, category_filter=category_filter,
                           statuses=STATUSES, categories=CATEGORIES)


@app.route("/engineer/complaint/<int:cid>", methods=["GET", "POST"])
@login_required
@role_required("engineer")
def engineer_view_complaint(cid):
    db = get_db()
    if request.method == "POST":
        status = request.form.get("status", "")
        remark = request.form.get("remark", "").strip()
        if status not in STATUSES:
            flash("Invalid status.", "danger")
        else:
            db.execute(
                "UPDATE complaints SET status=?, remark=?, updated_at=? WHERE id=?",
                (status, remark, datetime.now().isoformat(timespec="seconds"), cid),
            )
            db.commit()
            flash("Complaint updated successfully!", "success")
        return redirect(url_for("engineer_view_complaint", cid=cid))

    c = db.execute(
        "SELECT c.*, u.name as citizen_name, u.email as citizen_email FROM complaints c JOIN users u ON c.citizen_id=u.id WHERE c.id=?",
        (cid,),
    ).fetchone()
    if not c:
        flash("Complaint not found.", "danger")
        return redirect(url_for("engineer_dashboard"))
    return render_template("view_complaint.html", c=c, is_engineer=True, statuses=STATUSES)


# ---------- ESP32 DEVICES (engineer only) ----------
def clean_esp_ip(raw):
    """Accept '192.168.1.50', '192.168.1.50:80', or full URL. Return host[:port] or None."""
    import re
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^https?://", "", s, flags=re.I)
    s = s.split("/")[0].strip()
    # IPv4 + optional port, or mDNS/hostname + optional port
    if re.match(r"^(\d{1,3}\.){3}\d{1,3}(:\d{1,5})?$", s):
        parts = s.split(":")[0].split(".")
        if all(0 <= int(p) <= 255 for p in parts):
            return s
        return None
    if re.match(r"^[a-zA-Z0-9_.-]+(:\d{1,5})?$", s):
        return s
    return None


@app.route("/engineer/devices", methods=["GET", "POST"])
@login_required
@role_required("engineer")
def esp_devices():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip() or "Street Light Controller"
        ip_raw = request.form.get("ip", "")
        area = request.form.get("area", "").strip()
        ip = clean_esp_ip(ip_raw)
        if not ip:
            flash("Enter a valid ESP32 IP, e.g. 192.168.1.50 or 192.168.1.50:80", "danger")
        else:
            db.execute(
                "INSERT INTO esp_devices (name, ip, area, added_by, created_at) VALUES (?,?,?,?,?)",
                (name, ip, area, session["user_id"], datetime.now().isoformat(timespec="seconds")),
            )
            db.commit()
            flash(f"ESP32 {ip} saved! Click Open to go to its webserver.", "success")
        return redirect(url_for("esp_devices"))
    devices = db.execute("SELECT * FROM esp_devices ORDER BY id DESC").fetchall()
    return render_template("esp_devices.html", devices=devices)


@app.route("/engineer/devices/<int:did>/delete", methods=["POST"])
@login_required
@role_required("engineer")
def esp_device_delete(did):
    db = get_db()
    db.execute("DELETE FROM esp_devices WHERE id=?", (did,))
    db.commit()
    flash("Device removed.", "info")
    return redirect(url_for("esp_devices"))


@app.route("/engineer/devices/<int:did>/open")
@login_required
@role_required("engineer")
def esp_device_open(did):
    """Directly goes to the ESP32 webserver."""
    db = get_db()
    d = db.execute("SELECT * FROM esp_devices WHERE id=?", (did,)).fetchone()
    if not d:
        flash("Device not found.", "danger")
        return redirect(url_for("esp_devices"))
    return redirect(f"http://{d['ip']}/")


@app.route("/healthz")
def healthz():
    """UptimeRobot pings this every 5 min to keep Render free tier awake.
    Returns 200 + JSON so monitors can check keyword 'ok'."""
    uptime = int(time.time() - START_TIME)
    try:
        db = sqlite3.connect(DATABASE)
        db.execute("SELECT 1").fetchone()
        db.close()
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"
    return jsonify(status="ok", uptime_seconds=uptime, db=db_status), 200


@app.route("/status")
def status():
    """Public status page (human-friendly) for UptimeRobot concept demo."""
    uptime = int(time.time() - START_TIME)
    hrs, rem = divmod(uptime, 3600)
    mins, secs = divmod(rem, 60)
    return render_template("status.html", uptime_seconds=uptime,
                           uptime_str=f"{hrs}h {mins}m {secs}s")


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"Database ready. Open http://0.0.0.0:{port}")
    app.run(debug=debug, host="0.0.0.0", port=port)
else:
    # Gunicorn / Render: ensure DB exists on worker boot
    try:
        init_db()
    except Exception as e:
        print(f"DB init skipped: {e}")

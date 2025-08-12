# app.py
import os
import base64
import hashlib
import secrets
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template_string, request, redirect, url_for,
    session, flash, abort
)
import psycopg2
import psycopg2.extras
from psycopg2 import IntegrityError

# -------------------------
# Configuration
# -------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(24))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Please set DATABASE_URL environment variable (Neon Postgres connection string)")

# Chat extra allowed full names
ALLOWED_CHAT_FULL_NAMES = {
    "Lin Yirou",
    "Sum Wy Lok",
    "Sum Ee Lok",
    "Sum Ann Lok",
    "Lin Hongye",
}

# Allowed avatar extensions
ALLOWED_EXTS = {'png', 'jpg', 'jpeg', 'gif'}


# -------------------------
# DB helpers
# -------------------------
def get_db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)


def row_to_dict(row):
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def rows_to_dicts(rows):
    return [row_to_dict(r) for r in rows]


# -------------------------
# Init DB (safe to run multiple times)
# -------------------------
def init_db():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(50) UNIQUE NOT NULL,
        password_hash VARCHAR(128) NOT NULL,
        about TEXT,
        nickname VARCHAR(50),
        avatar_base64 TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id),
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id SERIAL PRIMARY KEY,
        post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
        user_id INTEGER REFERENCES users(id),
        comment TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id),
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    cur.close()
    conn.close()


init_db()


# -------------------------
# Utility functions
# -------------------------
def hash_password(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTS


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            flash("Please log in to access that page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# -------------------------
# Routes
# -------------------------

# Public: login & register only. All other routes require login.
@app.route('/')
@login_required
def home():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT posts.*, users.nickname, users.avatar_base64, users.username
        FROM posts JOIN users ON posts.user_id = users.id
        ORDER BY posts.created_at DESC
        LIMIT 50
    """)
    posts = rows_to_dicts(cur.fetchall())
    cur.close()
    conn.close()
    return render_template_string(HOME_HTML, posts=posts, session=session)


@app.route('/register', methods=['GET', 'POST'])
def register():
    # Allow registration without being logged in
    if session.get('user_id'):
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        about = request.form.get('about', '').strip()
        nickname = request.form.get('nickname', '').strip()
        avatar = request.files.get('avatar')

        if not username or not password:
            flash("Username and password required.", "danger")
            return redirect(url_for('register'))

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for('register'))

        avatar_b64 = None
        if avatar and avatar.filename and allowed_file(avatar.filename):
            avatar_b = avatar.read()
            avatar_b64 = base64.b64encode(avatar_b).decode('utf-8')

        pw_hash = hash_password(password)

        try:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password_hash, about, nickname, avatar_base64) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (username, pw_hash, about, nickname, avatar_b64)
            )
            user_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for('login'))
        except IntegrityError:
            # likely unique violation on username
            flash("Username already exists.", "danger")
            return redirect(url_for('register'))

    return render_template_string(REGISTER_HTML)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash("Fill both fields.", "warning")
            return redirect(url_for('login'))

        pw_hash = hash_password(password)
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s AND password_hash=%s", (username, pw_hash))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user:
            u = row_to_dict(user)
            session['user_id'] = u['id']
            session['username'] = u['username']
            session['nickname'] = u.get('nickname')
            session['avatar_base64'] = u.get('avatar_base64')
            # clear chat auth on login (user must re-enter full name)
            session.pop('chat_allowed', None)
            flash("Logged in successfully.", "success")
            return redirect(url_for('home'))
        else:
            flash("Invalid credentials.", "danger")
            return redirect(url_for('login'))

    return render_template_string(LOGIN_HTML)


@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))


# View all users (only accessible when logged in)
@app.route('/users')
@login_required
def users_list():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, nickname, avatar_base64 FROM users ORDER BY username ASC")
    users = rows_to_dicts(cur.fetchall())
    cur.close()
    conn.close()
    return render_template_string(USERS_HTML, users=users)


# View public profile of any user (only for logged-in visitors)
@app.route('/profile/<int:user_id>')
@login_required
def profile_view(user_id):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, nickname, about, avatar_base64 FROM users WHERE id=%s", (user_id,))
    user = row_to_dict(cur.fetchone())
    if user is None:
        cur.close()
        conn.close()
        abort(404)
    # fetch user's posts count and recent posts
    cur.execute("SELECT id, subject, created_at FROM posts WHERE user_id=%s ORDER BY created_at DESC LIMIT 10", (user_id,))
    posts = rows_to_dicts(cur.fetchall())
    cur.close()
    conn.close()
    return render_template_string(PROFILE_PUBLIC_HTML, user=user, posts=posts)


# Edit own profile
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile_edit():
    uid = session.get('user_id')
    conn = get_db_conn()
    cur = conn.cursor()
    if request.method == 'POST':
        about = request.form.get('about', '').strip()
        nickname = request.form.get('nickname', '').strip()
        avatar = request.files.get('avatar')
        avatar_b64 = session.get('avatar_base64')

        if avatar and avatar.filename and allowed_file(avatar.filename):
            avatar_b = avatar.read()
            avatar_b64 = base64.b64encode(avatar_b).decode('utf-8')

        cur.execute("UPDATE users SET about=%s, nickname=%s, avatar_base64=%s WHERE id=%s",
                    (about, nickname, avatar_b64, uid))
        conn.commit()
        # update session
        session['nickname'] = nickname
        session['avatar_base64'] = avatar_b64
        flash("Profile updated.", "success")

    cur.execute("SELECT id, username, nickname, about, avatar_base64 FROM users WHERE id=%s", (uid,))
    user = row_to_dict(cur.fetchone())
    cur.close()
    conn.close()
    return render_template_string(PROFILE_EDIT_HTML, user=user)


# Create a post
@app.route('/post', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        body = request.form.get('body', '').strip()
        if not subject or not body:
            flash("Subject and body required.", "warning")
            return redirect(url_for('create_post'))
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO posts (user_id, subject, body) VALUES (%s,%s,%s)", (session['user_id'], subject, body))
        conn.commit()
        cur.close()
        conn.close()
        flash("Post created.", "success")
        return redirect(url_for('home'))
    return render_template_string(POST_HTML)


# View a post + comments, add comments
@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
@login_required
def post_detail(post_id):
    conn = get_db_conn()
    cur = conn.cursor()
    if request.method == 'POST':
        comment = request.form.get('comment', '').strip()
        if not comment:
            flash("Comment cannot be empty.", "warning")
            return redirect(url_for('post_detail', post_id=post_id))
        cur.execute("INSERT INTO comments (post_id, user_id, comment) VALUES (%s,%s,%s)",
                    (post_id, session['user_id'], comment))
        conn.commit()
        flash("Comment added.", "success")

    cur.execute("""
        SELECT posts.*, u.nickname AS author_nick, u.avatar_base64 AS author_avatar, u.username AS author_username
        FROM posts JOIN users u ON posts.user_id = u.id
        WHERE posts.id=%s
    """, (post_id,))
    post = row_to_dict(cur.fetchone())
    if post is None:
        cur.close()
        conn.close()
        abort(404)

    cur.execute("""
        SELECT c.*, u.nickname, u.avatar_base64, u.username
        FROM comments c JOIN users u ON c.user_id = u.id
        WHERE c.post_id=%s ORDER BY c.created_at ASC
    """, (post_id,))
    comments = rows_to_dicts(cur.fetchall())
    cur.close()
    conn.close()
    return render_template_string(POST_DETAIL_HTML, post=post, comments=comments)


# Chat auth (enter full name to gain access for this session)
@app.route('/chat_auth', methods=['GET', 'POST'])
@login_required
def chat_auth():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        if full_name in ALLOWED_CHAT_FULL_NAMES:
            session['chat_allowed'] = True
            flash("Chat access granted for this session.", "success")
            return redirect(url_for('chat'))
        else:
            flash("Access denied. Your full name is not authorized.", "danger")
            return redirect(url_for('chat_auth'))
    return render_template_string(CHAT_AUTH_HTML)


# Chat page (requires both login and chat_allowed)
@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat():
    if not session.get('chat_allowed'):
        return redirect(url_for('chat_auth'))

    conn = get_db_conn()
    cur = conn.cursor()
    if request.method == 'POST':
        message = request.form.get('message', '').strip()
        if message:
            cur.execute("INSERT INTO chat_messages (user_id, message) VALUES (%s,%s)", (session['user_id'], message))
            conn.commit()
            flash("Message sent.", "success")

    cur.execute("""
        SELECT cm.*, u.nickname, u.avatar_base64, u.username
        FROM chat_messages cm JOIN users u ON cm.user_id = u.id
        ORDER BY cm.created_at ASC
        LIMIT 200
    """)
    messages = rows_to_dicts(cur.fetchall())
    cur.close()
    conn.close()
    return render_template_string(CHAT_HTML, messages=messages, session=session)


# -------------------------
# Templates (inline)
# -------------------------
# Note: styling uses blue-green accents with white background per your request.
# For brevity templates are included here; they are fairly verbose but self-contained.

# LOGIN page (public)
LOGIN_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Login — Chatterbox</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body { background: #ffffff; color:#055a52; font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial; }
.center { max-width:420px; margin:6rem auto; }
.brand { color:#0d9b8e; font-weight:700; font-size:1.6rem; letter-spacing:0.4px; }
.card { border-radius:12px; box-shadow:0 8px 30px rgba(13,155,142,0.08); }
.btn-primary { background:#0d9b8e; border:#0d9b8e; }
.btn-primary:hover { background:#055a52; border:#055a52; }
</style>
</head>
<body>
<div class="center">
  <div class="mb-3 text-center brand">Chatterbox</div>
  <div class="card p-4">
    <h5 class="mb-3">Log in</h5>
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for cat, msg in messages %}
          <div class="alert alert-{{cat}}">{{msg}}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    <form method="post">
      <div class="mb-3"><label class="form-label">Username</label><input name="username" class="form-control" required></div>
      <div class="mb-3"><label class="form-label">Password</label><input name="password" type="password" class="form-control" required></div>
      <button class="btn btn-primary w-100">Login</button>
    </form>
    <div class="text-center mt-3">
      <small>Don't have an account? <a href="{{ url_for('register') }}">Register</a></small>
    </div>
  </div>
</div>
</body>
</html>
"""

# REGISTER page (public)
REGISTER_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Register — Chatterbox</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body { background:#ffffff; color:#055a52; font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial; }
.center { max-width:520px; margin:3.5rem auto; }
.card { border-radius:12px; box-shadow:0 8px 30px rgba(13,155,142,0.06);}
.btn-primary { background:#0d9b8e; border:#0d9b8e; }
</style>
</head>
<body>
<div class="center">
  <div class="card p-4">
    <h4 class="mb-3">Create an account</h4>
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for cat, msg in messages %}
          <div class="alert alert-{{cat}}">{{msg}}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    <form method="post" enctype="multipart/form-data">
      <div class="mb-2"><label class="form-label">Username</label><input name="username" class="form-control" maxlength="50" required></div>
      <div class="mb-2"><label class="form-label">Password</label><input name="password" type="password" class="form-control" required></div>
      <div class="mb-2"><label class="form-label">Confirm</label><input name="confirm" type="password" class="form-control" required></div>
      <div class="mb-2"><label class="form-label">Nickname</label><input name="nickname" class="form-control" maxlength="50"></div>
      <div class="mb-2"><label class="form-label">Tell us about yourself</label><textarea name="about" class="form-control" rows="3"></textarea></div>
      <div class="mb-2"><label class="form-label">Avatar (png/jpg/gif)</label><input name="avatar" type="file" accept="image/*" class="form-control"></div>
      <button class="btn btn-primary w-100">Register</button>
    </form>
    <div class="text-center mt-3"><small>Already registered? <a href="{{ url_for('login') }}">Login</a></small></div>
  </div>
</div>
</body>
</html>
"""

# HOME (requires login)
HOME_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Home — Chatterbox</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
:root { --accent:#0d9b8e; --accent-dark:#055a52; }
body { background:#ffffff; color:#055a52; font-family: system-ui, -apple-system, "Segoe UI", Roboto; min-height:100vh; display:flex; flex-direction:column; }
.navbar { background:var(--accent); }
.navbar .nav-link, .navbar-brand { color: #fff !important; }
.container { max-width:980px; margin-top:2rem; flex:1 0 auto; }
.post { background:#e8f6f4; border-radius:12px; padding:1rem; margin-bottom:1rem; box-shadow:0 6px 18px rgba(5,90,82,0.06); }
.avatar { width:48px;height:48px;border-radius:50%;object-fit:cover;border:2px solid var(--accent-dark); }
.btn-accent { background:var(--accent); border:none; color:#fff; }
.btn-accent:hover { background:var(--accent-dark); }
footer { background:var(--accent-dark); color:#fff; padding:0.75rem; text-align:center; margin-top:auto; }
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg">
  <div class="container">
    <a class="navbar-brand fw-bold" href="{{ url_for('home') }}">Chatterbox</a>
    <div class="d-flex gap-2">
      <a class="btn btn-outline-light btn-sm" href="{{ url_for('users_list') }}">People</a>
      <a class="btn btn-outline-light btn-sm" href="{{ url_for('profile') }}">My Profile</a>
      <a class="btn btn-outline-light btn-sm" href="{{ url_for('post') }}">New Post</a>
      <a class="btn btn-outline-light btn-sm" href="{{ url_for('chat') }}">Chat</a>
      <a class="btn btn-outline-light btn-sm" href="{{ url_for('logout') }}">Logout</a>
    </div>
  </div>
</nav>

<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for cat, msg in messages %}
        <div class="alert alert-{{cat}}">{{msg}}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  <h4 class="mb-3">Recent posts</h4>
  {% for p in posts %}
    <div class="post">
      <div class="d-flex align-items-center mb-2">
        {% if p.avatar_base64 %}
          <img src="data:image/png;base64,{{ p.avatar_base64 }}" class="avatar me-3">
        {% else %}
          <div class="avatar bg-secondary me-3 d-flex justify-content-center align-items-center text-white fw-bold">?</div>
        {% endif %}
        <div>
          <div class="fw-600">{{ p.nickname or p.username }}</div>
          <small class="text-muted">{{ p.created_at.strftime('%Y-%m-%d %H:%M') }}</small>
        </div>
        <div class="ms-auto">
          <a href="{{ url_for('profile_view', user_id=p.user_id) }}" class="btn btn-sm btn-outline-primary me-2">Profile</a>
          <a href="{{ url_for('post_detail', post_id=p.id) }}" class="btn btn-sm btn-accent">View</a>
        </div>
      </div>
      <h5>{{ p.subject }}</h5>
      <p>{{ p.body }}</p>
    </div>
  {% else %}
    <p>No posts yet.</p>
  {% endfor %}
</div>

<footer>© 2025 Chatterbox</footer>
</body>
</html>
"""

# USERS listing
USERS_HTML = """
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>People — Chatterbox</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>body{background:#fff;color:#055a52;font-family:system-ui;} .container{max-width:900px;margin:2rem auto;} .avatar{width:56px;height:56px;border-radius:50%;object-fit:cover;border:2px solid #0d9b8e}</style>
</head><body>
<nav class="navbar" style="background:#0d9b8e"><div class="container"><a href="{{ url_for('home') }}" class="navbar-brand text-white">Chatterbox</a></div></nav>
<div class="container">
  <h4 class="mb-3">People on Chatterbox</h4>
  <div class="list-group">
    {% for u in users %}
      <a class="list-group-item list-group-item-action d-flex align-items-center" href="{{ url_for('profile_view', user_id=u.id) }}">
        {% if u.avatar_base64 %}
          <img src="data:image/png;base64,{{ u.avatar_base64 }}" class="avatar me-3">
        {% else %}
          <div class="avatar bg-secondary me-3 d-flex justify-content-center align-items-center text-white fw-bold">?</div>
        {% endif %}
        <div>
          <div class="fw-bold">{{ u.nickname or u.username }}</div>
          <small class="text-muted">{{ u.username }}</small>
        </div>
        <div class="ms-auto text-muted">View profile</div>
      </a>
    {% endfor %}
  </div>
</div>
</body></html>
"""

# PROFILE public view (others can view)
PROFILE_PUBLIC_HTML = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Profile — Chatterbox</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>body{background:#fff;color:#055a52;font-family:system-ui;} .container{max-width:800px;margin:2rem auto;} .avatar-lg{width:120px;height:120px;border-radius:50%;object-fit:cover;border:3px solid #0d9b8e}</style>
</head><body>
<nav class="navbar" style="background:#0d9b8e"><div class="container"><a href="{{ url_for('home') }}" class="navbar-brand text-white">Chatterbox</a></div></nav>
<div class="container card p-4">
  <div class="d-flex align-items-center gap-3">
    {% if user.avatar_base64 %}
      <img src="data:image/png;base64,{{ user.avatar_base64 }}" class="avatar-lg">
    {% else %}
      <div class="avatar-lg bg-secondary d-flex justify-content-center align-items-center text-white fw-bold" style="font-size:2rem">?</div>
    {% endif %}
    <div>
      <h3>{{ user.nickname or user.username }}</h3>
      <p class="text-muted">{{ user.username }}</p>
    </div>
    <div class="ms-auto">
      <a class="btn btn-outline-primary" href="{{ url_for('message_user', user_id=user.id) }}" style="display:none">Message</a>
    </div>
  </div>
  <hr>
  <h5>About</h5>
  <p>{{ user.about or "No bio yet." }}</p>

  <h5>Recent posts</h5>
  {% for p in posts %}
    <div class="border p-2 rounded mb-2">
      <div class="d-flex justify-content-between"><strong>{{ p.subject }}</strong><small class="text-muted">{{ p.created_at.strftime('%Y-%m-%d') }}</small></div>
    </div>
  {% else %}
    <p class="text-muted">No posts yet.</p>
  {% endfor %}
</div>
</body></html>
"""

# PROFILE edit (own)
PROFILE_EDIT_HTML = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>My Profile — Chatterbox</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>body{background:#fff;color:#055a52;font-family:system-ui;} .container{max-width:700px;margin:2rem auto;} .avatar-xl{width:96px;height:96px;border-radius:50%;object-fit:cover;border:3px solid #0d9b8e}</style>
</head><body>
<nav class="navbar" style="background:#0d9b8e"><div class="container"><a href="{{ url_for('home') }}" class="navbar-brand text-white">Chatterbox</a></div></nav>
<div class="container card p-4">
  <h4>My Profile</h4>
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for cat,msg in messages %}
        <div class="alert alert-{{cat}}">{{msg}}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  <div class="d-flex gap-3 mb-3">
    {% if user.avatar_base64 %}
      <img src="data:image/png;base64,{{ user.avatar_base64 }}" class="avatar-xl">
    {% else %}
      <div class="avatar-xl bg-secondary d-flex justify-content-center align-items-center text-white fw-bold" style="font-size:1.5rem">?</div>
    {% endif %}
    <div>
      <div class="fw-bold">{{ user.username }}</div>
      <div class="text-muted">Edit your profile below.</div>
    </div>
  </div>
  <form method="post" enctype="multipart/form-data">
    <div class="mb-2"><label class="form-label">Nickname</label><input name="nickname" value="{{ user.nickname }}" class="form-control"></div>
    <div class="mb-2"><label class="form-label">About</label><textarea name="about" class="form-control" rows="4">{{ user.about }}</textarea></div>
    <div class="mb-2"><label class="form-label">Change avatar</label><input name="avatar" type="file" accept="image/*" class="form-control"></div>
    <button class="btn btn-primary">Save</button>
  </form>
</div>
</body></html>
"""

# CREATE POST page
POST_HTML = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>New Post — Chatterbox</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>body{background:#fff;color:#055a52;font-family:system-ui;} .container{max-width:800px;margin:2rem auto;}</style>
</head><body>
<nav class="navbar" style="background:#0d9b8e"><div class="container"><a href="{{ url_for('home') }}" class="navbar-brand text-white">Chatterbox</a></div></nav>
<div class="container card p-4">
  <h4>Create a new post</h4>
  <form method="post">
    <div class="mb-2"><label class="form-label">Subject</label><input name="subject" class="form-control" maxlength="200" required></div>
    <div class="mb-2"><label class="form-label">Body</label><textarea name="body" rows="6" class="form-control" required></textarea></div>
    <button class="btn btn-primary">Post</button>
  </form>
</div>
</body></html>
"""

# POST detail + comments
POST_DETAIL_HTML = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{{ post.subject }} — Chatterbox</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>body{background:#fff;color:#055a52;font-family:system-ui;} .container{max-width:900px;margin:2rem auto;} .avatar{width:44px;height:44px;border-radius:50%;object-fit:cover;border:2px solid #0d9b8e}</style>
</head><body>
<nav class="navbar" style="background:#0d9b8e"><div class="container"><a class="navbar-brand text-white" href="{{ url_for('home') }}">Chatterbox</a></div></nav>
<div class="container card p-4">
  <h3>{{ post.subject }}</h3>
  <div class="d-flex align-items-center mb-3">
    {% if post.author_avatar %}<img src="data:image/png;base64,{{ post.author_avatar }}" class="avatar me-3">{% else %}<div class="avatar bg-secondary me-3"></div>{% endif %}
    <div><strong>{{ post.author_nick or post.author_username }}</strong><br><small class="text-muted">{{ post.created_at.strftime('%Y-%m-%d %H:%M') }}</small></div>
  </div>
  <p>{{ post.body }}</p>
  <hr>
  <h5>Comments</h5>
  {% for c in comments %}
    <div class="mb-3 p-2 border rounded">
      <div class="d-flex align-items-center mb-1">
        {% if c.avatar_base64 %}<img src="data:image/png;base64,{{ c.avatar_base64 }}" class="avatar me-2">{% else %}<div class="avatar bg-secondary me-2"></div>{% endif %}
        <div><strong>{{ c.nickname or c.username }}</strong> <small class="text-muted">{{ c.created_at.strftime('%Y-%m-%d %H:%M') }}</small></div>
      </div>
      <div>{{ c.comment }}</div>
    </div>
  {% else %}
    <p>No comments yet.</p>
  {% endfor %}

  <hr>
  <h6>Add a comment</h6>
  <form method="post">
    <div class="mb-2"><textarea name="comment" rows="3" class="form-control" required></textarea></div>
    <button class="btn btn-primary">Send Comment</button>
  </form>
</div>
</body></html>
"""

# CHAT AUTH page
CHAT_AUTH_HTML = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Chat Access — Chatterbox</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><style>body{background:#fff;color:#055a52;font-family:system-ui;} .center{max-width:560px;margin:3rem auto;}</style></head>
<body>
<div class="center card p-4">
  <h5>Chat Room Access</h5>
  <p>To enter the chat room, enter your full name. Only authorized full names are allowed.</p>
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for cat,msg in messages %}<div class="alert alert-{{cat}}">{{msg}}</div>{% endfor %}
    {% endif %}
  {% endwith %}
  <form method="post">
    <div class="mb-2"><label>Full name</label><input name="full_name" class="form-control" required></div>
    <button class="btn btn-primary">Request Access</button>
  </form>
  <p class="mt-2"><a href="{{ url_for('home') }}">Back</a></p>
</div>
</body></html>
"""

# CHAT page
CHAT_HTML = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Chat — Chatterbox</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>body{background:#fff;color:#055a52;font-family:system-ui;} nav{background:#0d9b8e} .container{max-width:900px;margin:2rem auto;} .avatar{width:40px;height:40px;border-radius:50%;object-fit:cover;border:2px solid #0d9b8e} .messages{max-height:420px;overflow:auto;background:#fff;border:1px solid #dfeff0;padding:1rem;border-radius:10px}</style>
</head><body>
<nav class="navbar"><div class="container"><a class="navbar-brand text-white" href="{{ url_for('home') }}">Chatterbox</a></div></nav>
<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for cat,msg in messages %}<div class="alert alert-{{cat}}">{{msg}}</div>{% endfor %}
    {% endif %}
  {% endwith %}
  <div class="messages mb-3" id="messages">
    {% for m in messages %}
      <div class="d-flex mb-3">
        {% if m.avatar_base64 %}<img src="data:image/png;base64,{{ m.avatar_base64 }}" class="avatar me-2">{% else %}<div class="avatar bg-secondary me-2"></div>{% endif %}
        <div>
          <div><strong>{{ m.nickname or m.username }}</strong> <small class="text-muted ms-2">{{ m.created_at.strftime('%Y-%m-%d %H:%M:%S') }}</small></div>
          <div style="white-space:pre-wrap">{{ m.message }}</div>
        </div>
      </div>
    {% else %}
      <p class="text-muted">No messages yet.</p>
    {% endfor %}
  </div>

  <form method="post">
    <div class="mb-2"><textarea name="message" rows="3" class="form-control" placeholder="Type a message..." required></textarea></div>
    <button class="btn btn-primary">Send</button>
  </form>
</div>
<script>
const messagesDiv = document.getElementById('messages');
if(messagesDiv){ messagesDiv.scrollTop = messagesDiv.scrollHeight; }
</script>
</body></html>
"""

# -------------------------
# Run
# -------------------------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    # In production you will run via gunicorn; debug only for local run
    app.run(host='0.0.0.0', port=port, debug=False)

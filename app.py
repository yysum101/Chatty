import os
import psycopg2
import psycopg2.extras
from flask import (
    Flask, request, session, redirect, url_for,
    render_template_string, flash, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or "supersecretkey"

# Config
DATABASE_URL = os.environ.get("DATABASE_URL")  # Neon postgres URL
UPLOAD_FOLDER = 'avatars'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Connect to DB
def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
    return conn

# DB init - only create tables if missing
def init_db():
    conn = get_db()
    cur = conn.cursor()
    # Check if 'users' table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'users'
        );
    """)
    if not cur.fetchone()[0]:
        # Create tables
        cur.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                nickname TEXT NOT NULL,
                about TEXT,
                avatar TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE posts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE comments (
                id SERIAL PRIMARY KEY,
                post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        print("Database initialized.")
    cur.close()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_current_user():
    if "user_id" in session:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],))
        user = cur.fetchone()
        cur.close()
        conn.close()
        return user
    return None

@app.route('/')
def home():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT posts.*, users.nickname FROM posts
        JOIN users ON posts.user_id = users.id
        ORDER BY posts.created_at DESC
        LIMIT 20
    """)
    posts = cur.fetchall()
    cur.close()
    conn.close()
    return render_template_string(TEMPLATE_HOME, posts=posts, user=user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        confirm = request.form['confirm']
        nickname = request.form['nickname'].strip()
        about = request.form['about'].strip()

        if not username or not password or not confirm or not nickname:
            flash("Please fill in all required fields.", "danger")
            return redirect(url_for('register'))
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for('register'))

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s", (username,))
        if cur.fetchone():
            flash("Username already taken.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for('register'))

        pw_hash = generate_password_hash(password)
        cur.execute(
            "INSERT INTO users (username, password_hash, nickname, about) VALUES (%s, %s, %s, %s) RETURNING id",
            (username, pw_hash, nickname, about)
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        session['user_id'] = user_id
        flash("Registered successfully!", "success")
        return redirect(url_for('home'))
    return render_template_string(TEMPLATE_REGISTER)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            flash("Logged in successfully.", "success")
            return redirect(url_for('home'))
        else:
            flash("Invalid username or password.", "danger")
            return redirect(url_for('login'))
    return render_template_string(TEMPLATE_LOGIN)

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for('login'))

@app.route('/post/create', methods=['GET', 'POST'])
def create_post():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    if request.method == 'POST':
        subject = request.form['subject'].strip()
        body = request.form['body'].strip()
        if not subject or not body:
            flash("Subject and body required.", "danger")
            return redirect(url_for('create_post'))
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO posts (user_id, subject, body) VALUES (%s, %s, %s)",
            (user['id'], subject, body)
        )
        conn.commit()
        cur.close()
        conn.close()
        flash("Post created!", "success")
        return redirect(url_for('home'))
    return render_template_string(TEMPLATE_CREATE_POST, user=user)

@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def post_detail(post_id):
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT posts.*, users.nickname FROM posts
        JOIN users ON posts.user_id = users.id
        WHERE posts.id = %s
    """, (post_id,))
    post = cur.fetchone()
    if not post:
        cur.close()
        conn.close()
        flash("Post not found.", "danger")
        return redirect(url_for('home'))

    if request.method == 'POST':
        comment_body = request.form.get('comment', '').strip()
        if comment_body:
            cur.execute("""
                INSERT INTO comments (post_id, user_id, body)
                VALUES (%s, %s, %s)
            """, (post_id, user['id'], comment_body))
            conn.commit()
            flash("Comment added.", "success")

    cur.execute("""
        SELECT comments.*, users.nickname FROM comments
        JOIN users ON comments.user_id = users.id
        WHERE comments.post_id = %s
        ORDER BY comments.created_at ASC
    """, (post_id,))
    comments = cur.fetchall()

    cur.close()
    conn.close()
    return render_template_string(TEMPLATE_POST_DETAIL, post=post, comments=comments, user=user)

@app.route('/profile/<int:user_id>')
def profile(user_id):
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    profile = cur.fetchone()
    if not profile:
        cur.close()
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for('home'))
    cur.close()
    conn.close()
    return render_template_string(TEMPLATE_PROFILE, profile=profile, user=user)

@app.route('/avatar/<filename>')
def avatar(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    if request.method == 'POST':
        nickname = request.form['nickname'].strip()
        about = request.form['about'].strip()

        avatar_file = request.files.get('avatar')
        avatar_filename = None

        if avatar_file and allowed_file(avatar_file.filename):
            filename = secure_filename(avatar_file.filename)
            unique_name = f"{uuid.uuid4().hex}_{filename}"
            avatar_file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
            avatar_filename = unique_name

        conn = get_db()
        cur = conn.cursor()
        if avatar_filename:
            cur.execute("""
                UPDATE users SET nickname=%s, about=%s, avatar=%s WHERE id=%s
            """, (nickname, about, avatar_filename, user['id']))
        else:
            cur.execute("""
                UPDATE users SET nickname=%s, about=%s WHERE id=%s
            """, (nickname, about, user['id']))
        conn.commit()
        cur.close()
        conn.close()
        flash("Settings updated.", "success")
        return redirect(url_for('settings'))

    return render_template_string(TEMPLATE_SETTINGS, user=user)

# Inline Bootstrap 5 Blue-Green theme templates:

TEMPLATE_BASE = '''
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chatterbox - {{ title or "" }}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  body { background: white; color: #0f5132; }
  .navbar, .footer {
    background: linear-gradient(45deg, #009879, #3ecf8e);
    color: white !important;
  }
  .navbar-brand, .nav-link, .footer {
    color: white !important;
  }
  a.nav-link:hover {
    color: #d4f1e4 !important;
  }
  .avatar {
    border-radius: 50%;
    width: 48px;
    height: 48px;
    object-fit: cover;
    border: 2px solid #006644;
  }
  .footer {
    position: fixed;
    bottom: 0;
    width: 100%;
    height: 40px;
    line-height: 40px;
    text-align: center;
    font-weight: bold;
    font-size: 14px;
  }
</style>
</head>
<body>

<nav class="navbar navbar-expand-lg">
  <div class="container-fluid">
    <a class="navbar-brand fw-bold" href="{{ url_for('home') }}">Chatterbox</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navmenu"
      aria-controls="navmenu" aria-expanded="false" aria-label="Toggle navigation">
      <span class="navbar-toggler-icon"></span>
    </button>
    {% if user %}
    <div class="collapse navbar-collapse" id="navmenu">
      <ul class="navbar-nav ms-auto mb-2 mb-lg-0 align-items-center">
        <li class="nav-item">
          <a class="nav-link" href="{{ url_for('home') }}">Home</a>
        </li>
        <li class="nav-item">
          <a class="nav-link" href="{{ url_for('create_post') }}">New Post</a>
        </li>
        <li class="nav-item dropdown">
          <a class="nav-link dropdown-toggle d-flex align-items-center" href="#" id="userMenu" role="button" data-bs-toggle="dropdown" aria-expanded="false">
            {% if user.avatar %}
              <img src="{{ url_for('avatar', filename=user.avatar) }}" alt="Avatar" class="avatar me-2">
            {% else %}
              <img src="https://via.placeholder.com/48?text=?" alt="Avatar" class="avatar me-2">
            {% endif %}
            {{ user.nickname }}
          </a>
          <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="userMenu">
            <li><a class="dropdown-item" href="{{ url_for('profile', user_id=user.id) }}">Profile</a></li>
            <li><a class="dropdown-item" href="{{ url_for('settings') }}">Settings</a></li>
            <li><hr class="dropdown-divider"></li>
            <li><a class="dropdown-item text-danger" href="{{ url_for('logout') }}">Logout</a></li>
          </ul>
        </li>
      </ul>
    </div>
    {% endif %}
  </div>
</nav>

<div class="container my-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, msg in messages %}
        <div class="alert alert-{{category}} alert-dismissible fade show" role="alert">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>

<footer class="footer">
  Chatterbox © 2025 by Chicken
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

TEMPLATE_LOGIN = '''
{% extends none %}
{% block content %}
<h2>Login</h2>
<form method="post" class="mb-3">
  <div class="mb-3">
    <label for="username" class="form-label">Username</label>
    <input required type="text" class="form-control" id="username" name="username" placeholder="Enter username">
  </div>
  <div class="mb-3">
    <label for="password" class="form-label">Password</label>
    <input required type="password" class="form-control" id="password" name="password" placeholder="Enter password">
  </div>
  <button type="submit" class="btn btn-success">Login</button>
  <a href="{{ url_for('register') }}" class="btn btn-link">Register</a>
</form>
{% endblock %}
'''

TEMPLATE_REGISTER = '''
{% extends none %}
{% block content %}
<h2>Register</h2>
<form method="post" class="mb-3">
  <div class="mb-3">
    <label for="username" class="form-label">Username</label>
    <input required type="text" class="form-control" id="username" name="username" placeholder="Choose username">
  </div>
  <div class="mb-3">
    <label for="nickname" class="form-label">Nickname</label>
    <input required type="text" class="form-control" id="nickname" name="nickname" placeholder="Your nickname">
  </div>
  <div class="mb-3">
    <label for="about" class="form-label">Tell us about yourself</label>
    <textarea class="form-control" id="about" name="about" rows="3" placeholder="Optional"></textarea>
  </div>
  <div class="mb-3">
    <label for="password" class="form-label">Password</label>
    <input required type="password" class="form-control" id="password" name="password" placeholder="Choose password">
  </div>
  <div class="mb-3">
    <label for="confirm" class="form-label">Confirm Password</label>
    <input required type="password" class="form-control" id="confirm" name="confirm" placeholder="Confirm password">
  </div>
  <button type="submit" class="btn btn-success">Register</button>
  <a href="{{ url_for('login') }}" class="btn btn-link">Back to Login</a>
</form>
{% endblock %}
'''

TEMPLATE_HOME = '''
{% extends none %}
{% block content %}
<h2>Recent Posts</h2>
{% if posts %}
  {% for post in posts %}
  <div class="card mb-3 shadow-sm">
    <div class="card-header d-flex align-items-center">
      <a href="{{ url_for('profile', user_id=post.user_id) }}" class="me-3 text-decoration-none text-success">
        {{ post.nickname }}
      </a>
      <div class="flex-grow-1 fw-bold">{{ post.subject }}</div>
      <small class="text-muted">{{ post.created_at.strftime('%Y-%m-%d %H:%M') }}</small>
    </div>
    <div class="card-body">
      <p>{{ post.body }}</p>
      <a href="{{ url_for('post_detail', post_id=post.id) }}" class="btn btn-outline-success btn-sm">View & Comment</a>
    </div>
  </div>
  {% endfor %}
{% else %}
  <p>No posts yet. <a href="{{ url_for('create_post') }}">Create the first one!</a></p>
{% endif %}
{% endblock %}
'''

TEMPLATE_CREATE_POST = '''
{% extends none %}
{% block content %}
<h2>Create New Post</h2>
<form method="post" class="mb-3">
  <div class="mb-3">
    <label for="subject" class="form-label">Subject</label>
    <input required type="text" class="form-control" id="subject" name="subject" placeholder="Post subject">
  </div>
  <div class="mb-3">
    <label for="body" class="form-label">Body</label>
    <textarea required class="form-control" id="body" name="body" rows="5" placeholder="Write your post here..."></textarea>
  </div>
  <button type="submit" class="btn btn-success">Post</button>
  <a href="{{ url_for('home') }}" class="btn btn-link">Cancel</a>
</form>
{% endblock %}
'''

TEMPLATE_POST_DETAIL = '''
{% extends none %}
{% block content %}
<h2>{{ post.subject }}</h2>
<div class="mb-3 text-muted">
  By <a href="{{ url_for('profile', user_id=post.user_id) }}">{{ post.nickname }}</a> on {{ post.created_at.strftime('%Y-%m-%d %H:%M') }}
</div>
<p>{{ post.body }}</p>
<hr>
<h4>Comments</h4>
{% if comments %}
  {% for c in comments %}
  <div class="mb-2 border p-2 rounded">
    <small class="text-success">{{ c.nickname }} said on {{ c.created_at.strftime('%Y-%m-%d %H:%M') }}:</small>
    <p>{{ c.body }}</p>
  </div>
  {% endfor %}
{% else %}
  <p>No comments yet.</p>
{% endif %}
<hr>
<h5>Add Comment</h5>
<form method="post" class="mb-3">
  <textarea required class="form-control mb-2" name="comment" rows="3" placeholder="Write a comment..."></textarea>
  <button type="submit" class="btn btn-success btn-sm">Submit</button>
  <a href="{{ url_for('home') }}" class="btn btn-link btn-sm">Back</a>
</form>
{% endblock %}
'''

TEMPLATE_PROFILE = '''
{% extends none %}
{% block content %}
<h2>{{ profile.nickname }}'s Profile</h2>
<div class="d-flex align-items-center mb-3">
  {% if profile.avatar %}
    <img src="{{ url_for('avatar', filename=profile.avatar) }}" alt="Avatar" class="avatar me-3" style="width:96px; height:96px;">
  {% else %}
    <img src="https://via.placeholder.com/96?text=?" alt="Avatar" class="avatar me-3" style="width:96px; height:96px;">
  {% endif %}
  <div>
    <p><strong>Username:</strong> {{ profile.username }}</p>
    <p><strong>About:</strong> {{ profile.about or "No info provided." }}</p>
    <p><strong>Joined:</strong> {{ profile.created_at.strftime('%Y-%m-%d') }}</p>
  </div>
</div>
<a href="{{ url_for('home') }}" class="btn btn-link">Back Home</a>
{% endblock %}
'''

TEMPLATE_SETTINGS = '''
{% extends none %}
{% block content %}
<h2>Settings</h2>
<form method="post" enctype="multipart/form-data" class="mb-3">
  <div class="mb-3">
    <label for="nickname" class="form-label">Nickname</label>
    <input required type="text" class="form-control" id="nickname" name="nickname" value="{{ user.nickname }}">
  </div>
  <div class="mb-3">
    <label for="about" class="form-label">About</label>
    <textarea class="form-control" id="about" name="about" rows="3">{{ user.about }}</textarea>
  </div>
  <div class="mb-3">
    <label for="avatar" class="form-label">Avatar (png/jpg/gif, max 2MB)</label>
    <input type="file" class="form-control" id="avatar" name="avatar" accept=".png,.jpg,.jpeg,.gif">
  </div>
  <button type="submit" class="btn btn-success">Update Settings</button>
  <a href="{{ url_for('home') }}" class="btn btn-link">Cancel</a>
</form>
{% endblock %}
'''

# Render Templates Wrapper (to use TEMPLATE_BASE with inline templates)
def render_template_string(tpl, **context):
    base = TEMPLATE_BASE.replace("{% block content %}{% endblock %}", tpl)
    return render_template_string_original(base, **context)

# Save original to avoid recursion
render_template_string_original = render_template_string

# Override Flask's render_template_string to our wrapper
import flask.templating
flask.templating.render_template_string = render_template_string

# Init DB on start
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

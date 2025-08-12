import os
import psycopg2
import psycopg2.extras
from flask import Flask, render_template_string, request, redirect, url_for, session, flash, send_from_directory, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey")

DATABASE_URL = os.environ.get("DATABASE_URL")  # Neon/Postgres URL here
AVATAR_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), "avatars")
os.makedirs(AVATAR_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
    return conn

def query_db(query, args=(), one=False, commit=False):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(query, args)
    if commit:
        conn.commit()
        cur.close()
        conn.close()
        return None
    rv = cur.fetchall()
    cur.close()
    conn.close()
    return (rv[0] if rv else None) if one else rv

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        nickname TEXT NOT NULL,
        about TEXT,
        avatar TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id SERIAL PRIMARY KEY,
        post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

@app.route("/")
@login_required
def home():
    posts = query_db("""
        SELECT posts.*, users.nickname FROM posts
        JOIN users ON posts.user_id = users.id
        ORDER BY posts.created_at DESC
        LIMIT 20
    """)
    return render_template_string(TEMPLATE_HOME, posts=posts, user=get_current_user())

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        confirm = request.form["confirm"]
        nickname = request.form["nickname"].strip()
        about = request.form["about"].strip()
        if not username or not password or not confirm or not nickname:
            flash("Please fill in all required fields.")
            return redirect(url_for("register"))
        if password != confirm:
            flash("Passwords do not match.")
            return redirect(url_for("register"))
        if query_db("SELECT id FROM users WHERE username=%s", (username,), one=True):
            flash("Username already taken.")
            return redirect(url_for("register"))
        password_hash = generate_password_hash(password)
        query_db(
            "INSERT INTO users (username, password_hash, nickname, about) VALUES (%s, %s, %s, %s)",
            (username, password_hash, nickname, about),
            commit=True,
        )
        flash("Registration successful. Please log in.")
        return redirect(url_for("login"))
    return render_template_string(TEMPLATE_REGISTER)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        user = query_db("SELECT * FROM users WHERE username=%s", (username,), one=True)
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.")
            return redirect(url_for("login"))
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        flash(f"Welcome, {user['nickname']}!")
        return redirect(url_for("home"))
    return render_template_string(TEMPLATE_LOGIN)

@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Logged out successfully.")
    return redirect(url_for("login"))

@app.route("/post/new", methods=["GET", "POST"])
@login_required
def new_post():
    if request.method == "POST":
        subject = request.form["subject"].strip()
        body = request.form["body"].strip()
        if not subject or not body:
            flash("Subject and body cannot be empty.")
            return redirect(url_for("new_post"))
        query_db(
            "INSERT INTO posts (user_id, subject, body) VALUES (%s, %s, %s)",
            (session["user_id"], subject, body),
            commit=True,
        )
        flash("Post created successfully.")
        return redirect(url_for("home"))
    return render_template_string(TEMPLATE_NEW_POST)

@app.route("/post/<int:post_id>", methods=["GET", "POST"])
@login_required
def post_detail(post_id):
    post = query_db("""
        SELECT posts.*, users.nickname FROM posts
        JOIN users ON posts.user_id = users.id
        WHERE posts.id = %s
    """, (post_id,), one=True)
    if not post:
        abort(404)
    if request.method == "POST":
        comment_body = request.form.get("comment", "").strip()
        if comment_body:
            query_db(
                "INSERT INTO comments (post_id, user_id, body) VALUES (%s, %s, %s)",
                (post_id, session["user_id"], comment_body),
                commit=True,
            )
            flash("Comment added.")
            return redirect(url_for("post_detail", post_id=post_id))
        else:
            flash("Comment cannot be empty.")
    comments = query_db("""
        SELECT comments.*, users.nickname FROM comments
        JOIN users ON comments.user_id = users.id
        WHERE comments.post_id = %s
        ORDER BY comments.created_at ASC
    """, (post_id,))
    return render_template_string(TEMPLATE_POST_DETAIL, post=post, comments=comments, user=get_current_user())

@app.route("/profile/<int:user_id>")
@login_required
def profile(user_id):
    profile = query_db("SELECT * FROM users WHERE id=%s", (user_id,), one=True)
    if not profile:
        abort(404)
    return render_template_string(TEMPLATE_PROFILE, profile=profile)

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = get_current_user()
    if request.method == "POST":
        nickname = request.form["nickname"].strip()
        about = request.form["about"].strip()
        avatar_file = request.files.get("avatar")
        avatar_filename = user["avatar"]
        if avatar_file and allowed_file(avatar_file.filename):
            filename = secure_filename(avatar_file.filename)
            avatar_file.save(os.path.join(AVATAR_FOLDER, filename))
            avatar_filename = filename
        query_db("""
            UPDATE users SET nickname=%s, about=%s, avatar=%s WHERE id=%s
        """, (nickname, about, avatar_filename, user["id"]), commit=True)
        flash("Settings updated.")
        return redirect(url_for("settings"))
    return render_template_string(TEMPLATE_SETTINGS, user=user)

@app.route("/avatars/<filename>")
def avatar(filename):
    return send_from_directory(AVATAR_FOLDER, filename)

def get_current_user():
    if "user_id" in session:
        return query_db("SELECT * FROM users WHERE id=%s", (session["user_id"],), one=True)
    return None

# Templates as inline strings follow:

TEMPLATE_BASE = '''
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chatterbox</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  body {background: #f9fdfd; color: #044d40;}
  .navbar {background: linear-gradient(45deg, #008080, #40e0d0);}
  .navbar-brand, .nav-link, .nav-item a {color: #e0f7f7 !important;}
  .btn-primary {background-color: #007b7f; border: none;}
  .btn-primary:hover {background-color: #005f5f;}
  .avatar {width: 80px; height: 80px; border-radius: 50%; object-fit: cover; border: 2px solid #40e0d0;}
  footer {background: #008080; color: #e0f7f7; text-align: center; padding: 10px 0; position: fixed; bottom: 0; width: 100%;}
  .container {padding-bottom: 70px;}
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg">
  <div class="container">
    <a class="navbar-brand fw-bold" href="{{ url_for('home') }}">Chatterbox</a>
    <ul class="navbar-nav ms-auto">
    {% if user %}
      <li class="nav-item"><a class="nav-link" href="{{ url_for('home') }}">Home</a></li>
      <li class="nav-item"><a class="nav-link" href="{{ url_for('new_post') }}">New Post</a></li>
      <li class="nav-item"><a class="nav-link" href="{{ url_for('settings') }}">Settings</a></li>
      <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></li>
    {% else %}
      <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">Login</a></li>
      <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">Register</a></li>
    {% endif %}
    </ul>
  </div>
</nav>
<div class="container mt-4">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="alert alert-info">
        {% for message in messages %}
          <div>{{ message }}</div>
        {% endfor %}
      </div>
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
<footer>
  &copy; 2025 Chatterbox by Chicken 🐔
</footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

TEMPLATE_HOME = '''
{% extends None %}
{% block content %}
<h1>Latest Posts</h1>
{% if posts %}
  <div class="list-group">
    {% for post in posts %}
      <a href="{{ url_for('post_detail', post_id=post.id) }}" class="list-group-item list-group-item-action">
        <strong>{{ post.subject }}</strong><br>
        by <a href="{{ url_for('profile', user_id=post.user_id) }}">{{ post.nickname }}</a> on {{ post.created_at.strftime('%Y-%m-%d %H:%M') }}
      </a>
    {% endfor %}
  </div>
{% else %}
  <p>No posts yet. <a href="{{ url_for('new_post') }}">Create one!</a></p>
{% endif %}
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_REGISTER = '''
{% extends None %}
{% block content %}
<h2>Register</h2>
<form method="POST" class="mb-3">
  <div class="mb-3">
    <label for="username" class="form-label">Username *</label>
    <input class="form-control" type="text" name="username" id="username" maxlength="80" required>
  </div>
  <div class="mb-3">
    <label for="password" class="form-label">Password *</label>
    <input class="form-control" type="password" name="password" id="password" required>
  </div>
  <div class="mb-3">
    <label for="confirm" class="form-label">Confirm Password *</label>
    <input class="form-control" type="password" name="confirm" id="confirm" required>
  </div>
  <div class="mb-3">
    <label for="nickname" class="form-label">Nickname *</label>
    <input class="form-control" type="text" name="nickname" id="nickname" maxlength="80" required>
  </div>
  <div class="mb-3">
    <label for="about" class="form-label">About Yourself</label>
    <textarea class="form-control" name="about" id="about" rows="3" maxlength="500"></textarea>
  </div>
  <button class="btn btn-primary" type="submit">Register</button>
  <a href="{{ url_for('login') }}" class="btn btn-secondary ms-2">Login</a>
</form>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_LOGIN = '''
{% extends None %}
{% block content %}
<h2>Login</h2>
<form method="POST" class="mb-3">
  <div class="mb-3">
    <label for="username" class="form-label">Username</label>
    <input class="form-control" type="text" name="username" id="username" required maxlength="80">
  </div>
  <div class="mb-3">
    <label for="password" class="form-label">Password</label>
    <input class="form-control" type="password" name="password" id="password" required>
  </div>
  <button class="btn btn-primary" type="submit">Login</button>
  <a href="{{ url_for('register') }}" class="btn btn-secondary ms-2">Register</a>
</form>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_NEW_POST = '''
{% extends None %}
{% block content %}
<h2>Create New Post</h2>
<form method="POST" class="mb-3">
  <div class="mb-3">
    <label for="subject" class="form-label">Subject *</label>
    <input class="form-control" type="text" name="subject" id="subject" maxlength="255" required>
  </div>
  <div class="mb-3">
    <label for="body" class="form-label">Body *</label>
    <textarea class="form-control" name="body" id="body" rows="5" required maxlength="2000"></textarea>
  </div>
  <button class="btn btn-primary" type="submit">Post</button>
  <a href="{{ url_for('home') }}" class="btn btn-secondary ms-2">Cancel</a>
</form>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_POST_DETAIL = '''
{% extends None %}
{% block content %}
<h2>{{ post.subject }}</h2>
<p class="text-muted">By <a href="{{ url_for('profile', user_id=post.user_id) }}">{{ post.nickname }}</a> on {{ post.created_at.strftime('%Y-%m-%d %H:%M') }}</p>
<div class="mb-4">{{ post.body|e|replace('\\n', '<br>')|safe }}</div>

<h4>Comments</h4>
{% if comments %}
  <ul class="list-group mb-4">
  {% for comment in comments %}
    <li class="list-group-item">
      <strong><a href="{{ url_for('profile', user_id=comment.user_id) }}">{{ comment.nickname }}</a></strong> 
      <small class="text-muted">{{ comment.created_at.strftime('%Y-%m-%d %H:%M') }}</small><br>
      {{ comment.body|e|replace('\\n', '<br>')|safe }}
    </li>
  {% endfor %}
  </ul>
{% else %}
  <p>No comments yet.</p>
{% endif %}

<form method="POST" class="mb-3">
  <div class="mb-3">
    <label for="comment" class="form-label">Add a comment</label>
    <textarea class="form-control" id="comment" name="comment" rows="3" maxlength="1000" required></textarea>
  </div>
  <button type="submit" class="btn btn-primary">Submit Comment</button>
  <a href="{{ url_for('home') }}" class="btn btn-secondary ms-2">Back to Home</a>
</form>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_PROFILE = '''
{% extends None %}
{% block content %}
<h2>{{ profile.nickname }}'s Profile</h2>
{% if profile.avatar %}
  <img src="{{ url_for('avatar', filename=profile.avatar) }}" alt="Avatar" class="avatar mb-3">
{% else %}
  <div class="avatar bg-secondary text-white d-flex align-items-center justify-content-center mb-3" style="font-size: 2rem;">
    {{ profile.nickname[0]|upper }}
  </div>
{% endif %}
<p><strong>Username:</strong> {{ profile.username }}</p>
{% if profile.about %}
<p><strong>About:</strong><br>{{ profile.about|e|replace('\\n', '<br>')|safe }}</p>
{% endif %}
<a href="{{ url_for('home') }}" class="btn btn-secondary">Back to Home</a>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_SETTINGS = '''
{% extends None %}
{% block content %}
<h2>Settings</h2>
<form method="POST" enctype="multipart/form-data" class="mb-5">
  <div class="mb-3">
    <label for="nickname" class="form-label">Nickname</label>
    <input type="text" class="form-control" id="nickname" name="nickname" value="{{ user.nickname }}" maxlength="80" required>
  </div>
  <div class="mb-3">
    <label for="about" class="form-label">About</label>
    <textarea class="form-control" id="about" name="about" rows="4" maxlength="500">{{ user.about }}</textarea>
  </div>
  <div class="mb-3">
    <label for="avatar" class="form-label">Avatar (png, jpg, jpeg, gif)</label>
    <input class="form-control" type="file" id="avatar" name="avatar" accept=".png,.jpg,.jpeg,.gif">
  </div>
  {% if user.avatar %}
    <p>Current avatar:</p>
    <img src="{{ url_for('avatar', filename=user.avatar) }}" alt="avatar" class="avatar mb-3">
  {% endif %}
  <button type="submit" class="btn btn-primary">Save Changes</button>
  <a href="{{ url_for('home') }}" class="btn btn-secondary ms-2">Cancel</a>
</form>
{% endblock %}
''' + TEMPLATE_BASE

if __name__ == "__main__":
    app.run(debug=True)

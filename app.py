import os
import uuid
from flask import (
    Flask, render_template_string, request, redirect, url_for,
    session, flash, send_from_directory, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")

UPLOAD_FOLDER = 'avatars'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

conn = psycopg2.connect(DATABASE_URL, sslmode='require')
conn.autocommit = True

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def init_db():
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            nickname TEXT,
            about TEXT,
            avatar TEXT
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id),
            body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""")

init_db()

def get_user_by_username(username):
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        return cur.fetchone()

def get_user_by_id(uid):
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (uid,))
        return cur.fetchone()

@app.route('/')
def home():
    if "user_id" not in session:
        return redirect(url_for('login'))
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""
            SELECT posts.*, users.nickname FROM posts
            JOIN users ON posts.user_id = users.id
            ORDER BY posts.created_at DESC
        """)
        posts = cur.fetchall()
    user = get_user_by_id(session["user_id"])
    return render_template_string(TEMPLATE_HOME, posts=posts, user=user)

@app.route('/register', methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        nickname = request.form.get("nickname", "").strip()
        about = request.form.get("about", "").strip()
        if not username or not password or not confirm:
            flash("Username and password are required.", "danger")
            return redirect(url_for('register'))
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for('register'))
        if get_user_by_username(username):
            flash("Username already taken.", "danger")
            return redirect(url_for('register'))
        hashed = generate_password_hash(password)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password, nickname, about) VALUES (%s, %s, %s, %s)",
                (username, hashed, nickname, about)
            )
        flash("Registration successful! Please login.", "success")
        return redirect(url_for('login'))
    return render_template_string(TEMPLATE_REGISTER)

@app.route('/login', methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_user_by_username(username)
        if user is None or not check_password_hash(user['password'], password):
            flash("Invalid username or password.", "danger")
            return redirect(url_for('login'))
        session["user_id"] = user["id"]
        flash(f"Welcome back, {user['nickname'] or user['username']}!", "success")
        return redirect(url_for('home'))
    return render_template_string(TEMPLATE_LOGIN)

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for('login'))

@app.route('/avatars/<filename>')
def avatar(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/profile/<int:uid>')
def profile(uid):
    user = get_user_by_id(uid)
    if not user:
        abort(404)
    current_user = get_user_by_id(session.get("user_id")) if "user_id" in session else None
    return render_template_string(TEMPLATE_PROFILE, profile=user, user=current_user)

@app.route('/settings', methods=["GET","POST"])
def settings():
    if "user_id" not in session:
        return redirect(url_for('login'))
    user = get_user_by_id(session["user_id"])
    if request.method == "POST":
        nickname = request.form.get("nickname", "").strip()
        about = request.form.get("about", "").strip()
        avatar_file = request.files.get("avatar")
        avatar_filename = user['avatar']

        if avatar_file and allowed_file(avatar_file.filename):
            filename = secure_filename(avatar_file.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            avatar_file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
            avatar_filename = unique_filename

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users SET nickname = %s, about = %s, avatar = %s WHERE id = %s
            """, (nickname, about, avatar_filename, user['id']))
        flash("Settings updated.", "success")
        return redirect(url_for('settings'))
    return render_template_string(TEMPLATE_SETTINGS, user=user)

@app.route('/post/<int:post_id>', methods=["GET", "POST"])
def post_detail(post_id):
    if "user_id" not in session:
        return redirect(url_for('login'))
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""
            SELECT posts.*, users.nickname FROM posts JOIN users ON posts.user_id = users.id WHERE posts.id = %s
        """, (post_id,))
        post = cur.fetchone()
        if not post:
            abort(404)
        if request.method == "POST":
            body = request.form.get("body", "").strip()
            if body:
                cur.execute(
                    "INSERT INTO comments (post_id, user_id, body) VALUES (%s, %s, %s)",
                    (post_id, session["user_id"], body)
                )
                flash("Comment added.", "success")
                return redirect(url_for('post_detail', post_id=post_id))
        cur.execute("""
            SELECT comments.*, users.nickname FROM comments JOIN users ON comments.user_id = users.id
            WHERE post_id = %s ORDER BY created_at ASC
        """, (post_id,))
        comments = cur.fetchall()
    user = get_user_by_id(session["user_id"])
    return render_template_string(TEMPLATE_POST_DETAIL, post=post, comments=comments, user=user)

@app.route('/new_post', methods=["GET","POST"])
def new_post():
    if "user_id" not in session:
        return redirect(url_for('login'))
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        if not subject or not body:
            flash("Subject and body are required.", "danger")
            return redirect(url_for('new_post'))
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO posts (user_id, subject, body) VALUES (%s, %s, %s)",
                (session["user_id"], subject, body)
            )
        flash("Post created.", "success")
        return redirect(url_for('home'))
    user = get_user_by_id(session["user_id"])
    return render_template_string(TEMPLATE_NEW_POST, user=user)

@app.errorhandler(404)
def not_found(e):
    return render_template_string(TEMPLATE_404), 404

# --- TEMPLATES ---
# Blue-green with white background theme

TEMPLATE_BASE = '''
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{{ title or "Chatterbox" }}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
<style>
  body {
    background: #f9fefa;
    color: #114b5f;
  }
  .navbar, .footer {
    background: linear-gradient(45deg, #56ab2f, #a8e063);
    color: white !important;
  }
  .navbar a, .footer a {
    color: white !important;
  }
  .avatar {
    width: 50px;
    height: 50px;
    border-radius: 50%;
    object-fit: cover;
  }
  .post-subject {
    color: #1f8a70;
  }
  .btn-primary {
    background: #1f8a70;
    border: none;
  }
  .btn-primary:hover {
    background: #16664e;
  }
  footer.footer {
    position: fixed;
    bottom: 0;
    width: 100%;
    padding: 10px 0;
    text-align: center;
  }
  .comment {
    background: #e8f5e9;
    border-radius: 8px;
    padding: 10px;
    margin-bottom: 8px;
  }
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg mb-4">
  <div class="container">
    <a class="navbar-brand fw-bold" href="{{ url_for('home') }}">Chatterbox</a>
    <div>
      {% if user %}
        <a href="{{ url_for('profile', uid=user.id) }}" class="me-3">{{ user.nickname or user.username }}</a>
        <a href="{{ url_for('new_post') }}" class="btn btn-sm btn-primary me-2">New Post</a>
        <a href="{{ url_for('settings') }}" class="btn btn-sm btn-primary me-2">Settings</a>
        <a href="{{ url_for('logout') }}" class="btn btn-sm btn-danger">Logout</a>
      {% else %}
        <a href="{{ url_for('login') }}" class="btn btn-sm btn-primary me-2">Login</a>
        <a href="{{ url_for('register') }}" class="btn btn-sm btn-primary">Register</a>
      {% endif %}
    </div>
  </div>
</nav>
<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, msg in messages %}
        <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
<footer class="footer bg-success text-white mt-5">
  <div class="container">© 2025 Chatterbox by Chicken</div>
</footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

TEMPLATE_LOGIN = '''
{% extends None %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-5">
    <h2>Login</h2>
    <form method="POST">
      <div class="mb-3">
        <label>Username</label>
        <input type="text" name="username" class="form-control" required autofocus />
      </div>
      <div class="mb-3">
        <label>Password</label>
        <input type="password" name="password" class="form-control" required />
      </div>
      <button class="btn btn-primary w-100" type="submit">Login</button>
    </form>
    <p class="mt-3">Don't have an account? <a href="{{ url_for('register') }}">Register here</a>.</p>
  </div>
</div>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_REGISTER = '''
{% extends None %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h2>Register</h2>
    <form method="POST">
      <div class="mb-3">
        <label>Username</label>
        <input type="text" name="username" class="form-control" required autofocus />
      </div>
      <div class="mb-3">
        <label>Password</label>
        <input type="password" name="password" class="form-control" required />
      </div>
      <div class="mb-3">
        <label>Confirm Password</label>
        <input type="password" name="confirm" class="form-control" required />
      </div>
      <div class="mb-3">
        <label>Nickname (optional)</label>
        <input type="text" name="nickname" class="form-control" />
      </div>
      <div class="mb-3">
        <label>About you (optional)</label>
        <textarea name="about" class="form-control"></textarea>
      </div>
      <button class="btn btn-primary w-100" type="submit">Register</button>
    </form>
    <p class="mt-3">Already have an account? <a href="{{ url_for('login') }}">Login here</a>.</p>
  </div>
</div>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_HOME = '''
{% extends None %}
{% block content %}
<h1>Posts</h1>
{% if posts %}
  <div class="list-group">
  {% for p in posts %}
    <a href="{{ url_for('post_detail', post_id=p.id) }}" class="list-group-item list-group-item-action mb-2">
      <h5 class="post-subject">{{ p.subject }}</h5>
      <small>by {{ p.nickname or "Anonymous" }} on {{ p.created_at.strftime('%Y-%m-%d %H:%M') }}</small>
      <p>{{ p.body[:150] }}{% if p.body|length > 150 %}...{% endif %}</p>
    </a>
  {% endfor %}
  </div>
{% else %}
  <p>No posts yet. <a href="{{ url_for('new_post') }}">Create one!</a></p>
{% endif %}
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_NEW_POST = '''
{% extends None %}
{% block content %}
<h2>Create New Post</h2>
<form method="POST">
  <div class="mb-3">
    <label>Subject</label>
    <input type="text" name="subject" class="form-control" required autofocus />
  </div>
  <div class="mb-3">
    <label>Body</label>
    <textarea name="body" class="form-control" rows="6" required></textarea>
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
<p><small>by {{ post.nickname or "Anonymous" }} on {{ post.created_at.strftime('%Y-%m-%d %H:%M') }}</small></p>
<p>{{ post.body }}</p>

<hr />
<h4>Comments</h4>
{% if comments %}
  {% for c in comments %}
    <div class="comment">
      <strong>{{ c.nickname or "Anonymous" }}</strong> <small>{{ c.created_at.strftime('%Y-%m-%d %H:%M') }}</small>
      <p>{{ c.body }}</p>
    </div>
  {% endfor %}
{% else %}
  <p>No comments yet.</p>
{% endif %}

<hr />
<h5>Add a Comment</h5>
<form method="POST">
  <textarea name="body" class="form-control" rows="3" required></textarea>
  <button class="btn btn-primary mt-2" type="submit">Submit</button>
</form>
<a href="{{ url_for('home') }}" class="btn btn-secondary mt-3">Back to Posts</a>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_PROFILE = '''
{% extends None %}
{% block content %}
<h2>Profile: {{ profile.nickname or profile.username }}</h2>
<div class="d-flex align-items-center mb-3">
  {% if profile.avatar %}
    <img src="{{ url_for('avatar', filename=profile.avatar) }}" alt="Avatar" class="avatar me-3" />
  {% else %}
    <div class="avatar bg-secondary text-white d-flex justify-content-center align-items-center me-3">?</div>
  {% endif %}
  <div>
    <p><strong>Username:</strong> {{ profile.username }}</p>
    <p><strong>Nickname:</strong> {{ profile.nickname or "N/A" }}</p>
  </div>
</div>
<h4>About</h4>
<p>{{ profile.about or "No info provided." }}</p>
<a href="{{ url_for('home') }}" class="btn btn-secondary mt-3">Back Home</a>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_SETTINGS = '''
{% extends None %}
{% block content %}
<h2>Settings</h2>
<form method="POST" enctype="multipart/form-data">
  <div class="mb-3">
    <label>Nickname</label>
    <input type="text" name="nickname" class="form-control" value="{{ user.nickname or '' }}" />
  </div>
  <div class="mb-3">
    <label>About You</label>
    <textarea name="about" class="form-control">{{ user.about or '' }}</textarea>
  </div>
  <div class="mb-3">
    <label>Avatar</label><br />
    {% if user.avatar %}
      <img src="{{ url_for('avatar', filename=user.avatar) }}" class="avatar mb-2" alt="Current avatar" />
    {% endif %}
    <input type="file" name="avatar" class="form-control" accept="image/*" />
  </div>
  <button class="btn btn-primary" type="submit">Save</button>
  <a href="{{ url_for('home') }}" class="btn btn-secondary ms-2">Cancel</a>
</form>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_404 = '''
{% extends None %}
{% block content %}
<h2>404 - Not Found</h2>
<p>Sorry, the page you are looking for does not exist.</p>
<a href="{{ url_for('home') }}" class="btn btn-primary">Home</a>
{% endblock %}
''' + TEMPLATE_BASE

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=True)

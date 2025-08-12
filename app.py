import os
from flask import (
    Flask, request, redirect, url_for, session,
    send_from_directory, abort, flash, render_template_string
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import psycopg2
import psycopg2.extras
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_change_me")

app.config['UPLOAD_FOLDER'] = 'avatars'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(80) UNIQUE NOT NULL,
            password_hash VARCHAR(128) NOT NULL,
            nickname VARCHAR(80) NOT NULL,
            about TEXT,
            avatar VARCHAR(256)
        );
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            body TEXT NOT NULL,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    cur.close()
    conn.close()

init_db()

def query_db(query, args=(), one=False, commit=False):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute(query, args)
    if commit:
        conn.commit()
        cur.close()
        conn.close()
        return
    rv = cur.fetchall()
    cur.close()
    conn.close()
    return (rv[0] if rv else None) if one else rv

def get_user_by_username(username):
    return query_db('SELECT * FROM users WHERE username = %s', (username,), one=True)

def get_user_by_id(user_id):
    return query_db('SELECT * FROM users WHERE id = %s', (user_id,), one=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

def login_required(func):
    from functools import wraps
    @wraps(func)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please login first.")
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return decorated

@app.route('/avatars/<filename>')
def avatar(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
@login_required
def home():
    posts = query_db('''
        SELECT posts.*, users.nickname, users.id AS user_id FROM posts
        JOIN users ON posts.user_id = users.id
        ORDER BY posts.created DESC
    ''')
    user = get_user_by_id(session['user_id'])
    return render_template_string(TEMPLATE_HOME, posts=posts, user=user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        nickname = request.form.get('nickname', '').strip()
        about = request.form.get('about', '').strip()

        if not username or not password or not confirm or not nickname:
            flash("Please fill all required fields.")
            return redirect(url_for('register'))

        if password != confirm:
            flash("Passwords do not match.")
            return redirect(url_for('register'))

        if get_user_by_username(username):
            flash("Username already taken.")
            return redirect(url_for('register'))

        avatar_filename = None
        avatar_file = request.files.get('avatar')
        if avatar_file and avatar_file.filename != '' and allowed_file(avatar_file.filename):
            filename = secure_filename(avatar_file.filename)
            avatar_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            avatar_file.save(avatar_path)
            avatar_filename = filename

        password_hash = generate_password_hash(password)

        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO users (username, password_hash, nickname, about, avatar)
            VALUES (%s, %s, %s, %s, %s)
        ''', (username, password_hash, nickname, about, avatar_filename))
        conn.commit()
        cur.close()
        conn.close()
        flash("Registered successfully! Please log in.")
        return redirect(url_for('login'))

    return render_template_string(TEMPLATE_REGISTER)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = get_user_by_username(username)
        if not user or not check_password_hash(user['password_hash'], password):
            flash("Invalid username or password.")
            return redirect(url_for('login'))

        session['user_id'] = user['id']
        flash(f"Welcome back, {user['nickname']}!")
        return redirect(url_for('home'))

    return render_template_string(TEMPLATE_LOGIN)

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash("Logged out successfully.")
    return redirect(url_for('login'))

@app.route('/post/create', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        body = request.form.get('body', '').strip()

        if not subject or not body:
            flash("Subject and body cannot be empty.")
            return redirect(url_for('create_post'))

        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO posts (user_id, subject, body)
            VALUES (%s, %s, %s)
        ''', (session['user_id'], subject, body))
        conn.commit()
        cur.close()
        conn.close()

        flash("Post created successfully.")
        return redirect(url_for('home'))

    return render_template_string(TEMPLATE_CREATE_POST)

@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
@login_required
def view_post(post_id):
    post = query_db('''
        SELECT posts.*, users.nickname, users.id AS user_id FROM posts
        JOIN users ON posts.user_id = users.id
        WHERE posts.id = %s
    ''', (post_id,), one=True)
    if not post:
        abort(404)

    comments = query_db('''
        SELECT comments.*, users.nickname, users.id AS user_id FROM comments
        JOIN users ON comments.user_id = users.id
        WHERE comments.post_id = %s
        ORDER BY comments.created ASC
    ''', (post_id,))

    if request.method == 'POST':
        comment_body = request.form.get('comment', '').strip()
        if comment_body == '':
            flash("Comment cannot be empty.")
            return redirect(url_for('view_post', post_id=post_id))

        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO comments (post_id, user_id, body)
            VALUES (%s, %s, %s)
        ''', (post_id, session['user_id'], comment_body))
        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for('view_post', post_id=post_id))

    user = get_user_by_id(session['user_id'])
    return render_template_string(TEMPLATE_VIEW_POST, post=post, comments=comments, user=user)

@app.route('/profile/<int:user_id>')
@login_required
def profile(user_id):
    profile = get_user_by_id(user_id)
    if not profile:
        abort(404)
    return render_template_string(TEMPLATE_PROFILE, profile=profile)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user = get_user_by_id(session['user_id'])
    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip()
        about = request.form.get('about', '').strip()

        if not nickname:
            flash("Nickname cannot be empty.")
            return redirect(url_for('settings'))

        avatar_filename = user['avatar']
        avatar_file = request.files.get('avatar')
        if avatar_file and avatar_file.filename != '' and allowed_file(avatar_file.filename):
            filename = secure_filename(avatar_file.filename)
            avatar_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            avatar_file.save(avatar_path)
            avatar_filename = filename

        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            UPDATE users SET nickname = %s, about = %s, avatar = %s WHERE id = %s
        ''', (nickname, about, avatar_filename, session['user_id']))
        conn.commit()
        cur.close()
        conn.close()

        flash("Profile updated.")
        return redirect(url_for('settings'))

    return render_template_string(TEMPLATE_SETTINGS, user=user)

# --- Inline Templates ---

TEMPLATE_BASE = '''
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Chatterbox - {{ title or "Home" }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <!-- Bootstrap 5 CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { background: white; color: #054a29; }
      .navbar { background: linear-gradient(45deg, #00796b, #004d40); }
      .navbar-brand, .nav-link, .nav-item { color: #a5d6a7 !important; }
      .btn-primary { background-color: #00796b; border-color: #004d40; }
      .btn-primary:hover { background-color: #004d40; border-color: #00251a; }
      .avatar { width: 60px; height: 60px; border-radius: 50%; object-fit: cover; }
      footer { position: fixed; bottom: 0; width: 100%; background: #004d40; color: white; padding: 0.5rem 0; text-align: center;}
      .container { padding-bottom: 60px; }
    </style>
</head>
<body>
<nav class="navbar navbar-expand-lg">
  <div class="container">
    <a class="navbar-brand fw-bold" href="{{ url_for('home') }}">Chatterbox</a>
    <ul class="navbar-nav ms-auto">
      {% if session.get('user_id') %}
      <li class="nav-item"><a class="nav-link" href="{{ url_for('home') }}">Home</a></li>
      <li class="nav-item"><a class="nav-link" href="{{ url_for('create_post') }}">New Post</a></li>
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
          {% for msg in messages %}
            <div>{{ msg }}</div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
</div>

<footer>
    &copy; 2025 Chatterbox by Chicken
</footer>

<!-- Bootstrap 5 JS bundle -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

TEMPLATE_HOME = '''
{% extends None %}
{% block content %}
<h2>Recent Posts</h2>
{% if posts %}
  <div class="list-group">
    {% for post in posts %}
    <a href="{{ url_for('view_post', post_id=post.id) }}" class="list-group-item list-group-item-action">
      <h5 class="mb-1">{{ post.subject }}</h5>
      <small>By <a href="{{ url_for('profile', user_id=post.user_id) }}">{{ post.nickname }}</a> on {{ post.created.strftime('%Y-%m-%d %H:%M') }}</small>
      <p class="mb-1 text-truncate" style="max-width:600px;">{{ post.body }}</p>
    </a>
    {% endfor %}
  </div>
{% else %}
  <p>No posts yet. <a href="{{ url_for('create_post') }}">Create one</a>.</p>
{% endif %}
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_REGISTER = '''
{% extends None %}
{% block content %}
<h2>Register</h2>
<form method="POST" enctype="multipart/form-data" class="mb-5">
  <div class="mb-3">
    <label for="username" class="form-label">Username *</label>
    <input class="form-control" type="text" name="username" id="username" required maxlength="80">
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
    <input class="form-control" type="text" name="nickname" id="nickname" required maxlength="80">
  </div>
  <div class="mb-3">
    <label for="about" class="form-label">About Yourself</label>
    <textarea class="form-control" name="about" id="about" rows="3" maxlength="500"></textarea>
  </div>
  <div class="mb-3">
    <label for="avatar" class="form-label">Avatar (optional, image files only)</label>
    <input class="form-control" type="file" name="avatar" id="avatar" accept="image/*">
  </div>
  <button class="btn btn-primary" type="submit">Register</button>
  <a href="{{ url_for('login') }}" class="btn btn-secondary ms-2">Already have an account? Login</a>
</form>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_LOGIN = '''
{% extends None %}
{% block content %}
<h2>Login</h2>
<form method="POST" class="mb-5">
  <div class="mb-3">
    <label for="username" class="form-label">Username</label>
    <input class="form-control" type="text" name="username" id="username" required maxlength="80">
  </div>
  <div class="mb-3">
    <label for="password" class="form-label">Password</label>
    <input class="form-control" type="password" name="password" id="password" required>
  </div>
  <button class="btn btn-primary" type="submit">Login</button>
  <a href="{{ url_for('register') }}" class="btn btn-secondary ms-2">Register here</a>
</form>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_CREATE_POST = '''
{% extends None %}
{% block content %}
<h2>Create Post</h2>
<form method="POST" class="mb-5">
  <div class="mb-3">
    <label for="subject" class="form-label">Subject</label>
    <input class="form-control" name="subject" id="subject" required maxlength="200">
  </div>
  <div class="mb-3">
    <label for="body" class="form-label">Body</label>
    <textarea class="form-control" name="body" id="body" rows="6" required maxlength="2000"></textarea>
  </div>
  <button class="btn btn-primary" type="submit">Submit</button>
  <a href="{{ url_for('home') }}" class="btn btn-secondary ms-2">Cancel</a>
</form>
{% endblock %}
''' + TEMPLATE_BASE

TEMPLATE_VIEW_POST = '''
{% extends None %}
{% block content %}
<h2>{{ post.subject }}</h2>
<p>By <a href="{{ url_for('profile', user_id=post.user_id) }}">{{ post.nickname }}</a> on {{ post.created.strftime('%Y-%m-%d %H:%M') }}</p>
<div class="mb-4" style="white-space: pre-wrap;">{{ post.body }}</div>

<h4>Comments</h4>
{% if comments %}
  <ul class="list-group mb-4">
    {% for comment in comments %}
    <li class="list-group-item">
      <strong><a href="{{ url_for('profile', user_id=comment.user_id) }}">{{ comment.nickname }}</a>:</strong>
      <span>{{ comment.body }}</span>
      <small class="text-muted float-end">{{ comment.created.strftime('%Y-%m-%d %H:%M') }}</small>
    </li>
    {% endfor %}
  </ul>
{% else %}
  <p>No comments yet.</p>
{% endif %}

<form method="POST">
  <div class="mb-3">
    <label for="comment" class="form-label">Add a comment</label>
    <textarea class="form-control" id="comment" name="comment" rows="3" maxlength="1000" required></textarea>
  </div>
  <button type="submit" class="btn btn-primary">Submit Comment</button>
  <a href="{{ url_for('home') }}" class="btn btn-secondary ms-2">Back to Posts</a>
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
<p><strong>About:</strong><br>{{ profile.about|e|replace('\n', '<br>')|safe }}</p>
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
    <label for="nickname" class="form-label">Nickname *</label>
    <input class="form-control" type="text" name="nickname" id="nickname" value="{{ user.nickname }}" required maxlength="80">
  </div>
  <div class="mb-3">
    <label for="about" class="form-label">About Yourself</label>
    <textarea class="form-control" name="about" id="about" rows="4" maxlength="500">{{ user.about }}</textarea>
  </div>
  <div class="mb-3">
    <label for="avatar" class="form-label">Change Avatar (optional)</label>
    <input class="form-control" type="file" name="avatar" id="avatar" accept="image/*">
  </div>
  {% if user.avatar %}
  <p>Current Avatar:</p>
  <img src="{{ url_for('avatar', filename=user.avatar) }}" alt="Current avatar" class="avatar mb-3">
  {% endif %}
  <button class="btn btn-primary" type="submit">Save Changes</button>
  <a href="{{ url_for('home') }}" class="btn btn-secondary ms-2">Cancel</a>
</form>
{% endblock %}
''' + TEMPLATE_BASE

if __name__ == '__main__':
    app.run(debug=True)

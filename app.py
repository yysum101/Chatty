import os
import base64
import hashlib
import secrets
from io import BytesIO
from datetime import datetime

from flask import Flask, render_template_string, request, redirect, url_for, session, flash
import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL environment variable not set")

def get_db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def init_db():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(50) UNIQUE NOT NULL,
        password_hash VARCHAR(64) NOT NULL,
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
    conn.commit()
    cur.close()
    conn.close()

init_db()

def allowed_file(filename):
    allowed_exts = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_exts

@app.route('/')
def home():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT posts.*, users.nickname, users.avatar_base64, users.username FROM posts
        JOIN users ON posts.user_id = users.id
        ORDER BY posts.created_at DESC
        LIMIT 20;
    """)
    posts = cur.fetchall()
    cur.close()
    conn.close()
    return render_template_string(HOME_HTML, posts=posts, session=session)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        confirm = request.form['confirm']
        about = request.form['about'].strip()
        nickname = request.form['nickname'].strip()
        avatar = request.files.get('avatar')

        if password != confirm:
            flash("Passwords do not match!", "danger")
            return redirect(url_for('register'))

        avatar_b64 = None
        if avatar and allowed_file(avatar.filename):
            avatar_bytes = avatar.read()
            avatar_b64 = base64.b64encode(avatar_bytes).decode('utf-8')

        pw_hash = hash_password(password)

        try:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, password_hash, about, nickname, avatar_base64) VALUES (%s,%s,%s,%s,%s)",
                        (username, pw_hash, about, nickname, avatar_b64))
            conn.commit()
            cur.close()
            conn.close()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for('login'))
        except psycopg2.errors.UniqueViolation:
            flash("Username already exists.", "danger")
            return redirect(url_for('register'))

    return render_template_string(REGISTER_HTML)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        pw_hash = hash_password(password)

        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s AND password_hash = %s", (username, pw_hash))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['nickname'] = user['nickname']
            session['avatar_base64'] = user['avatar_base64']
            flash("Logged in successfully!", "success")
            return redirect(url_for('home'))
        else:
            flash("Invalid username or password", "danger")
            return redirect(url_for('login'))

    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for('home'))

@app.route('/post', methods=['GET', 'POST'])
def post():
    if 'user_id' not in session:
        flash("You must be logged in to post.", "warning")
        return redirect(url_for('login'))
    if request.method == 'POST':
        subject = request.form['subject'].strip()
        body = request.form['body'].strip()
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO posts (user_id, subject, body) VALUES (%s, %s, %s)", (session['user_id'], subject, body))
        conn.commit()
        cur.close()
        conn.close()
        flash("Post created!", "success")
        return redirect(url_for('home'))
    return render_template_string(POST_HTML)

@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def post_detail(post_id):
    conn = get_db_conn()
    cur = conn.cursor()
    if request.method == 'POST':
        if 'user_id' not in session:
            flash("You must be logged in to comment.", "warning")
            return redirect(url_for('login'))
        comment = request.form['comment'].strip()
        cur.execute("INSERT INTO comments (post_id, user_id, comment) VALUES (%s, %s, %s)",
                    (post_id, session['user_id'], comment))
        conn.commit()
        flash("Comment added!", "success")

    cur.execute("""
        SELECT posts.*, users.nickname, users.avatar_base64, users.username FROM posts
        JOIN users ON posts.user_id = users.id
        WHERE posts.id = %s
    """, (post_id,))
    post = cur.fetchone()

    cur.execute("""
        SELECT comments.*, users.nickname, users.avatar_base64, users.username FROM comments
        JOIN users ON comments.user_id = users.id
        WHERE comments.post_id = %s
        ORDER BY comments.created_at ASC
    """, (post_id,))
    comments = cur.fetchall()
    cur.close()
    conn.close()

    return render_template_string(POST_DETAIL_HTML, post=post, comments=comments, session=session)

# ---- Inline Templates Below ----

HOME_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Chatterbox Home</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
  <style>
    body {
      background: linear-gradient(135deg, #b71c1c, #fbc02d);
      color: #222;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    .container {
      margin-top: 2rem;
      flex: 1 0 auto;
    }
    footer {
      flex-shrink: 0;
      padding: 1rem;
      background: #b71c1c;
      color: white;
      text-align: center;
      border-top: 3px solid #fbc02d;
      margin-top: auto;
    }
    .avatar {
      width: 50px; height: 50px;
      border-radius: 50%;
      object-fit: cover;
      border: 2px solid #fbc02d;
    }
    .post-card {
      background: rgba(255,255,255,0.9);
      padding: 1rem;
      margin-bottom: 1rem;
      border-radius: 15px;
      box-shadow: 0 0 15px #b71c1c;
    }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark" style="background:#b71c1c;">
  <div class="container">
    <a class="navbar-brand fw-bold" href="{{ url_for('home') }}">Chatterbox</a>
    <div>
      {% if session.get('user_id') %}
        <span class="text-warning me-3">Hi, {{ session.get('nickname') or session.get('username') }}</span>
        <a href="{{ url_for('post') }}" class="btn btn-warning btn-sm me-2">New Post</a>
        <a href="{{ url_for('logout') }}" class="btn btn-outline-warning btn-sm">Logout</a>
      {% else %}
        <a href="{{ url_for('login') }}" class="btn btn-warning btn-sm me-2">Login</a>
        <a href="{{ url_for('register') }}" class="btn btn-outline-warning btn-sm">Register</a>
      {% endif %}
    </div>
  </div>
</nav>
<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, message in messages %}
        <div class="alert alert-{{category}} alert-dismissible fade show" role="alert">
          {{ message }}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  {% for post in posts %}
  <div class="post-card">
    <div class="d-flex align-items-center mb-2">
      {% if post.avatar_base64 %}
      <img src="data:image/png;base64,{{ post.avatar_base64 }}" alt="avatar" class="avatar me-3" />
      {% else %}
      <div class="avatar bg-warning d-flex justify-content-center align-items-center fw-bold text-dark me-3">?</div>
      {% endif %}
      <strong>{{ post.nickname or post.username }}</strong>
      <small class="text-muted ms-auto">{{ post.created_at.strftime('%Y-%m-%d %H:%M') }}</small>
    </div>
    <h5>{{ post.subject }}</h5>
    <p>{{ post.body }}</p>
    <a href="{{ url_for('post_detail', post_id=post.id) }}" class="btn btn-sm btn-danger">View & Comment</a>
  </div>
  {% else %}
  <p>No posts yet.</p>
  {% endfor %}
</div>
<footer>© 2025 Chatterbox by Chicken</footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

REGISTER_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
  <meta charset="UTF-8" />
  <title>Register - Chatterbox</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
  <style>
    body {background: linear-gradient(135deg, #b71c1c, #fbc02d); color:#222;}
    .form-container {
      max-width: 450px;
      margin: 3rem auto;
      background: rgba(255,255,255,0.9);
      padding: 2rem;
      border-radius: 15px;
      box-shadow: 0 0 15px #b71c1c;
    }
  </style>
</head>
<body>
<div class="form-container">
  <h2 class="mb-4">Register</h2>
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, message in messages %}
        <div class="alert alert-{{category}} alert-dismissible fade show" role="alert">
          {{ message }}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  <form method="post" enctype="multipart/form-data">
    <div class="mb-3">
      <label>Username</label>
      <input type="text" name="username" class="form-control" required maxlength="50" />
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
      <label>Tell us about yourself</label>
      <textarea name="about" class="form-control" rows="3"></textarea>
    </div>
    <div class="mb-3">
      <label>Nickname</label>
      <input type="text" name="nickname" class="form-control" maxlength="50" />
    </div>
    <div class="mb-3">
      <label>Avatar (optional)</label>
      <input type="file" name="avatar" accept="image/*" class="form-control" />
      <small class="text-muted">Allowed: png, jpg, jpeg, gif</small>
    </div>
    <button type="submit" class="btn btn-danger w-100">Register</button>
  </form>
  <p class="mt-3 text-center">Already have an account? <a href="{{ url_for('login') }}">Login here</a>.</p>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
  <meta charset="UTF-8" />
  <title>Login - Chatterbox</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
  <style>
    body {background: linear-gradient(135deg, #b71c1c, #fbc02d); color:#222;}
    .form-container {
      max-width: 400px;
      margin: 4rem auto;
      background: rgba(255,255,255,0.9);
      padding: 2rem;
      border-radius: 15px;
      box-shadow: 0 0 15px #b71c1c;
    }
  </style>
</head>
<body>
<div class="form-container">
  <h2 class="mb-4">Login</h2>
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, message in messages %}
        <div class="alert alert-{{category}} alert-dismissible fade show" role="alert">
          {{ message }}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  <form method="post">
    <div class="mb-3">
      <label>Username</label>
      <input type="text" name="username" class="form-control" required maxlength="50" />
    </div>
    <div class="mb-3">
      <label>Password</label>
      <input type="password" name="password" class="form-control" required />
    </div>
    <button type="submit" class="btn btn-danger w-100">Login</button>
  </form>
  <p class="mt-3 text-center">Don't have an account? <a href="{{ url_for('register') }}">Register here</a>.</p>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>
"""

POST_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
  <meta charset="UTF-8" />
  <title>New Post - Chatterbox</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
  <style>
    body {background: linear-gradient(135deg, #b71c1c, #fbc02d); color:#222;}
    .form-container {
      max-width: 600px;
      margin: 3rem auto;
      background: rgba(255,255,255,0.9);
      padding: 2rem;
      border-radius: 15px;
      box-shadow: 0 0 15px #b71c1c;
    }
  </style>
</head>
<body>
<div class="form-container">
  <h2 class="mb-4">Create New Post</h2>
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, message in messages %}
        <div class="alert alert-{{category}} alert-dismissible fade show" role="alert">
          {{ message }}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  <form method="post">
    <div class="mb-3">
      <label>Subject</label>
      <input type="text" name="subject" class="form-control" required maxlength="200" />
    </div>
    <div class="mb-3">
      <label>Body</label>
      <textarea name="body" rows="5" class="form-control" required></textarea>
    </div>
    <button type="submit" class="btn btn-danger w-100">Post</button>
  </form>
  <p class="mt-3 text-center"><a href="{{ url_for('home') }}">Back to Home</a></p>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>
"""

POST_DETAIL_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
  <meta charset="UTF-8" />
  <title>Post Detail - Chatterbox</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
  <style>
    body {background: linear-gradient(135deg, #b71c1c, #fbc02d); color:#222;}
    .container {
      max-width: 700px;
      margin: 2rem auto;
      background: rgba(255,255,255,0.9);
      padding: 2rem;
      border-radius: 15px;
      box-shadow: 0 0 15px #b71c1c;
    }
    .avatar {
      width: 40px; height: 40px;
      border-radius: 50%;
      object-fit: cover;
      border: 2px solid #fbc02d;
    }
    .comment {
      border-bottom: 1px solid #fbc02d;
      padding-bottom: 0.5rem;
      margin-bottom: 0.5rem;
    }
  </style>
</head>
<body>
<div class="container">
  <h3>{{ post.subject }}</h3>
  <div class="d-flex align-items-center mb-3">
    {% if post.avatar_base64 %}
    <img src="data:image/png;base64,{{ post.avatar_base64 }}" alt="avatar" class="avatar me-3" />
    {% else %}
    <div class="avatar bg-warning d-flex justify-content-center align-items-center fw-bold text-dark me-3">?</div>
    {% endif %}
    <strong>{{ post.nickname or post.username }}</strong>
    <small class="text-muted ms-auto">{{ post.created_at.strftime('%Y-%m-%d %H:%M') }}</small>
  </div>
  <p>{{ post.body }}</p>

  <hr />
  <h5>Comments</h5>
  {% for comment in comments %}
  <div class="comment">
    <div class="d-flex align-items-center mb-1">
      {% if comment.avatar_base64 %}
      <img src="data:image/png;base64,{{ comment.avatar_base64 }}" alt="avatar" class="avatar me-2" />
      {% else %}
      <div class="avatar bg-warning d-flex justify-content-center align-items-center fw-bold text-dark me-2">?</div>
      {% endif %}
      <strong>{{ comment.nickname or comment.username }}</strong>
      <small class="text-muted ms-auto">{{ comment.created_at.strftime('%Y-%m-%d %H:%M') }}</small>
    </div>
    <p>{{ comment.comment }}</p>
  </div>
  {% else %}
  <p>No comments yet.</p>
  {% endfor %}

  {% if session.get('user_id') %}
  <form method="post" class="mt-4">
    <div class="mb-3">
      <textarea name="comment" rows="3" class="form-control" placeholder="Add a comment..." required></textarea>
    </div>
    <button type="submit" class="btn btn-danger">Submit Comment</button>
  </form>
  {% else %}
  <p><a href="{{ url_for('login') }}">Login</a> to comment.</p>
  {% endif %}
  <p class="mt-3"><a href="{{ url_for('home') }}">Back to Home</a></p>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

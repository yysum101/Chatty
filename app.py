import os
import base64
import hashlib
import secrets
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

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        flash("Login required.", "warning")
        return redirect(url_for('login'))

    conn = get_db_conn()
    cur = conn.cursor()

    if request.method == 'POST':
        about = request.form['about'].strip()
        nickname = request.form['nickname'].strip()
        avatar = request.files.get('avatar')
        avatar_b64 = session.get('avatar_base64')

        if avatar and allowed_file(avatar.filename):
            avatar_bytes = avatar.read()
            avatar_b64 = base64.b64encode(avatar_bytes).decode('utf-8')

        cur.execute("""
            UPDATE users SET about=%s, nickname=%s, avatar_base64=%s WHERE id=%s
        """, (about, nickname, avatar_b64, session['user_id']))
        conn.commit()
        flash("Profile updated!", "success")

        # Update session info
        session['nickname'] = nickname
        session['avatar_base64'] = avatar_b64

    cur.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    conn.close()

    return render_template_string(PROFILE_HTML, user=user)

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

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if 'user_id' not in session:
        flash("Login to enter chat room.", "warning")
        return redirect(url_for('login'))

    conn = get_db_conn()
    cur = conn.cursor()

    if request.method == 'POST':
        msg = request.form['message'].strip()
        if msg:
            cur.execute("INSERT INTO chat_messages (user_id, message) VALUES (%s, %s)", (session['user_id'], msg))
            conn.commit()
            flash("Message sent!", "success")

    cur.execute("""
        SELECT chat_messages.*, users.nickname, users.avatar_base64, users.username FROM chat_messages
        JOIN users ON chat_messages.user_id = users.id
        ORDER BY chat_messages.created_at ASC
        LIMIT 100
    """)
    messages = cur.fetchall()
    cur.close()
    conn.close()

    return render_template_string(CHAT_HTML, messages=messages, session=session)

# === Inline templates ===

# Only showing the PROFILE_HTML here, rest remains same as before (blue-green with white bg, all pages share style/nav/footer)

PROFILE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Profile - Chatterbox</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
  <style>
    body {background: #ffffff; color:#055a52; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;}
    nav.navbar {
      background: #0d9b8e;
    }
    .container {
      max-width: 600px;
      margin: 3rem auto;
      background: #e0f2f1;
      padding: 2rem;
      border-radius: 15px;
      box-shadow: 0 0 15px #0d9b8e88;
    }
    .avatar-preview {
      width: 120px;
      height: 120px;
      border-radius: 50%;
      object-fit: cover;
      border: 3px solid #0d9b8e;
      margin-bottom: 1rem;
    }
    button.btn-danger {
      background-color: #0d9b8e;
      border: none;
    }
    button.btn-danger:hover {
      background-color: #055a52;
    }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg">
  <div class="container">
    <a class="navbar-brand fw-bold text-white" href="{{ url_for('home') }}">Chatterbox</a>
    <div>
      <span class="text-white me-3">{{ session.get('nickname') or session.get('username') }}</span>
      <a href="{{ url_for('post') }}" class="btn btn-outline-light btn-sm me-2">New Post</a>
      <a href="{{ url_for('chat') }}" class="btn btn-outline-light btn-sm me-2">Chat Room</a>
      <a href="{{ url_for('logout') }}" class="btn btn-outline-light btn-sm me-2">Logout</a>
    </div>
  </div>
</nav>
<div class="container">
  <h2>Your Profile</h2>
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

  {% if user.avatar_base64 %}
  <img src="data:image/png;base64,{{ user.avatar_base64 }}" alt="Avatar" class="avatar-preview" />
  {% else %}
  <div class="avatar-preview bg-primary d-flex justify-content-center align-items-center fw-bold text-white" style="font-size: 3rem;">?</div>
  {% endif %}

  <form method="post" enctype="multipart/form-data">
    <div class="mb-3">
      <label>About You</label>
      <textarea name="about" rows="4" class="form-control">{{ user.about }}</textarea>
    </div>
    <div class="mb-3">
      <label>Nickname</label>
      <input type="text" name="nickname" value="{{ user.nickname }}" maxlength="50" class="form-control" />
    </div>
    <div class="mb-3">
      <label>Change Avatar (optional)</label>
      <input type="file" name="avatar" accept="image/*" class="form-control" />
      <small class="text-muted">Allowed: png, jpg, jpeg, gif</small>
    </div>
    <button type="submit" class="btn btn-danger w-100">Save Profile</button>
  </form>
  <p class="mt-3"><a href="{{ url_for('home') }}">Back to Home</a></p>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# The rest of the templates (HOME_HTML, REGISTER_HTML, LOGIN_HTML, POST_HTML, POST_DETAIL_HTML, CHAT_HTML) 
# remain exactly as the previous full code with the blue-green and white background theme and navigation

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

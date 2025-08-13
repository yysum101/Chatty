import base64
import hashlib
import secrets
from io import BytesIO
from datetime import datetime

from flask import Flask, render_template_string, request, redirect, url_for, session, flash
@@ -52,14 +53,6 @@ def init_db():
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
@@ -155,42 +148,6 @@ def logout():
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
@@ -242,89 +199,68 @@ def post_detail(post_id):

return render_template_string(POST_DETAIL_HTML, post=post, comments=comments, session=session)

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if 'user_id' not in session:
        flash("Login to enter chat room.", "warning")
        return redirect(url_for('login'))

    conn = get_db_conn()
    cur = conn.cursor()
# ---- Inline Templates Below ----

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
HOME_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
 <meta charset="UTF-8" />
  <title>Profile - Chatterbox</title>
  <title>Chatterbox Home</title>
 <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
 <style>
    body {background: #ffffff; color:#055a52; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;}
    nav.navbar {
      background: #0d9b8e;
    body {
      background: linear-gradient(135deg, #b71c1c, #fbc02d);
      color: #222;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
   }
   .container {
      max-width: 600px;
      margin: 3rem auto;
      background: #e0f2f1;
      padding: 2rem;
      border-radius: 15px;
      box-shadow: 0 0 15px #0d9b8e88;
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
    .avatar-preview {
      width: 120px;
      height: 120px;
    .avatar {
      width: 50px; height: 50px;
     border-radius: 50%;
     object-fit: cover;
      border: 3px solid #0d9b8e;
      margin-bottom: 1rem;
    }
    button.btn-danger {
      background-color: #0d9b8e;
      border: none;
      border: 2px solid #fbc02d;
   }
    button.btn-danger:hover {
      background-color: #055a52;
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
<nav class="navbar navbar-expand-lg">
<nav class="navbar navbar-expand-lg navbar-dark" style="background:#b71c1c;">
 <div class="container">
    <a class="navbar-brand fw-bold text-white" href="{{ url_for('home') }}">Chatterbox</a>
    <a class="navbar-brand fw-bold" href="{{ url_for('home') }}">Chatterbox</a>
   <div>
      <span class="text-white me-3">{{ session.get('nickname') or session.get('username') }}</span>
      <a href="{{ url_for('post') }}" class="btn btn-outline-light btn-sm me-2">New Post</a>
      <a href="{{ url_for('chat') }}" class="btn btn-outline-light btn-sm me-2">Chat Room</a>
      <a href="{{ url_for('logout') }}" class="btn btn-outline-light btn-sm me-2">Logout</a>
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
  <h2>Your Profile</h2>
 {% with messages = get_flashed_messages(with_categories=true) %}
   {% if messages %}
     {% for category, message in messages %}
@@ -336,37 +272,269 @@ def chat():
   {% endif %}
 {% endwith %}

  {% if user.avatar_base64 %}
  <img src="data:image/png;base64,{{ user.avatar_base64 }}" alt="Avatar" class="avatar-preview" />
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
  <div class="avatar-preview bg-primary d-flex justify-content-center align-items-center fw-bold text-white" style="font-size: 3rem;">?</div>
  {% endif %}
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
      <label>About You</label>
      <textarea name="about" rows="4" class="form-control">{{ user.about }}</textarea>
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
      <input type="text" name="nickname" value="{{ user.nickname }}" maxlength="50" class="form-control" />
      <input type="text" name="nickname" class="form-control" maxlength="50" />
   </div>
   <div class="mb-3">
      <label>Change Avatar (optional)</label>
      <label>Avatar (optional)</label>
     <input type="file" name="avatar" accept="image/*" class="form-control" />
     <small class="text-muted">Allowed: png, jpg, jpeg, gif</small>
   </div>
    <button type="submit" class="btn btn-danger w-100">Save Profile</button>
    <button type="submit" class="btn btn-danger w-100">Register</button>
 </form>
  <p class="mt-3"><a href="{{ url_for('home') }}">Back to Home</a></p>
  <p class="mt-3 text-center">Already have an account? <a href="{{ url_for('login') }}">Login here</a>.</p>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
</body></html>
"""

# The rest of the templates (HOME_HTML, REGISTER_HTML, LOGIN_HTML, POST_HTML, POST_DETAIL_HTML, CHAT_HTML) 
# remain exactly as the previous full code with the blue-green and white background theme and navigation
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

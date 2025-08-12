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
app.secret_key = os.environ.get("SECRET_KEY", "super-secret-key")

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
    # Note: chat_messages table removed!

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

# Templates are omitted here for brevity.
# They are the same as before, minus any chat related parts.

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

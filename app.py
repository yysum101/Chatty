from flask import Flask, render_template_string, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('CHAT_SECRET') or 'change-this-secret-to-something-long'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatty.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login = LoginManager(app)
login.login_view = 'login'

# --------------------
# Models
# --------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    nickname = db.Column(db.String(80), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    posts = db.relationship('Post', backref='author', lazy=True)
    comments = db.relationship('Comment', backref='author', lazy=True)
    chat_messages = db.relationship('ChatMessage', backref='author', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comments = db.relationship('Comment', backref='post', lazy=True, cascade="all, delete-orphan")

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# --------------------
# Login loader
# --------------------
@login.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --------------------
# DB init
# --------------------
with app.app_context():
    db.create_all()

# --------------------
# Templates (inline)
# --------------------
base_tpl = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Chatty - {% block title %}{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      /* Red - Yellow theme */
      :root{
        --primary:#d62828;    /* red */
        --accent:#ffb703;     /* yellow */
        --soft:#fff3d9;
        --muted:#6b6b6b;
        --card-radius:1rem;
      }
      body{
        background: linear-gradient(180deg, rgba(214,40,40,0.04), rgba(255,183,3,0.02));
        font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial;
      }
      .navbar, .footer {
        background: linear-gradient(90deg,var(--primary), #ff7b03);
      }
      .brand {
        font-weight: 800;
        letter-spacing: 0.6px;
        color: white;
      }
      .card.fancy {
        border: none;
        border-radius: var(--card-radius);
        box-shadow: 0 8px 30px rgba(214,40,40,0.12);
        background: linear-gradient(180deg,#fff,#fff7ea);
      }
      .btn-primary {
        background: var(--primary);
        border: none;
      }
      .btn-accent {
        background: var(--accent);
        color: #2a2a2a;
        border: none;
      }
      .avatar {
        width:48px;height:48px;border-radius:12px;background:linear-gradient(180deg,var(--primary),#ff7b03);display:inline-flex;align-items:center;justify-content:center;color:white;font-weight:700;
      }
      textarea { resize: vertical; }
      .muted { color: var(--muted); }
      .chat-box { max-height:420px; overflow:auto; padding:1rem; background:rgba(255,255,255,0.85); border-radius:.75rem; }
      .message { padding:.6rem .8rem; border-radius:.75rem; margin-bottom:.6rem; display:inline-block; }
      .message.me { background: linear-gradient(90deg, rgba(255,183,3,0.2), rgba(255,183,3,0.05)); }
      .message.other { background: rgba(214,40,40,0.05); }
      .small-muted { font-size:0.85rem; color: #7b7b7b; }
      footer.footer { padding:1rem 0; color:white; }
      .nice-header { padding:1.2rem; border-radius: .75rem; background: linear-gradient(90deg, rgba(214,40,40,0.06), rgba(255,183,3,0.04)); }
      .form-floating>.form-control:focus~label { color: var(--primary); }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg mb-4">
      <div class="container">
        <a class="navbar-brand brand" href="{{ url_for('index') }}">Chatty</a>
        <div class="d-flex align-items-center">
          {% if current_user.is_authenticated %}
            <a class="btn btn-sm btn-outline-light me-2" href="{{ url_for('profile', username=current_user.username) }}">{{ current_user.nickname or current_user.username }}</a>
            <a class="btn btn-sm btn-light btn-accent me-2" href="{{ url_for('create_post') }}">New Post</a>
            <a class="btn btn-sm btn-light" href="{{ url_for('chat') }}">Chat</a>
            <a class="btn btn-sm btn-dark ms-2" href="{{ url_for('logout') }}">Logout</a>
          {% else %}
            <a class="btn btn-sm btn-light btn-accent me-2" href="{{ url_for('register') }}">Register</a>
            <a class="btn btn-sm btn-dark" href="{{ url_for('login') }}">Login</a>
          {% endif %}
        </div>
      </div>
    </nav>

    <div class="container">
      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          <div class="mb-3">
            {% for cat, msg in messages %}
              <div class="alert alert-{{ 'success' if cat=='success' else 'warning' }} alert-dismissible fade show" role="alert">
                {{ msg }}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
              </div>
            {% endfor %}
          </div>
        {% endif %}
      {% endwith %}

      {% block content %}{% endblock %}
    </div>

    <footer class="footer mt-5">
      <div class="container text-center">
        <small>Made with ❤️ — Chatty • Simple demo app</small>
      </div>
    </footer>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

# --------------------
# Routes
# --------------------
@app.route('/')
def index():
    posts = Post.query.order_by(Post.created_at.desc()).limit(50).all()
    recent_chats = ChatMessage.query.order_by(ChatMessage.created_at.desc()).limit(10).all()[::-1]
    return render_template_string(base_tpl + """
    {% block title %}Home{% endblock %}
    {% block content %}
    <div class="row g-4">
      <div class="col-lg-8">
        <div class="card fancy p-4">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h4 class="mb-0">Posts</h4>
            <a class="btn btn-sm btn-accent" href="{{ url_for('create_post') }}">+ New Post</a>
          </div>

          {% if posts %}
            {% for p in posts %}
              <div class="mb-3 p-3" style="border-radius:.6rem; background:linear-gradient(180deg,rgba(255,255,255,0.9), rgba(255,248,230,0.7));">
                <div class="d-flex align-items-start">
                  <div class="me-3 avatar">{{ (p.author.nickname or p.author.username)[:1].upper() }}</div>
                  <div class="w-100">
                    <div class="d-flex justify-content-between">
                      <div>
                        <strong>{{ p.subject }}</strong>
                        <div class="small-muted">by <a href="{{ url_for('profile', username=p.author.username) }}">{{ p.author.nickname or p.author.username }}</a> · {{ p.created_at.strftime('%b %d, %Y %H:%M') }}</div>
                      </div>
                      <div class="text-end">
                        <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('view_post', post_id=p.id) }}">Open</a>
                      </div>
                    </div>
                    <p class="mt-2 mb-1">{{ p.body[:260] }}{% if p.body|length > 260 %}...{% endif %}</p>
                    <div class="small-muted">{{ p.comments|length }} comments</div>
                  </div>
                </div>
              </div>
            {% endfor %}
          {% else %}
            <p class="text-muted">No posts yet. Be the first to create one!</p>
          {% endif %}
        </div>
      </div>

      <div class="col-lg-4">
        <div class="card fancy p-4 mb-4">
          <h5>Quick Chat (recent)</h5>
          <div class="chat-box my-3">
            {% for m in recent_chats %}
              <div class="mb-2">
                <div class="small-muted">{{ m.author.nickname or m.author.username }} · <small class="text-muted">{{ m.created_at.strftime('%H:%M') }}</small></div>
                <div class="message {% if current_user.is_authenticated and m.user_id==current_user.id %}me{% else %}other{% endif %}">{{ m.body }}</div>
              </div>
            {% endfor %}
          </div>
          <div>
            <a class="btn btn-sm btn-primary" href="{{ url_for('chat') }}">Open Chat Room</a>
          </div>
        </div>

        <div class="card fancy p-4">
          <h6>About Chatty</h6>
          <p class="muted">A simple small community demo — posts, comments and a persistent chat. Sign up and say hi!</p>
        </div>
      </div>
    </div>
    {% endblock %}
    """, posts=posts, recent_chats=recent_chats)

# Register
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        confirm = request.form.get('confirm','')
        nickname = request.form.get('nickname','').strip() or None
        bio = request.form.get('bio','').strip() or None

        if not username or not password or not confirm:
            flash('Please fill all required fields', 'error')
            return redirect(url_for('register'))
        if password != confirm:
            flash('Passwords do not match', 'error')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('Username already taken', 'error')
            return redirect(url_for('register'))

        u = User(username=username, nickname=nickname, bio=bio)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        flash('Account created! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template_string(base_tpl + """
    {% block title %}Register{% endblock %}
    {% block content %}
    <div class="row justify-content-center">
      <div class="col-md-7">
        <div class="card fancy p-4">
          <h3 class="mb-3">Create your Chatty account</h3>
          <form method="post">
            <div class="mb-3">
              <label class="form-label">Username *</label>
              <input class="form-control" name="username" required maxlength="80">
            </div>
            <div class="mb-3">
              <label class="form-label">Nickname</label>
              <input class="form-control" name="nickname" maxlength="80" placeholder="What should others call you?">
            </div>
            <div class="mb-3">
              <label class="form-label">Tell us about yourself</label>
              <textarea class="form-control" name="bio" rows="3" placeholder="A short bio..."></textarea>
            </div>
            <div class="row">
              <div class="col">
                <label class="form-label">Password *</label>
                <input type="password" class="form-control" name="password" required>
              </div>
              <div class="col">
                <label class="form-label">Confirm Password *</label>
                <input type="password" class="form-control" name="confirm" required>
              </div>
            </div>
            <div class="mt-4 d-flex justify-content-between">
              <a href="{{ url_for('login') }}" class="btn btn-link">Already have an account?</a>
              <button class="btn btn-primary">Register</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    {% endblock %}
    """)

# Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        if not username or not password:
            flash('Please enter username and password', 'error')
            return redirect(url_for('login'))
        user = User.query.filter_by(username=username).first()
        if user is None or not user.check_password(password):
            flash('Invalid credentials', 'error')
            return redirect(url_for('login'))
        login_user(user)
        flash('Welcome back, {}!'.format(user.nickname or user.username), 'success')
        return redirect(url_for('index'))

    return render_template_string(base_tpl + """
    {% block title %}Login{% endblock %}
    {% block content %}
    <div class="row justify-content-center">
      <div class="col-md-5">
        <div class="card fancy p-4">
          <h3 class="mb-3">Login to Chatty</h3>
          <form method="post">
            <div class="mb-3">
              <label class="form-label">Username</label>
              <input class="form-control" name="username" required>
            </div>
            <div class="mb-3">
              <label class="form-label">Password</label>
              <input type="password" class="form-control" name="password" required>
            </div>
            <div class="d-flex justify-content-between align-items-center">
              <a class="btn btn-link" href="{{ url_for('register') }}">Create an account</a>
              <button class="btn btn-primary">Login</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    {% endblock %}
    """)

# Logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'success')
    return redirect(url_for('index'))

# Create Post
@app.route('/create_post', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        subject = request.form.get('subject','').strip()
        body = request.form.get('body','').strip()
        if not subject or not body:
            flash('Please provide subject and body', 'error')
            return redirect(url_for('create_post'))
        p = Post(subject=subject, body=body, author=current_user)
        db.session.add(p)
        db.session.commit()
        flash('Post created', 'success')
        return redirect(url_for('view_post', post_id=p.id))
    return render_template_string(base_tpl + """
    {% block title %}Create Post{% endblock %}
    {% block content %}
    <div class="row justify-content-center">
      <div class="col-md-8">
        <div class="card fancy p-4">
          <h4>New Post</h4>
          <form method="post">
            <div class="mb-3">
              <label class="form-label">Subject</label>
              <input class="form-control" name="subject" required maxlength="200">
            </div>
            <div class="mb-3">
              <label class="form-label">Body</label>
              <textarea class="form-control" name="body" rows="8" required></textarea>
            </div>
            <div class="d-flex justify-content-end">
              <a class="btn btn-link me-2" href="{{ url_for('index') }}">Cancel</a>
              <button class="btn btn-accent">Publish</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    {% endblock %}
    """)

# View Post + Comments
@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def view_post(post_id):
    p = Post.query.get_or_404(post_id)
    if request.method == 'POST':
        if not current_user.is_authenticated:
            flash('You must be logged in to comment', 'error')
            return redirect(url_for('login'))
        body = request.form.get('body','').strip()
        if not body:
            flash('Comment cannot be empty', 'error')
            return redirect(url_for('view_post', post_id=post_id))
        c = Comment(body=body, author=current_user, post=p)
        db.session.add(c)
        db.session.commit()
        flash('Comment added', 'success')
        return redirect(url_for('view_post', post_id=post_id))

    return render_template_string(base_tpl + """
    {% block title %}{{ p.subject }}{% endblock %}
    {% block content %}
      <div class="row">
        <div class="col-lg-8">
          <div class="card fancy p-4">
            <h3>{{ p.subject }}</h3>
            <div class="small-muted">by <a href="{{ url_for('profile', username=p.author.username) }}">{{ p.author.nickname or p.author.username }}</a> · {{ p.created_at.strftime('%b %d, %Y %H:%M') }}</div>
            <hr>
            <p style="white-space:pre-wrap;">{{ p.body }}</p>
            <hr>
            <h6>Comments ({{ p.comments|length }})</h6>
            {% if p.comments %}
              {% for c in p.comments %}
                <div class="mb-3 p-3" style="border-radius:.6rem; background:rgba(0,0,0,0.02);">
                  <div class="d-flex align-items-start">
                    <div class="me-3 avatar">{{ (c.author.nickname or c.author.username)[:1].upper() }}</div>
                    <div>
                      <div><strong>{{ c.author.nickname or c.author.username }}</strong> <small class="text-muted">{{ c.created_at.strftime('%b %d %H:%M') }}</small></div>
                      <div class="mt-1">{{ c.body }}</div>
                    </div>
                  </div>
                </div>
              {% endfor %}
            {% else %}
              <p class="text-muted">No comments yet. Be the first to comment!</p>
            {% endif %}
          </div>
        </div>

        <div class="col-lg-4">
          <div class="card fancy p-3">
            <h6>Leave a comment</h6>
            {% if current_user.is_authenticated %}
              <form method="post">
                <div class="mb-2">
                  <textarea class="form-control" name="body" rows="4" placeholder="Write your comment..." required></textarea>
                </div>
                <div class="d-flex justify-content-end">
                  <button class="btn btn-primary">Post Comment</button>
                </div>
              </form>
            {% else %}
              <p class="muted">Please <a href="{{ url_for('login') }}">login</a> to comment.</p>
            {% endif %}
          </div>
        </div>
      </div>
    {% endblock %}
    """, p=p)

# Chat room
@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat():
    if request.method == 'POST':
        body = request.form.get('body','').strip()
        if not body:
            flash('Message cannot be empty', 'error')
            return redirect(url_for('chat'))
        m = ChatMessage(body=body, author=current_user)
        db.session.add(m)
        db.session.commit()
        return redirect(url_for('chat'))
    # show last 200 messages (most recent last)
    messages = ChatMessage.query.order_by(ChatMessage.created_at.asc()).limit(200).all()
    return render_template_string(base_tpl + """
    {% block title %}Chat Room{% endblock %}
    {% block content %}
      <div class="row justify-content-center">
        <div class="col-lg-8">
          <div class="card fancy p-4">
            <div class="d-flex justify-content-between align-items-center mb-3">
              <h4>Chat Room</h4>
              <small class="text-muted">Say hi — messages are public and saved</small>
            </div>
            <div class="chat-box mb-3" id="chatbox">
              {% for m in messages %}
                <div class="mb-2">
                  <div class="small-muted">{{ m.author.nickname or m.author.username }} · <small class="text-muted">{{ m.created_at.strftime('%Y-%m-%d %H:%M:%S') }}</small></div>
                  <div class="message {% if m.user_id==current_user.id %}me{% else %}other{% endif %}">{{ m.body }}</div>
                </div>
              {% endfor %}
            </div>

            <form method="post">
              <div class="input-group">
                <input name="body" class="form-control" placeholder="Type a message..." autocomplete="off">
                <button class="btn btn-primary">Send</button>
              </div>
            </form>
          </div>
        </div>
      </div>

      <script>
        // auto-scroll chatbox to bottom
        const cb = document.getElementById('chatbox');
        if (cb) { cb.scrollTop = cb.scrollHeight; }
      </script>
    {% endblock %}
    """, messages=messages)

# User profile
@app.route('/profile/<username>')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(user_id=user.id).order_by(Post.created_at.desc()).all()
    return render_template_string(base_tpl + """
    {% block title %}Profile - {{ user.username }}{% endblock %}
    {% block content %}
      <div class="row">
        <div class="col-md-8">
          <div class="card fancy p-4">
            <div class="d-flex align-items-center mb-3">
              <div class="avatar me-3">{{ (user.nickname or user.username)[:1].upper() }}</div>
              <div>
                <h4 class="mb-0">{{ user.nickname or user.username }}</h4>
                <div class="small-muted">@{{ user.username }} · Joined {{ user.created_at.strftime('%b %Y') }}</div>
              </div>
            </div>
            <p style="white-space:pre-wrap;">{{ user.bio or 'This user has not written a bio yet.' }}</p>
          </div>

          <div class="mt-4">
            <h5>Posts by {{ user.nickname or user.username }}</h5>
            {% for p in posts %}
              <div class="card p-3 mb-2">
                <div class="d-flex justify-content-between">
                  <div><a href="{{ url_for('view_post', post_id=p.id) }}"><strong>{{ p.subject }}</strong></a> <div class="small-muted">{{ p.created_at.strftime('%b %d %Y') }}</div></div>
                </div>
              </div>
            {% else %}
              <p class="text-muted">No posts yet.</p>
            {% endfor %}
          </div>
        </div>
      </div>
    {% endblock %}
    """, user=user, posts=posts)

# --------------------
# Run
# --------------------
if __name__ == '__main__':
    app.run(debug=True)

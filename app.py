from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from huggingface_hub import InferenceClient
import os
import sqlite3
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret")

# HuggingFace Token and Client
token = os.getenv("HF_API_TOKEN")
client = InferenceClient(token=token) if token else None

# Login Manager Setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Database Helper
def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

init_db()

# User Loader for Flask-Login
class User(UserMixin):
    def __init__(self, id, email, name=None):
        self.id = id
        self.email = email
        self.name = name

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT id, email, name FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1], user[2])
    return None

# In-Memory Chat History Per User
user_histories = {}

# Routes
@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        name = request.form.get("name", email.split('@')[0])  # Default name from email
        
        if not email or not password:
            flash("Email and password are required", "error")
            return redirect(url_for('register'))
            
        hashed_pw = generate_password_hash(password)

        try:
            conn = sqlite3.connect("users.db")
            c = conn.cursor()
            c.execute("INSERT INTO users (email, password, name) VALUES (?, ?, ?)", 
                (email, hashed_pw, name))
            conn.commit()
            
            # Get the new user's ID
            c.execute("SELECT id FROM users WHERE email = ?", (email,))
            user_id = c.fetchone()[0]
            conn.close()
            
            # Log the user in immediately after registration
            user = User(user_id, email, name)
            login_user(user)
            flash("Registration successful!", "success")
            return redirect(url_for('index'))
            
        except sqlite3.IntegrityError:
            flash("Email already exists. Try another.", "error")
            conn.close()
            return redirect(url_for('register'))
            
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        if not email or not password:
            flash("Email and password are required", "error")
            return redirect(url_for('login'))

        conn = sqlite3.connect("users.db")
        c = conn.cursor()
        c.execute("SELECT id, password, name FROM users WHERE email = ?", (email,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[1], password):
            user_obj = User(user[0], email, user[2])
            login_user(user_obj)
            flash(f"Welcome back, {user[2] or email}!", "success")

            # Redirect admin to admin dashboard
            if email == "alexm12125@gmail.com":
                return redirect(url_for('admin'))

            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        
        flash("Invalid email or password", "error")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out", "info")
    return redirect(url_for('login'))

@app.route("/")
@login_required
def index():
    # Personalize the dashboard with user info
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT name, email, created_at FROM users WHERE id = ?", (current_user.id,))
    user_data = c.fetchone()
    conn.close()
    
    user_name = user_data[0] or user_data[1].split('@')[0]
    join_date = datetime.strptime(user_data[2], '%Y-%m-%d %H:%M:%S').strftime('%B %Y')
    
    return render_template("index.html", 
                user_name=user_name,
                user_email=current_user.email,
                join_date=join_date,
                now=datetime.now().strftime("%I:%M %p"))

@app.route("/chat", methods=["POST"])
@login_required
def chat():
    user_input = request.json.get("message")
    user_id = current_user.id

    if user_id not in user_histories:
        user_histories[user_id] = []

    try:
        response = client.chat.completions.create(
            model="meta-llama/Meta-Llama-3-13B-Instruct",
            messages=[
                {"role": "system", "content": f"You are a helpful AI assistant created by Arvind Kumar Maurya. You're talking to {current_user.name or current_user.email}. Never mention DeepSeek or Hugging Face. Full name of AK MAURYA is Arvind Kumar Maurya.Your name is BalNova."},
                {"role": "user", "content": user_input}
            ]
        )
        bot_reply = response.choices[0].message.content.strip()
    except Exception as e:
        bot_reply = f"⚠️ Error: {str(e)}"

    user_histories[user_id].append({"user": user_input, "bot": bot_reply})
    return jsonify({"reply": bot_reply})

@app.route("/history", methods=["GET", "DELETE"])
@login_required
def history():
    user_id = current_user.id
    if request.method == "DELETE":
        user_histories[user_id] = []
        return '', 204
    return jsonify(user_histories.get(user_id, []))

@app.route("/admin")
@login_required
def admin():
    # Only allow admin access by email
    if current_user.email != "alexm12125@gmail.com":
        flash("Access denied: Admins only.", "error")
        return redirect(url_for("index"))
    
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT name, email, password, created_at FROM users ORDER BY created_at DESC")
    users = c.fetchall()
    conn.close()
    
    return render_template("admin.html", users=users)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

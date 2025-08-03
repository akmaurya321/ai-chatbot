import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
from huggingface_hub import InferenceClient
import sqlite3
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from collections import deque
import pytesseract
from PIL import Image
import io
import base64
import requests
from uuid import uuid4
import time

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret")

# HuggingFace Token and Client
token = os.getenv("HF_API_TOKEN")
client = InferenceClient(token=token) if token else None

# Wan Video Generation Config
WAN_API_URL = os.getenv('WAN_API_URL',)
WAN_API_SECRET = os.getenv('WAN_API_SECRET', 'arvindg123Kumar@12!9199244051Maurya!')

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
    c.execute("""
        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS generated_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            filename TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

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

def extract_text_from_image(image_data):
    try:
        if ';base64,' in image_data:
            image_data = image_data.split(';base64,')[1]
        
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        
        text = pytesseract.image_to_string(image)
        return text.strip()
    except Exception as e:
        print(f"Error in OCR: {str(e)}")
        return None

@app.route("/extract_text", methods=["POST"])
@login_required
def extract_text():
    image_data = request.json.get("image")
    if not image_data:
        return jsonify({"error": "No image provided"}), 400
    
    extracted_text = extract_text_from_image(image_data)
    if extracted_text:
        return jsonify({"text": extracted_text})
    else:
        return jsonify({"error": "Failed to extract text"}), 500

@app.route("/flashcards", methods=["GET", "POST", "DELETE"])
@login_required
def flashcards():
    if request.method == "GET":
        conn = sqlite3.connect("users.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT id, front, back FROM flashcards WHERE user_id = ?", (current_user.id,))
        cards = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify(cards)
    
    elif request.method == "POST":
        front = request.json.get("front")
        back = request.json.get("back")
        if not front or not back:
            return jsonify({"error": "Front and back text required"}), 400
        
        conn = sqlite3.connect("users.db")
        c = conn.cursor()
        c.execute("INSERT INTO flashcards (user_id, front, back) VALUES (?, ?, ?)", 
                (current_user.id, front, back))
        conn.commit()
        card_id = c.lastrowid
        conn.close()
        return jsonify({"id": card_id, "front": front, "back": back}), 201
    
    elif request.method == "DELETE":
        card_id = request.json.get("id")
        if not card_id:
            return jsonify({"error": "Card ID required"}), 400
        
        conn = sqlite3.connect("users.db")
        c = conn.cursor()
        c.execute("DELETE FROM flashcards WHERE id = ? AND user_id = ?", 
                (card_id, current_user.id))
        conn.commit()
        conn.close()
        return jsonify({"success": True}), 200

@app.route("/generate_video", methods=["POST"])
@login_required
def generate_video():
    try:
        data = request.get_json()
        prompt = data.get('prompt')
        
        if not prompt:
            return jsonify({'error': 'Prompt is required'}), 400
        
        # Make request to WAN API
        response = requests.post(
            WAN_API_URL,
            json={
                'prompt': prompt,
                'auth_token': WAN_API_SECRET

            },
            timeout=120
        )
        
        if response.status_code != 200:
            return jsonify({'error': 'Video generation failed', 'details': response.text}), 500
        
        video_data = response.json()
        filename = video_data.get('filename')
        video_url = video_data.get('video_url')
        
        if not filename or not video_url:
            return jsonify({'error': 'Invalid response from video generation service'}), 500
        
        # Store the video reference in database
        conn = sqlite3.connect("users.db")
        c = conn.cursor()
        c.execute("INSERT INTO generated_videos (user_id, prompt, filename) VALUES (?, ?, ?)",
                (current_user.id, prompt, filename))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'video_url': video_url,
            'filename': filename,
            'message': 'Video generated successfully'
        })
        
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Video generation timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/videos/<filename>")
@login_required
def serve_video(filename):
    # Verify the user has access to this video
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT filename FROM generated_videos WHERE filename = ? AND user_id = ?", 
            (filename, current_user.id))
    if not c.fetchone():
        conn.close()
        return jsonify({'error': 'Video not found or access denied'}), 404
    conn.close()
    
    # In a real implementation, you would serve the file from storage
    # For now, we'll proxy the request to the WAN API
    try:
        wan_video_url = f"{WAN_API_URL.rsplit('/generate', 1)[0]}/videos/{filename}"
        response = requests.get(wan_video_url, stream=True)
        
        if response.status_code == 200:
            return send_file(
                io.BytesIO(response.content),
                mimetype='video/mp4',
                as_attachment=False
            )
        else:
            return jsonify({'error': 'Failed to fetch video'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/my_videos")
@login_required
def my_videos():
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT id, prompt, filename, created_at 
        FROM generated_videos 
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (current_user.id,))
    videos = [dict(row) for row in c.fetchall()]
    conn.close()
    
    # Generate full URLs for each video
    base_url = WAN_API_URL.rsplit('/generate', 1)[0]
    for video in videos:
        video['url'] = f"{base_url}/videos/{video['filename']}"
    
    return jsonify(videos)

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        name = request.form.get("name", email.split('@')[0])
        
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
            
            c.execute("SELECT id FROM users WHERE email = ?", (email,))
            user_id = c.fetchone()[0]
            conn.close()
            
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
        user_histories[user_id] = deque(maxlen=60)
    
    context_messages = [
        {"role": "system", "content": f'''You are a helpful AI assistant created by Arvind Kumar Maurya.
        You're talking to {current_user.name or current_user.email}. 
        Never mention DeepSeek or Hugging Face in chat. Full name of AK MAURYA is Arvind Kumar Maurya. 
        Your name is BalNova means young energy. You are able to remember 60 past chat history.
        You can help generate videos from text prompts by suggesting "Would you like me to generate a video for this?" when appropriate.'''}
    ]
    
    for msg in user_histories[user_id]:
        context_messages.append({
            "role": "user" if msg.startswith("User:") else "assistant",
            "content": msg.split(":", 1)[1].strip()
        })
    
    context_messages.append({"role": "user", "content": user_input})

    try:
        response = client.chat.completions.create(
            model="deepseek-ai/DeepSeek-V3-0324",
            messages=context_messages
        )
        bot_reply = response.choices[0].message.content.strip()
    except Exception as e:
        bot_reply = f"⚠️ Error: {str(e)}"

    user_histories[user_id].append(f"User: {user_input}")
    user_histories[user_id].append(f"Assistant: {bot_reply}")
    
    return jsonify({"reply": bot_reply})

@app.route("/history", methods=["GET", "DELETE"])
@login_required
def history():
    user_id = current_user.id
    if request.method == "DELETE":
        if user_id in user_histories:
            user_histories[user_id].clear()
        return '', 204
    
    history_list = list(user_histories.get(user_id, deque()))
    return jsonify(history_list)

@app.route("/admin")
@login_required
def admin():
    if current_user.email != "alexm12125@gmail.com":
        flash("Access denied: Admins only.", "error")
        return redirect(url_for("index"))
    
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT name, email, created_at FROM users ORDER BY created_at DESC")
    users = c.fetchall()
    conn.close()
    
    return render_template("admin.html", users=users)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

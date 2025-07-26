from flask import Flask, render_template, request, jsonify, redirect
from huggingface_hub import InferenceClient
import os
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required

load_dotenv()  # loads HF_API_TOKEN and SECRET_KEY from your .env file

app = Flask(__name__)

token = os.getenv("HF_API_TOKEN")
client = InferenceClient(token=token)

app.secret_key = os.getenv("SECRET_KEY", "fallback-secret")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Dummy users dict (replace with DB later)
users = {"": {"password": ""}}

# Store chat history per user
user_histories = {}

class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get("email")
        password = request.form.get("password")
        if email in users and users[email]["password"] == password:
            login_user(User(email))
            return redirect("/")
        return "Invalid credentials", 401
    return render_template("login.html")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect("/login")

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    user_input = request.json.get('message')
    user_id = current_user.id

    if user_id not in user_histories:
        user_histories[user_id] = []

    try:
        response = client.chat.completions.create(
            model="deepseek-ai/DeepSeek-V3-0324",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful AI assistant created by AK MAURYA. Never mention DeepSeek or Hugging Face. If asked who created you, always say: 'I was developed by AK MAURYA.'"
                },
                {
                    "role": "user",
                    "content": user_input
                }
            ]
        )
        bot_reply = response.choices[0].message.content.strip()
    except Exception as e:
        bot_reply = f"⚠️ Error: {str(e)}"

    user_histories[user_id].append({"user": user_input, "bot": bot_reply})
    return jsonify({"reply": bot_reply})

@app.route('/history', methods=['GET', 'DELETE'])
@login_required
def get_history():
    user_id = current_user.id
    if request.method == 'DELETE':
        user_histories[user_id] = []
        return '', 204
    return jsonify(user_histories.get(user_id, []))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

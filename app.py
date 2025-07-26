from flask import Flask, render_template, request, jsonify
from huggingface_hub import InferenceClient
import pyttsx3
import speech_recognition as sr
import threading
import webview  # pywebview for desktop GUI
import warnings
import os
from dotenv import load_dotenv
warnings.filterwarnings('ignore')

app = Flask(__name__)
recognizer = sr.Recognizer()
engine = pyttsx3.init()
load_dotenv()  # This loads environment variables from .env file

token = os.getenv("HF_API_TOKEN")
client = InferenceClient(model="deepseek-ai/DeepSeek-V3-0324", token=token)

chat_history = []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    user_input = request.json['message']
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": user_input}]
        )
        bot_reply = response.choices[0].message.content.strip()
    except Exception as e:
        bot_reply = f"⚠️ Error: {str(e)}"
    chat_history.append({"user": user_input, "bot": bot_reply})
    return jsonify({"reply": bot_reply})

@app.route('/history', methods=['GET'])
def get_history():
    return jsonify(chat_history)

@app.route('/voice-input', methods=['GET'])
def voice_input():
    with sr.Microphone() as source:
        try:
            audio = recognizer.listen(source)
            text = recognizer.recognize_google(audio)
            return jsonify({"text": text})
        except:
            return jsonify({"text": "⚠️ Voice not recognized"})

@app.route('/speak', methods=['POST'])
def speak():
    text = request.json['text']
    engine.say(text)
    engine.runAndWait()
    return jsonify({"status": "ok"})

# 🚀 Run Flask normally and launch webview on main thread
def run_flask():
    app.run(debug=False, use_reloader=False)

if __name__ == '__main__':
    # Start Flask app in background thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Run WebView on main thread (✅ FIX HERE)
    webview.create_window("AI Chatbot Desktop App", "http://127.0.0.1:5000")
    webview.start()

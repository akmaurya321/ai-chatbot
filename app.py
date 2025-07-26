from flask import Flask, render_template, request, jsonify
from huggingface_hub import InferenceClient
import os
from dotenv import load_dotenv

load_dotenv()  # loads HF_API_TOKEN from your .env file

app = Flask(__name__)

token = os.getenv("HF_API_TOKEN")
client = InferenceClient(token=token)

chat_history = []

@app.route('/')
def index():
    return render_template('index.html')  # create an index.html in templates folder

@app.route('/chat', methods=['POST'])
def chat():
    user_input = request.json.get('message')
    try:
        response = client.chat.completions.create(
            model="deepseek-ai/DeepSeek-V3-0324",
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
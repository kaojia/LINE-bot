from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from openai import OpenAI
import os
from dotenv import load_dotenv

# 🔹 載入環境變數
load_dotenv()

app = Flask(__name__)

# 🔹 讀取金鑰
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

# 初始化
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ✅ 初始化 OpenAI Client（必須有這行）
client = OpenAI(api_key=OPENAI_KEY)

# 🔹 ChatGPT 回覆函式
def get_chatgpt_response(user_message):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",   # 或 gpt-4o-mini
            messages=[{"role": "user", "content": user_message}],
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ ChatGPT API 錯誤：", e)
        return "系統發生錯誤，請稍後再試。"

# 🔹 Webhook 接收事件
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# 🔹 當使用者發送文字訊息時
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        user_text = event.message.text
        print(f"✅ 收到訊息：{user_text}")

        reply_text = get_chatgpt_response(user_text)
        print(f"✅ ChatGPT 回覆：{reply_text}")

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )

    except Exception as e:
        print("❌ handle_message 發生錯誤：", e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=500)

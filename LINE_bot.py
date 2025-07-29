from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from openai import OpenAI
import os
import re
from difflib import SequenceMatcher

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


# ✅ 快取與 FAQ
cache = {}
FAQ_RESPONSES = {
    "你好": "你好！我是Jenny 的 AI 助理，關於亞馬遜的問題歡迎詢問～",
    "幫助": "需要幫助嗎？請輸入：功能 / 教學 / 聯絡客服"
}

# ✅ 語言檢測（英文比例 >50% → 英文）
def is_english_message(text):
    letters = re.findall(r'[A-Za-z]', text)
    return len(letters) / max(len(text), 1) > 0.5

# ✅ GPT 判斷是否與亞馬遜相關（YES/NO）
def is_business_related_gpt(user_message):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a classifier. Answer only 'YES' or 'NO'. Does this message relate to Amazon seller business (FBA, logistics, ads, Prime Day, etc.)?"},
                {"role": "user", "content": user_message}
            ],
            max_tokens=3,
            temperature=0
        )
        return response.choices[0].message.content.strip().upper() == "YES"
    except Exception as e:
        print(f"❌ GPT 分類 API 錯誤：{e}")
        return True  # 分類失敗時，預設允許

# ✅ GPT 回覆函式
def get_gpt_reply(user_message):
    # 1️⃣ FAQ 完全匹配
    if user_message.strip() in FAQ_RESPONSES:
        return FAQ_RESPONSES[user_message.strip()]

    # 2️⃣ GPT 判斷業務性
    if not is_business_related_gpt(user_message):
        return "⚠️ 抱歉，此服務僅限亞馬遜相關用途，無法處理該訊息。"

    # 3️⃣ 快取
    if user_message in cache:
        return cache[user_message]

    english_input = is_english_message(user_message)

    # 🔹 GPT 生成回覆（縮短 System Prompt）
    prompt = (
        "You are Jenny's AI assistant. "
        "Answer only Amazon seller-related questions. "
        "If user asks in English, respond fully in English. "
        "If user asks in Chinese, respond in Chinese. "
        "Keep answers concise and practical."
    )

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=350
            )
            reply_text = response.choices[0].message.content.strip()

            # ✅ 程式自動加免責聲明
            if english_input:
                reply_text += "\n\nThis advice is for reference only. Please confirm with Jenny for further details."
            else:
                reply_text += "\n\n以上建議僅供參考，建議您與 Jenny 進一步確認。"

            cache[user_message] = reply_text
            return reply_text
        except Exception as e:
            print(f"❌ GPT API 錯誤（嘗試 {attempt+1}/3）：{e}")
            time.sleep(1)

    return "⚠️ 系統繁忙，請稍後再試。"

# ✅ 防止重複註冊 endpoint（特別是 Jupyter）
if "callback" in app.view_functions:
    app.view_functions.pop("callback")

# 🔹 Webhook
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 🔹 LINE 訊息處理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        user_text = event.message.text.strip()
        print(f"✅ 收到訊息：{user_text}")
        reply_text = get_gpt_reply(user_text)
        print(f"🤖 回覆：{reply_text}")

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    except Exception as e:
        print("❌ handle_message 發生錯誤：", e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=500)

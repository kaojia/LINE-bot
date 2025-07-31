from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from openai import OpenAI
from dotenv import load_dotenv
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
client = OpenAI(api_key=OPENAI_KEY)

# ✅ 快取與 FAQ
cache = {}
FAQ_RESPONSES = {
    # 中文
    "你好": "你好！我是Jenny 的 AI 助理，關於亞馬遜的問題歡迎詢問～",
    "幫助": "需要幫助嗎？請輸入：功能 / 教學 / 聯絡客服",

    # 英文
    "hello": "Hello! I'm Jenny's AI assistant. Feel free to ask anything about Amazon seller business.",
    "hi": "Hi there! I'm Jenny's AI assistant. You can ask me anything about Amazon seller topics.",
    "help": "Need help? You can type: features / tutorial / contact support."
}

# ✅ 官方帳號已回覆的關鍵字（不需要 ChatGPT 再回覆）
OFFICIAL_HANDLED_KEYWORDS = ["wifi", "預約諮詢", "提報促銷", "新賣家大禮包"]

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
    text = user_message.strip()
    text_lower = text.lower()

    # ✅ 0️⃣ FAQ 模糊匹配（支援中文 + 常見英文問候）
    greetings_keywords = ["你好", "您好", "hello", "hi", "hey", "yo"]
    if (1 <= len(user_message) <= 5) and (any(k in text_lower for k in greetings_keywords) or any(k in text for k in ["你好", "您好"])):
        return FAQ_RESPONSES.get("你好", "你好！我是Jenny 的 AI 助理，關於亞馬遜的問題歡迎詢問～")

    # ✅ 1️⃣ FAQ 完全匹配（原本的精準判斷）
    if text_lower in FAQ_RESPONSES:
        return FAQ_RESPONSES[text_lower]

    # ✅ 2️⃣ GPT 判斷是否業務相關
    if not is_business_related_gpt(text):
        return "⚠️ 抱歉，此服務僅限亞馬遜相關用途，無法處理該訊息。"

    # ✅ 3️⃣ 快取查詢
    if text in cache:
        return cache[text]

    english_input = is_english_message(text)

    # 🔹 GPT System Prompt
    prompt = (
        "You are Jenny's AI assistant. "
        "Answer only Amazon seller-related questions. "
        "If user asks in English, respond fully in English. "
        "If user asks in Chinese, respond in Traditional Chinese. "
        "Keep answers concise and practical."
    )

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text}
                ],
                max_tokens=350
            )
            reply_text = response.choices[0].message.content.strip()

            # ✅ 自動加免責聲明
            if english_input:
                reply_text += "\n\nThis advice is for reference only. Please confirm with Jenny for further details."
            else:
                reply_text += "\n\n以上建議僅供參考，建議您與 Jenny 進一步確認。"

            cache[text] = reply_text
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

# ✅ Keep-Alive Endpoint
@app.route("/ping", methods=['GET'])
def ping():
    print("✅ /ping 被呼叫")  # Debug log
    return "OK", 200

# 🔹 LINE 訊息處理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        user_text = event.message.text.strip()
        print(f"✅ 收到訊息：{user_text}")

        
        if event.source.type == "user":
        # 只回覆一對一聊天
        
        # 🟢 先檢查是否屬於官方已回覆的訊息
            if any(kw in user_text.lower() for kw in OFFICIAL_HANDLED_KEYWORDS):
                print(f"⏭️ 跳過 ChatGPT，因為 '{user_text}' 屬於官方已處理訊息")
                return  # ✅ 不回覆，避免重複

            # 🟢 其他訊息 → 繼續走 GPT 回覆邏輯
            reply_text = get_gpt_reply(user_text)
            print(f"🤖 回覆：{reply_text}")

            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

        else:
        # 來自群組或聊天室 → 不回覆
            print("訊息來自群組或聊天室，跳過回覆")


    except Exception as e:
        print("❌ handle_message 發生錯誤：", e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=500)


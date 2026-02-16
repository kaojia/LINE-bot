from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from openai import OpenAI
import os
import json
import re
import requests
from difflib import SequenceMatcher
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from dotenv import load_dotenv 

# 🔹 載入環境變數
load_dotenv()

app = Flask(__name__)

# 🔹 讀取金鑰
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
key_json_str = os.getenv("GOOGLE_SHEETS_KEY")
credentials_dict = json.loads(key_json_str)

# 初始化
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
client = OpenAI(api_key=OPENAI_KEY)
BOT_TRIGGER="@bot"

# ✅ 新增：改為從環境變數讀取
# 我們稍後會在 Render 設定一個叫做 'GOOGLE_SHEETS_KEY' 的變數
key_json_str = os.getenv("GOOGLE_SHEETS_KEY")

# 這裡做個防呆，如果讀不到變數 (例如在 local 沒設定)，就報錯或給提示
if key_json_str is None:
    print("⚠️ 警告：找不到 GOOGLE_SHEETS_KEY 環境變數")
    # 如果你在本機也想跑，可以在這裡寫 fallback 邏輯讀取本地檔案
    # 但部署時建議走環境變數
    CREDS_DICT = {} 
else:
    # 將 JSON 字串轉換回 Python 字典
    CREDS_DICT = json.loads(key_json_str)

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
OFFICIAL_HANDLED_KEYWORDS = ["wifi", "預約諮詢", "提報促銷", "新賣家大禮包","全球跟賣","註冊文件","品牌授權","倉庫位置","促銷提報","出貨注意事項","發票","佣金","關鍵字目錄","助手指令"]

# ✅ Google Sheets 設定
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, SCOPE)
GCLIENT = gspread.authorize(CREDS)

# 設定試算表名稱與工作表名稱
SHEET_NAME = "AI_Assistant_Config"  # 請改為你的試算表名稱
WORKSHEET_NAME = "Prompt"      # 請改為你的工作表名稱

def send_loading_animation(user_id, duration=20):
    url = "https://api.line.me/v2/bot/chat/loading/start"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "chatId": user_id,
        "loadingSeconds": duration
    }
    try:
        requests.post(url, headers=headers, json=data)
    except Exception as e:
        print("❌ Loading Animation API 錯誤：", e)


def get_prompt_from_sheet(mode_name="default"): 

    try:
        sheet = GCLIENT.open(SHEET_NAME).get_worksheet(0)
        print(f"✅ 成功連線到：{SHEET_NAME} - {sheet.title}")
        
        # 在第一欄搜尋 mode_name (例如 "Business_Review")
        cell = sheet.find(mode_name)
        
        if cell:
            # 找到後，回傳同一列、第二欄 (Column B) 的值
            return sheet.cell(cell.row, 2).value
        else:
            print(f"⚠️ 找不到模式 {mode_name}，使用預設 Prompt")
            return "You are a helpful AI assistant."
            
    except Exception as e:
        print(f"❌ 讀取 Google Sheet 失敗: {e}")
        return "You are a helpful AI assistant."

# ✅ 官方帳號已回覆的關鍵字（不需要 ChatGPT 再回覆）
OFFICIAL_HANDLED_KEYWORDS = ["wifi", "預約諮詢", "提報促銷", "新賣家大禮包"]

# ✅ 語言檢測（英文比例 >50% → 英文）
def is_english_message(text):
    letters = re.findall(r'[A-Za-z]', text)
    return len(letters) / max(len(text), 1) > 0.5

def get_gpt_reply(user_message):
    text = user_message.strip()
    text_lower = text.lower()
    
    # 預設 System Prompt
    system_prompt = "You are a helpful AI assistant."
    
    # 用來存放「乾淨」的使用者訊息 (移除 #trans 等標籤後)
    clean_text = text 

    # ✅ 1. 判斷指令並設定對應的 System Prompt
    # 同時把指令關鍵字移除，只留下要處理的內容
    if "#polish" in text_lower:
        system_prompt = get_prompt_from_sheet("Polish")
        clean_text = re.sub(r'#polish', '', text, flags=re.IGNORECASE).strip()
    elif "#trans" in text_lower:
        system_prompt = get_prompt_from_sheet("Translate")
        clean_text = re.sub(r'#trans', '', text, flags=re.IGNORECASE).strip()
    elif "#biz" in text_lower:
        system_prompt = get_prompt_from_sheet("Business_Review")
        clean_text = re.sub(r'#bus', '', text, flags=re.IGNORECASE).strip()
    elif "#line" in text_lower:
        system_prompt = get_prompt_from_sheet("Line_Blurb")
        clean_text = re.sub(r'#line', '', text, flags=re.IGNORECASE).strip()
    elif "#ai" in text_lower:
        system_prompt = get_prompt_from_sheet("AI")
        clean_text = re.sub(r'#line', '', text, flags=re.IGNORECASE).strip()
    else:
        # 如果沒有指令，嘗試去抓 default，或是維持預設助理
        # 注意：如果 Sheet 裡沒有 default 這一行，get_prompt_from_sheet 會回傳預設英文字串
        sheet_default = get_prompt_from_sheet("default")
        if sheet_default != "You are a helpful AI assistant.":
             system_prompt = sheet_default

    # ✅ 2️⃣ FAQ 模糊匹配 (維持原樣)
    greetings_keywords = ["你好", "您好", "hello", "hi", "hey", "yo"]
    # 這裡要注意：如果有下指令 (如 #trans 你好)，就不應該進 FAQ，所以加上條件
    if not any(tag in text_lower for tag in ["#polish", "#trans", "#bus", "#line"]):
        if (1 <= len(text) <= 5) and (any(k in text_lower for k in greetings_keywords) or any(k in text for k in ["你好", "您好"])):
            return FAQ_RESPONSES.get("你好", "你好！我是 AI 助理，歡迎詢問～")

    # ✅ 3️⃣ 快取查詢 (維持原樣)
    if text in cache:
        return cache[text]

    english_input = is_english_message(clean_text)

    # ✅ 4️⃣ 呼叫 OpenAI (這裡修正了！)
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt}, # 👈 修正：放入從 Sheet 抓來的人設
                    {"role": "user", "content": clean_text}       # 👈 優化：放入移除標籤後的內容
                ],
                max_tokens=500
            )
            reply_text = response.choices[0].message.content.strip()

            # ✅ 自動加免責聲明
            if english_input:
                reply_text += "\n\n(AI response for reference only)"
            else:
                reply_text += "\n\n(AI 回覆僅供參考)"

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
        source_type = event.source.type

        # 判斷 chat_id
        if source_type == "user":
            chat_id = event.source.user_id
        elif source_type == "group":
            chat_id = event.source.group_id
        elif source_type == "room":
            chat_id = event.source.room_id
        else:
            chat_id = "UNKNOWN"

        print(f"✅ 收到訊息：{user_text} | 來源：{source_type} | ID：{chat_id}")

        # =========================
        # 🟢 私聊：維持原本行為
        # =========================
        if source_type == "user":
            send_loading_animation(chat_id, duration=20)

            if any(kw in user_text.lower() for kw in OFFICIAL_HANDLED_KEYWORDS):
                print("⏭️ 官方已處理訊息，跳過")
                return

            reply_text = get_gpt_reply(user_text)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )
            return

        # =========================
        # 🟡 群組 / Room：只有 @bot 才回
        # =========================
        trigger = BOT_TRIGGER.lower()

        if trigger in user_text.lower():
            # ✂️ 移除 @bot（只移除第一個）
            cleaned_text = re.sub(
                trigger, "", user_text, count=1, flags=re.IGNORECASE
            ).strip()

            if not cleaned_text:
                print("⚠️ 只有 @bot，沒有問題內容，跳過")
                return

            print(f"🤖 群組觸發成功，問題內容：{cleaned_text}")

            reply_text = get_gpt_reply(cleaned_text)

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )
        else:
            print("⏭️ 群組未 @bot，跳過")

    except Exception as e:
        print("❌ handle_message 發生錯誤：", e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=500)


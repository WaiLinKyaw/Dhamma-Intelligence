import logging
import sqlite3
import os
import time
import datetime
import pytz
import requests
import threading

from flask import Flask

# Create dummy health-check app
app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# Start dummy server in background thread
threading.Thread(target=run_web, daemon=True).start()

from dotenv import load_dotenv
from google import genai
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()

# ----------------- CONFIGURATION -----------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Token သို့မဟုတ် API Key မရှိသေးပါ။")

client = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ----------------- DATABASE HELPERS -----------------
def get_db_connection():
    return sqlite3.connect("mindfulness_bot.db")

def init_db():
    """Table များ မရှိသေးပါက အလိုအလျောက် တည်ဆောက်ပေးသည့် Function"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_users (
            chat_id INTEGER PRIMARY KEY,
            first_name TEXT,
            subscribed INTEGER DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dhamma_resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            type TEXT,
            title TEXT,
            source TEXT
        )
    """)
    conn.commit()
    conn.close()

def register_user(chat_id: int, first_name: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO bot_users (chat_id, first_name, subscribed)
        VALUES (?, ?, 1)
    """, (chat_id, first_name))
    conn.commit()
    conn.close()

def get_subscribed_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM bot_users WHERE subscribed = 1")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_random_daily_quote():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT quote FROM daily_quotes ORDER BY RANDOM() LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "လက်ရှိ ပစ္စုပ္ပန်တည့်တည့်မှာ သတိဖြင့် အေးချမ်းပါစေ။"

def get_resources(category: str, r_type: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT title, source FROM dhamma_resources WHERE category = ? AND type = ?", 
        (category, r_type)
    )
    results = cursor.fetchall()
    conn.close()
    return results

def get_all_resources(r_type: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT title, source FROM dhamma_resources WHERE type = ?", (r_type,))
    results = cursor.fetchall()
    conn.close()
    return results

# ----------------- SCHEDULED BROADCAST JOBS -----------------
async def broadcast_quote(context: ContextTypes.DEFAULT_TYPE, title: str):
    users = get_subscribed_users()
    quote = get_random_daily_quote()
    msg = f"{title}\n\n{quote}"
    for chat_id in users:
        try:
            await context.bot.send_message(chat_id=chat_id, text=msg)
        except Exception as e:
            logging.warning(f"Failed to send broadcast to {chat_id}: {e}")

async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    await broadcast_quote(context, "🌅 မင်္ဂလာနံနက်ခင်းပါ... ဒီနေ့အတွက် ဆရာကြီးဒေါက်တာစိုးလွင်၏ ဓမ္မလက်ဆောင်:")

async def noon_job(context: ContextTypes.DEFAULT_TYPE):
    await broadcast_quote(context, "☀️ မွန်းတည့်ခေတ္တ အမောပြေ... စိတ်ကို သတိလေး ပြန်ကပ်ကြည့်ပါ:")

async def evening_job(context: ContextTypes.DEFAULT_TYPE):
    await broadcast_quote(context, "🌙 တစ်နေ့တာအပြီး ညချမ်းချိန် စိတ်အေးချမ်းရေး တရားစကား:")

# ----------------- BOT HANDLERS -----------------
def get_main_keyboard():
    custom_keyboard = [
        [KeyboardButton("💬 တရားဆွေးနွေးမည်"), KeyboardButton("🔄 စကားဝိုင်းအသစ် စမယ်")],
        [KeyboardButton("🌸 တရားဓမ္မ")]
    ]
    return ReplyKeyboardMarkup(custom_keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.first_name)
    context.user_data["gemini_chat"] = None

    await update.message.reply_text(
        f"မင်္ဂလာပါ {user.first_name}။ ဆရာကြီးဒေါက်တာစိုးလွင်၏ Dhamma Intelligence (DI) မှ ကြိုဆိုပါတယ်။\n\n"
        "နေ့စဉ် မနက်၊ နေ့လယ်၊ ည သတိပဋ္ဌာန် စိတ်ခွန်အားဖြည့် စာတိုလေးများ ပို့ပေးသွားပါမည်။\n\n"
        "🔹 တရားတော်များ ကြည့်ရှုဖတ်ရှုလိုပါက '🌸 တရားဓမ္မ' ကို နှိပ်ပါ။\n"
        "🔹 ဆရာကြီး၏ တရားအမြင်ဖြင့် စိတ်အေးချမ်းအောင် ဆွေးနွေးလိုပါက '💬 တရားဆွေးနွေးမည်' ကို နှိပ်ပါ။\n"
        "🔹 စကားဝိုင်းဟောင်းကို ရှင်းထုတ်ပြီး အသစ်ပြန်စလိုပါက '🔄 စကားဝိုင်းအသစ် စမယ်' ကို နှိပ်နိုင်ပါသည်ခင်ဗျာ။",
        reply_markup=get_main_keyboard()
    )

async def dhamma_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🧘 စိတ်ခံစားချက်အလိုက် ရွေးချယ်မယ်", callback_data="dhamma_by_mood")],
        [InlineKeyboardButton("📚 စာအုပ်နှင့် ဗီဒီယို အားလုံး ကြည့်မယ်", callback_data="dhamma_all_list")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "တရားဓမ္မ ဒေသနာများကို မည်သို့ ရွေးချယ်လေ့လာလိုပါသလဲခင်ဗျာ-",
        reply_markup=reply_markup
    ) 

async def dhamma_options_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "dhamma_by_mood":
        inline_keyboard = [
            [
                InlineKeyboardButton("စိတ်ဖိစီးနေတယ် 😣", callback_data="mood_stress"),
                InlineKeyboardButton("ဝမ်းနည်းနေတယ် 😔", callback_data="mood_sadness")
            ],
            [
                InlineKeyboardButton("ဒေါသထွက်နေတယ် 😡", callback_data="mood_anger"),
                InlineKeyboardButton("စိတ်ငြိမ်သက်ချင်တယ် 🧘", callback_data="mood_mindfulness")
            ]
        ]
        await query.edit_message_text(
            "သင့်ရဲ့ လက်ရှိ စိတ်ခံစားချက်လေးကို ရွေးချယ်ပေးပါ-",
            reply_markup=InlineKeyboardMarkup(inline_keyboard)
        )

    elif query.data == "dhamma_all_list":
        choice_keyboard = [
            [
                InlineKeyboardButton("📖 တရားစာအုပ် အားလုံး", callback_data="list_all_book"),
                InlineKeyboardButton("🎬 Video အားလုံး", callback_data="list_all_video")
            ]
        ]
        await query.edit_message_text(
            "စာအုပ်များအားလုံး ဖတ်ရှုလိုပါသလား၊ ဗီဒီယိုအားလုံး ကြည့်ရှုလိုပါသလား ရွေးချယ်ပေးပါ-",
            reply_markup=InlineKeyboardMarkup(choice_keyboard)
        )

async def list_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    r_type = query.data.replace("list_all_", "")
    resources = get_all_resources(r_type)

    if not resources:
        await query.message.reply_text("လက်ရှိတွင် မည်သည့် အချက်အလက်မျှ မရှိသေးပါ။")
        return

    if r_type == "video":
        await query.message.reply_text("🎬 **ဆရာကြီးဒေါက်တာစိုးလွင်၏ တရားတော် ဗီဒီယိုများ အားလုံး-**")
        for title, source in resources:
            await query.message.reply_text(f"🔹 {title}\n🔗 {source}")
            
    elif r_type == "book":
        await query.message.reply_text("📖 **ဆရာကြီး၏ စာအုပ်များ ပေးပို့နေပါသည်...**")
        for title, source in resources:
            if os.path.exists(source):
                with open(source, "rb") as doc:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=doc,
                        caption=f"📘 {title}"
                    )

async def mood_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category = query.data.replace("mood_", "")
    context.user_data["selected_category"] = category

    choice_keyboard = [
        [
            InlineKeyboardButton("📖 တရားစာအုပ် ဖတ်မယ်", callback_data=f"res_book_{category}"),
            InlineKeyboardButton("🎬 Video တရားတော် ကြည့်မယ်", callback_data=f"res_video_{category}")
        ]
    ]
    await query.edit_message_text(
        "သင့်ခံစားချက်အတွက် စာအုပ်ဖတ်ရှုလိုပါသလား၊ တရားတော် ဗီဒီယို ကြည့်ရှုလိုပါသလား ရွေးချယ်ပေးပါ-",
        reply_markup=InlineKeyboardMarkup(choice_keyboard)
    )

async def resource_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    r_type = parts[1]
    category = parts[2]

    resources = get_resources(category, r_type)

    if not resources:
        await query.message.reply_text("ဤကဏ္ဍအတွက် အချက်အလက်များ မရှိသေးပါ။")
        return

    if r_type == "video":
        await query.message.reply_text("🎬 **သင့်အတွက် ဆရာကြီး၏ တရားတော် ဗီဒီယိုများ-**")
        for title, source in resources:
            await query.message.reply_text(f"🔹 {title}\n🔗 {source}")
    elif r_type == "book":
        await query.message.reply_text("📖 **ဆရာကြီး၏ စာအုပ်များ ပေးပို့နေပါသည်...**")
        for title, source in resources:
            if os.path.exists(source):
                with open(source, "rb") as doc:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=doc,
                        caption=f"📘 {title}"
                    )

# စာသားနှင့် မီနူးများကို ကိုင်တွယ်သည့် Handler
async def text_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🌸 တရားဓမ္မ":
        await dhamma_main_menu(update, context)
        return

    if text == "💬 တရားဆွေးနွေးမည်":
        guide_msg = (
            "🧘 **Dhamma Intelligence (DI)**\n\n"
            "လက်ရှိကြုံတွေ့နေရတဲ့ စိတ်ဖိစီးမှု၊ သောက၊ ဒေါသ သို့မဟုတ် သိလိုသော တရားဓမ္မမေးခွန်းများကို အောက်ပါ Chat Box ထဲတွင် စာရိုက်၍ ပေးပို့နိုင်ပါသည်ခင်ဗျာ။\n\n"
            "ဆရာကြီးဒေါက်တာစိုးလွင်၏ သတိပဋ္ဌာန်တရားအမြင်ဖြင့် နွေးထွေးစွာ ပြန်လည်ဆွေးနွေးပေးပါမည်။ 👇"
        )
        await update.message.reply_text(guide_msg, parse_mode="Markdown")
        return

    # New Chat (စကားဝိုင်းအသစ် စတင်ခြင်း)
    if text == "🔄 စကားဝိုင်းအသစ် စမယ်":
        context.user_data["gemini_chat"] = None
        await update.message.reply_text(
            "🌱 **စကားဝိုင်းအသစ် စတင်ပါပြီခင်ဗျာ။**\n\n"
            "ယခင် ပြောဆိုထားသည့် မှတ်တမ်းများကို ရှင်းလင်းပြီးပါပြီ။ မည်သည့် စိတ်ခံစားချက် သို့မဟုတ် တရားဓမ္မမေးခွန်းမဆို အသစ်စတင်၍ မေးမြန်းဆွေးနွေးနိုင်ပါပြီခင်ဗျာ။"
        )
        return

    # Telegram တွင် typing ပြသခြင်း (အဖြေစောင့်ရစဉ် စာရိုက်နေသည်ဟု ပေါ်နေမည်)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    user_msg = text
    sys_prompt = """You are a Buddhist meditation counselor and assistant inspired by the teachings of Dr. Soe Lwin (ဆရာကြီးဒေါက်တာစိုးလွင်).
Key principles:
- Mindfulness (သတိ)
- Loving-kindness (မေတ္တာ)
- Impermanence (အနိစ္စ)
- Non-self (အနတ္တ)
- Validate user's emotional state with warmth, compassion, and practical mindfulness advice.
Respond in Burmese language with a gentle, compassionate, and wise physician-like tone.
"""

    response_text = None
    # ပေါ့ပါးမြန်ဆန်သော lite model ကို ဦးစားပေးထားပါသည်
    candidate_models = ["gemini-3.5-flash-lite", "gemini-3.6-flash"]

    # Chat session မရှိသေးပါက အသစ်တည်ဆောက်ခြင်း
    active_chat = context.user_data.get("gemini_chat")

    for model_name in candidate_models:
        try:
            if active_chat is None:
                active_chat = client.chats.create(
                    model=model_name,
                    config={"system_instruction": sys_prompt}
                )
            
            res = active_chat.send_message(user_msg)
            if res and res.text:
                response_text = res.text
                context.user_data["gemini_chat"] = active_chat  # စကားဝိုင်းမှတ်တမ်း သိမ်းဆည်းခြင်း
                break
        except Exception as e:
            logging.error(f"Gemini API Error with {model_name}: {e}")
            active_chat = None  # Error ကြုံပါက session ပြန်ဖျက်ပြီး နောက် model စမ်းမည်

    if response_text:
        await update.message.reply_text(response_text)
    else:
        await update.message.reply_text(
            "လတ်တလောတွင် AI ဆာဗာ အလုပ်များနေပါသဖြင့် စက္ကန့်အနည်းငယ်အကြာတွင် စာပြန်ပို့ပေးပါခင်ဗျာ။ စိတ်ကို သတိလေးကပ်ပြီး အသက်ကို ဖြည်းဖြည်း ရှူသွင်း ရှူထုတ် လုပ်ပေးပါခင်ဗျာ။"
        )

# Global Error Handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(f"Exception while handling an update: {context.error}")

# ----------------- MAIN -----------------
def main():
    init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    job_queue = app.job_queue

    if job_queue:
        mm_tz = pytz.timezone("Asia/Yangon")
        job_queue.run_daily(morning_job, time=datetime.time(hour=07, minute=30, tzinfo=mm_tz))
        job_queue.run_daily(noon_job, time=datetime.time(hour=12, minute=0, tzinfo=mm_tz))
        job_queue.run_daily(evening_job, time=datetime.time(hour=19, minute=0, tzinfo=mm_tz))

    app.add_handler(CommandHandler("start", start))
    
    # Callback Handlers
    app.add_handler(CallbackQueryHandler(dhamma_options_callback, pattern="^dhamma_"))
    app.add_handler(CallbackQueryHandler(list_all_callback, pattern="^list_all_"))
    app.add_handler(CallbackQueryHandler(mood_callback, pattern="^mood_"))
    app.add_handler(CallbackQueryHandler(resource_callback, pattern="^res_"))

    # Message Handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_menu_handler))

    # Error Handler
    app.add_error_handler(error_handler)

    print("Bot is running with New Chat and Dhamma Consultation...")
    app.run_polling()

if __name__ == "__main__":
    main()

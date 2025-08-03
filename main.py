import logging
import sqlite3
import telebot
import requests
import json
import re
import time
import csv
import sys
import os
import threading
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request

# تحميل المتغيرات من ملف .env
load_dotenv()

# معلومات البوت
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", 0))
MAINTENANCE_MODE = False
BOT_VERSION = "1.4"  # تم تحديث الإصدار
DEVELOPER_USERNAME = "@Czanw"
SUPPORT_CHANNEL = "@vcnra"

# إنشاء كائن البوت
bot = telebot.TeleBot(TOKEN, num_threads=1)  # تحديد خيط واحد فقط

# تكوين السجل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# حالات المستخدمين للإبلاغ
user_reporting = {}

# ========== وظائف قاعدة البيانات ========== #
def create_database():
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                 user_id INTEGER PRIMARY KEY,
                 username TEXT,
                 first_name TEXT,
                 last_name TEXT,
                 date_joined TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 is_banned INTEGER DEFAULT 0,
                 last_activity TIMESTAMP,
                 download_count INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS channels (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 channel_id TEXT UNIQUE,
                 channel_name TEXT,
                 is_primary INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
                 id INTEGER PRIMARY KEY,
                 welcome_msg TEXT,
                 subscribe_msg TEXT,
                 forced_subscription INTEGER DEFAULT 0,
                 maintenance_mode INTEGER DEFAULT 0,
                 notify_new_users INTEGER DEFAULT 1,
                 error_reporting INTEGER DEFAULT 1)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS statistics (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 action TEXT,
                 timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS downloads (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 video_url TEXT,
                 timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 status TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS ratings (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 rating INTEGER,
                 timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''INSERT OR IGNORE INTO settings (id, welcome_msg, subscribe_msg, notify_new_users) 
                 VALUES (1, 'مرحباً بك في بوت تحميل التيك توك! 🎥\n\nفقط أرسل رابط الفيديو وسأقوم بتحميله لك بجودة 720p', 'يجب الاشتراك في القناة أولاً للاستفادة من البوت', 1)''')
    
    conn.commit()
    conn.close()

def upgrade_database():
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    
    try:
        c.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'download_count' not in columns:
            c.execute("ALTER TABLE users ADD COLUMN download_count INTEGER DEFAULT 0")
            logger.info("تمت إضافة عمود download_count إلى جدول users")
        
        c.execute("PRAGMA table_info(settings)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'notify_new_users' not in columns:
            c.execute("ALTER TABLE settings ADD COLUMN notify_new_users INTEGER DEFAULT 1")
            logger.info("تمت إضافة عمود notify_new_users إلى جدول settings")
            c.execute("UPDATE settings SET notify_new_users=1 WHERE id=1")
    except Exception as e:
        logger.error(f"خطأ في تحديث قاعدة البيانات: {e}")
    finally:
        conn.commit()
        conn.close()

# استدعاء إنشاء قاعدة البيانات
create_database()
upgrade_database()

# ========== وظائف المساعد ========== #
def get_setting(setting_name):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute(f"SELECT {setting_name} FROM settings WHERE id=1")
        result = c.fetchone()
        return result[0] if result else None
    finally:
        conn.close()

def update_setting(setting_name, value):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute(f"UPDATE settings SET {setting_name} = ? WHERE id=1", (value,))
        conn.commit()
    finally:
        conn.close()

def add_user(user_id, username, first_name, last_name):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute('''INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) 
                     VALUES (?, ?, ?, ?)''',
                  (user_id, username, first_name, last_name))
        
        c.execute('''UPDATE users SET username=?, first_name=?, last_name=?, last_activity=CURRENT_TIMESTAMP 
                     WHERE user_id=?''', (username, first_name, last_name, user_id))
        
        conn.commit()
        log_activity(user_id, "انضم جديد")
        
        if get_setting('notify_new_users') == 1 and OWNER_ID:
            notify_text = f"👤 مستخدم جديد!\n\n🆔: {user_id}\n👤: @{username}\n📛: {first_name} {last_name}\n📅: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            try:
                bot.send_message(OWNER_ID, notify_text)
            except Exception as e:
                logger.error(f"فشل إرسال إشعار مستخدم جديد: {e}")
    finally:
        conn.close()

def is_banned(user_id):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
        result = c.fetchone()
        return result[0] == 1 if result else False
    finally:
        conn.close()

def update_user_activity(user_id):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()

def increment_download_count(user_id):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET download_count = download_count + 1 WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()

def get_download_count(user_id):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("SELECT download_count FROM users WHERE user_id=?", (user_id,))
        result = c.fetchone()
        return result[0] if result else 0
    finally:
        conn.close()

def log_activity(user_id, action):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO statistics (user_id, action) VALUES (?, ?)", (user_id, action))
        conn.commit()
    finally:
        conn.close()

def log_download(user_id, video_url, status):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO downloads (user_id, video_url, status) VALUES (?, ?, ?)", 
                  (user_id, video_url, status))
        conn.commit()
    finally:
        conn.close()

def get_tiktok_video(url):
    try:
        clean_url = re.sub(r'[?&].*$', '', url)
        
        apis = [
            f"https://tikmate.app/download?url={clean_url}",
            f"https://api.tikmate.app/api/lookup?url={clean_url}",
            f"https://www.tikwm.com/api/?url={clean_url}"
        ]
        
        for api_url in apis:
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                response = requests.get(api_url, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    video_url = None
                    if 'video_url' in data:
                        video_url = data['video_url']
                    elif 'data' in data and 'play' in data['data']:
                        video_url = data['data']['play']
                    elif 'video' in data:
                        video_url = data['video']
                    
                    if video_url:
                        return video_url
            except Exception as e:
                logger.error(f"فشل API {api_url}: {e}")
                continue
        
        try:
            response = requests.get(clean_url, headers={'User-Agent': 'TikTok 26.2.0 rv:262018 (iPhone; iOS 14.4.2; ar_SA) Cronet'}, timeout=30)
            if response.status_code == 200:
                video_pattern = r'"playAddr":"([^"]+)"'
                match = re.search(video_pattern, response.text)
                if match:
                    video_url = match.group(1).replace('\\u002F', '/')
                    return video_url
        except Exception as e:
            logger.error(f"فشل في استخراج الفيديو من الصفحة: {e}")
            
        return None
    except Exception as e:
        logger.error(f"فشل في تحميل الفيديو: {e}")
        return None

def get_user_stats():
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM users WHERE is_banned=1")
        banned_users = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM users WHERE last_activity > datetime('now', '-1 day')")
        active_users = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM downloads WHERE status='success'")
        total_downloads = c.fetchone()[0]
        
        return {
            'total_users': total_users,
            'banned_users': banned_users,
            'active_users': active_users,
            'total_downloads': total_downloads
        }
    finally:
        conn.close()

def get_daily_stats():
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM statistics WHERE date(timestamp) = date('now')")
        daily_actions = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM downloads WHERE date(timestamp) = date('now') AND status='success'")
        daily_downloads = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM users WHERE date(date_joined) = date('now')")
        new_users = c.fetchone()[0]
        
        return {
            'daily_actions': daily_actions,
            'daily_downloads': daily_downloads,
            'new_users': new_users
        }
    finally:
        conn.close()

def is_subscribed(user_id):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("SELECT channel_id FROM channels")
        channels = c.fetchall()
        if not channels:
            return True
        
        for channel in channels:
            try:
                member = bot.get_chat_member(channel[0], user_id)
                if member.status in ['left', 'kicked']:
                    return False
            except Exception as e:
                logger.error(f"خطأ في التحقق من الاشتراك في القناة {channel[0]}: {e}")
                continue
        return True
    finally:
        conn.close()

def ban_user(user_id):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))
        conn.commit()
        log_activity(OWNER_ID, f"حظر مستخدم {user_id}")
    finally:
        conn.close()

def unban_user(user_id):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))
        conn.commit()
        log_activity(OWNER_ID, f"رفع حظر مستخدم {user_id}")
    finally:
        conn.close()

def get_banned_users():
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("SELECT user_id, username, first_name FROM users WHERE is_banned=1")
        users = c.fetchall()
        return users
    finally:
        conn.close()

def export_users(format='csv'):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM users")
        users = c.fetchall()
        if format == 'csv':
            with open('users.csv', 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['user_id', 'username', 'first_name', 'last_name', 'date_joined', 'is_banned', 'last_activity', 'download_count'])
                writer.writerows(users)
            return 'users.csv'
        else:
            users_list = []
            for user in users:
                users_list.append({
                    'user_id': user[0],
                    'username': user[1],
                    'first_name': user[2],
                    'last_name': user[3],
                    'date_joined': user[4],
                    'is_banned': bool(user[5]),
                    'last_activity': user[6],
                    'download_count': user[7]
                })
            with open('users.json', 'w', encoding='utf-8') as f:
                json.dump(users_list, f, ensure_ascii=False, indent=2)
            return 'users.json'
    finally:
        conn.close()

def get_all_users():
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM users WHERE is_banned=0")
        users = [row[0] for row in c.fetchall()]
        return users
    finally:
        conn.close()

def is_owner(user_id):
    try:
        return int(user_id) == int(OWNER_ID)
    except:
        return False

def log_error(error_message):
    with open('errors.log', 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now()}] {error_message}\n")

def save_rating(user_id, rating):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO ratings (user_id, rating) VALUES (?, ?)", (user_id, rating))
        conn.commit()
    finally:
        conn.close()

def get_average_rating():
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("SELECT AVG(rating) FROM ratings")
        result = c.fetchone()[0]
        return result if result else 0
    finally:
        conn.close()

def has_rated(user_id):
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM ratings WHERE user_id=?", (user_id,))
        result = c.fetchone()[0]
        return result > 0
    finally:
        conn.close()

# ========== رسالة المساعدة ========== #
HELP_TEXT = f"""
🎥 بوت تحميل التيك توك

📋 طريقة الاستخدام:
• أرسل رابط أي فيديو من التيك توك
• سأقوم بتحميله لك بجودة 1080p
• يدعم جميع أنواع روابط التيك توك

🔗 الروابط المدعومة:
• tiktok.com
• vm.tiktok.com 
• vt.tiktok.com

⚡ مميزات البوت:
• تحميل سريع وعالي الجودة
• دعم جميع أنواع الفيديوهات
• واجهة عربية بسيطة
• يعمل على جميع الأجهزة

💡 نصيحة: فقط انسخ الرابط وأرسله هنا!

📌 لعرض الأوامر المتاحة اضغط /meenu
"""

# ========== وظائف إدارة الأوامر المرئية ========== #
def set_bot_commands():
    commands = [
        telebot.types.BotCommand("start", "بدء استخدام البوت"),
        telebot.types.BotCommand("test", "اختبار اتصال البوت"),
        telebot.types.BotCommand("help", "عرض رسالة المساعدة"),
        telebot.types.BotCommand("report", "📢 الإبلاغ عن مشكلة"),
        telebot.types.BotCommand("about", "معلومات عن البوت"),
        telebot.types.BotCommand("tutorial", "شرح طريقة الاستخدام"),
        telebot.types.BotCommand("features", "مميزات البوت"),
        telebot.types.BotCommand("support", "التواصل مع الدعم"),
        telebot.types.BotCommand("mystats", "إحصائياتك الشخصية"),
        telebot.types.BotCommand("rate", "تقييم البوت"),
        telebot.types.BotCommand("meenu", "عرض قائمة الأوامر")
    ]
    try:
        bot.set_my_commands(commands)
        logger.info("تم تعيين أوامر البوت بنجاح")
    except Exception as e:
        logger.error(f"فشل تعيين أوامر البوت: {e}")

def set_admin_commands():
    if not OWNER_ID:
        logger.warning("OWNER_ID غير محدد، لن يتم تعيين أوامر الأدمن")
        return
        
    admin_commands = [
        telebot.types.BotCommand("ownercheck", "فحص هوية المالك"),
        telebot.types.BotCommand("stats", "عرض إحصائيات البوت"),
        telebot.types.BotCommand("broadcast", "بث رسالة لجميع المستخدمين"),
        telebot.types.BotCommand("ban", "حظر مستخدم"),
        telebot.types.BotCommand("unban", "رفع حظر مستخدم"),
        telebot.types.BotCommand("banned", "قائمة المحظورين"),
        telebot.types.BotCommand("export", "تصدير بيانات المستخدمين"),
        telebot.types.BotCommand("setwelcome", "تغيير رسالة الترحيب"),
        telebot.types.BotCommand("setsubscribe", "تغيير رسالة الاشتراك"),
        telebot.types.BotCommand("subscription", "تفعيل/تعطيل الاشتراك الإجباري"),
        telebot.types.BotCommand("addchannel", "إضافة قناة للاشتراك"),
        telebot.types.BotCommand("maintenance", "تفعيل/تعطيل وضع الصيانة"),
        telebot.types.BotCommand("logs", "الحصول على ملف السجلات"),
        telebot.types.BotCommand("restart", "إعادة تشغيل البوت"),
        telebot.types.BotCommand("adminhelp", "عرض أوامر الإدارة"),
        telebot.types.BotCommand("fixowner", "تصحيح هوية المالك"),
        telebot.types.BotCommand("svvab", "نسخ محتوى الرسالة"),
        telebot.types.BotCommand("togglenotify", "تفعيل/تعطيل إشعارات المستخدمين الجدد")
    ]
    try:
        bot.set_my_commands(admin_commands, scope=telebot.types.BotCommandScopeChat(OWNER_ID))
        logger.info("تم تعيين أوامر الأدمن للمالك بنجاح")
    except Exception as e:
        logger.error(f"فشل تعيين أوامر الأدمن: {e}")

# ========== معالجة المستخدمين الجدد (الميزة الجديدة) ========== #
@bot.message_handler(commands=['togglenotify'])
def toggle_notify(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    current_status = get_setting('notify_new_users')
    new_status = 0 if current_status == 1 else 1
    update_setting('notify_new_users', new_status)
    
    status_text = "تفعيل" if new_status == 1 else "تعطيل"
    bot.reply_to(message, f"✅ تم {status_text} إشعارات المستخدمين الجدد")
    log_activity(message.from_user.id, f"تغيير إشعارات المستخدمين الجدد: {new_status}")

# ========== معالجات الأوامر للمستخدمين ========== #
@bot.message_handler(commands=['help'])
def show_help(message):
    user_id = message.from_user.id
    if is_banned(user_id) or MAINTENANCE_MODE:
        return
        
    bot.reply_to(message, HELP_TEXT, parse_mode='Markdown')
    log_activity(user_id, "طلب المساعدة")

@bot.message_handler(commands=['about'])
def about_bot(message):
    user_id = message.from_user.id
    if is_banned(user_id) or MAINTENANCE_MODE:
        return
        
    avg_rating = get_average_rating()
    rating_stars = "⭐" * int(round(avg_rating))
    
    text = f"🤖 **بوت تحميل التيك توك**\n\n" \
           f"📱 الإصدار: {BOT_VERSION}\n" \
           f"📅 تاريخ الإصدار: 2023\n" \
           f"👨‍💻 المطور: {DEVELOPER_USERNAME}\n" \
           f"📣 القناة: {SUPPORT_CHANNEL}\n" \
           f"⭐ التقييم: {avg_rating:.1f}/5 {rating_stars}\n\n" \
           f"💡 هذا البوت يساعدك على تحميل فيديوهات التيك توك بدون علامة مائية وبجودة عالية."
    bot.reply_to(message, text, parse_mode='Markdown')
    log_activity(user_id, "عرض معلومات البوت")

@bot.message_handler(commands=['tutorial'])
def show_tutorial(message):
    user_id = message.from_user.id
    if is_banned(user_id) or MAINTENANCE_MODE:
        return
        
    text = "🎬 **طريقة استخدام البوت:**\n\n" \
           "1. ابحث عن فيديو تيك توك تريده\n" \
           "2. انقر على مشاركة (Share) ثم انسخ الرابط\n" \
           "3. أرسل الرابط هنا في المحادثة\n" \
           "4. انتظر قليلاً (10-20 ثانية) وسأرسل لك الفيديو\n\n" \
           "💡 ملاحظة: يدعم البوت جميع أنواع روابط التيك توك"
    bot.reply_to(message, text, parse_mode='Markdown')
    log_activity(user_id, "عرض الشرح التعليمي")

@bot.message_handler(commands=['features'])
def show_features(message):
    user_id = message.from_user.id
    if is_banned(user_id) or MAINTENANCE_MODE:
        return
        
    text = "✨ **مميزات البوت:**\n\n" \
           "• تحميل فيديوهات التيك توك بدون علامة مائية\n" \
           "• جودة عالية (HD 720p/1080p)\n" \
           "• سرعة في التنزيل (10-20 ثانية)\n" \
           "• واجهة عربية سهلة\n" \
           "• يدعم جميع أنواع الأجهزة\n" \
           "• لا حاجة لتثبيت أي تطبيق\n" \
           "• مجاني بالكامل بدون إعلانات"
    bot.reply_to(message, text, parse_mode='Markdown')
    log_activity(user_id, "عرض المميزات")

@bot.message_handler(commands=['support'])
def contact_support(message):
    user_id = message.from_user.id
    if is_banned(user_id) or MAINTENANCE_MODE:
        return
        
    text = f"📞 **للتواصل مع الدعم الفني:**\n\n" \
           f"👤 المسؤول: {DEVELOPER_USERNAME}\n" \
           f"📣 القناة الرسمية: {SUPPORT_CHANNEL}\n" \
           f"⏰ أوقات الدعم: 24/7\n\n" \
           f"🚨 للإبلاغ عن مشاكل: أرسل /report"
    bot.reply_to(message, text, parse_mode='Markdown')
    log_activity(user_id, "طلب الدعم")

@bot.message_handler(commands=['mystats'])
def user_stats(message):
    user_id = message.from_user.id
    if is_banned(user_id) or MAINTENANCE_MODE:
        return
        
    download_count = get_download_count(user_id)
    conn = sqlite3.connect('tiktok_bot.db')
    c = conn.cursor()
    try:
        c.execute("SELECT date_joined, last_activity FROM users WHERE user_id=?", (user_id,))
        result = c.fetchone()
        if result:
            join_date, last_activity = result
            join_date = join_date.split()[0] if join_date else "غير معروف"
            last_activity = last_activity.split()[0] if last_activity else "غير معروف"
        else:
            join_date = "غير معروف"
            last_activity = "غير معروف"
    finally:
        conn.close()
    
    text = f"📊 **إحصائياتك الشخصية:**\n\n" \
           f"🆔 هويتك: `{user_id}`\n" \
           f"📥 عدد التنزيلات: {download_count}\n" \
           f"📅 تاريخ الانضمام: {join_date}\n" \
           f"⏱️ آخر نشاط: {last_activity}\n\n" \
           f"💡 استمر في استخدام البوت لتحميل المزيد من الفيديوهات!"
    
    bot.reply_to(message, text, parse_mode='Markdown')
    log_activity(user_id, "عرض الإحصائيات الشخصية")

@bot.message_handler(commands=['rate'])
def rate_bot(message):
    user_id = message.from_user.id
    if is_banned(user_id) or MAINTENANCE_MODE:
        return
        
    if has_rated(user_id):
        bot.reply_to(message, "⚠️ لقد قمت بتقييم البوت مسبقًا. شكرًا لك!")
        return
        
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=5)
    for i in range(1, 6):
        keyboard.add(telebot.types.InlineKeyboardButton(f"⭐ {i}", callback_data=f"rate_{i}"))
    
    bot.reply_to(message, "⚡ كيف تقيم تجربتك مع البوت؟", reply_markup=keyboard)
    log_activity(user_id, "طلب التقييم")

@bot.message_handler(commands=['report'])
def report_problem(message):
    user_id = message.from_user.id
    if is_banned(user_id) or MAINTENANCE_MODE:
        return
        
    bot.reply_to(message, "📢 الرجاء وصف المشكلة التي تواجهها...")
    user_reporting[user_id] = True
    log_activity(user_id, "بدأ عملية الإبلاغ")

@bot.message_handler(func=lambda message: message.from_user.id in user_reporting and user_reporting[message.from_user.id])
def handle_report_description(message):
    user_id = message.from_user.id
    problem_text = message.text
        
    report_text = f"🚨 **تبليغ عن مشكلة**\n\n" \
                  f"👤 المستخدم: @{message.from_user.username} ({user_id})\n" \
                  f"✉️ المشكلة:\n{problem_text}"
    
    try:
        bot.send_message(OWNER_ID, report_text, parse_mode='Markdown')
        logger.info(f"تم إرسال تقرير مشكلة من المستخدم {user_id} إلى المطور")
        bot.reply_to(message, "☑️ تم إيصال مشكلتك إلى المطور.\n🛠️ سنقوم بحلها في أسرع وقت ممكن.")
    except Exception as e:
        logger.error(f"فشل إرسال التقرير إلى المطور: {e}")
        bot.reply_to(message, "❌ فشل في إرسال التقرير، الرجاء المحاولة لاحقاً")
    
    del user_reporting[user_id]
    log_activity(user_id, "أبلغ عن مشكلة")

@bot.message_handler(commands=['meenu'])
def show_meenu(message):
    user_id = message.from_user.id
    if is_banned(user_id) or MAINTENANCE_MODE:
        return
        
    text = """
📌 **قائمة الأوامر المتاحة:**

/start - بدء استخدام البوت
/test - اختبار اتصال البوت
/help - عرض رسالة المساعدة
/report - للإبلاغ عن مشاكل
/about - معلومات عن البوت
/tutorial - شرح طريقة الاستخدام
/features - مميزات البوت
/support - التواصل مع الدعم
/mystats - إحصائياتك الشخصية
/rate - تقييم البوت
    """
    bot.reply_to(message, text, parse_mode='Markdown')
    log_activity(user_id, "عرض قائمة الأوامر (meenu)")

# ========== معالجات الاستدعاءات ========== #
@bot.callback_query_handler(func=lambda call: call.data.startswith("rate_"))
def handle_rating(call):
    user_id = call.from_user.id
    rating = int(call.data.split("_")[1])
    
    if rating < 1 or rating > 5:
        bot.answer_callback_query(call.id, "تقييم غير صالح!")
        return
        
    if has_rated(user_id):
        bot.answer_callback_query(call.id, "لقد قمت بالتقييم مسبقاً!")
        bot.edit_message_text("⚠️ لقد قمت بتقييم البوت مسبقًا. شكرًا لك!", call.message.chat.id, call.message.message_id)
        return
        
    save_rating(user_id, rating)
    bot.answer_callback_query(call.id, f"شكراً لتقييمك! ⭐ {rating}")
    bot.edit_message_text("✅ شكراً لتقييمك البوت!", call.message.chat.id, call.message.message_id)
    log_activity(user_id, f"قام بالتقييم: {rating} نجوم")

@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def check_subscription_callback(call):
    user_id = call.from_user.id
    
    if is_subscribed(user_id):
        bot.answer_callback_query(call.id, "✅ تم التحقق بنجاح!")
        bot.send_message(call.message.chat.id, HELP_TEXT, parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id, "❌ لم تقم بالاشتراك بعد!", show_alert=True)

# ========== الأوامر الإدارية ========== #
@bot.message_handler(commands=['test'])
def test_connection(message):
    user_id = message.from_user.id
    if is_banned(user_id):
        return
        
    bot.reply_to(message, "✅ البوت يعمل بشكل طبيعي!")
    log_activity(user_id, "اختبار الاتصال")

@bot.message_handler(commands=['ownercheck'])
def owner_check(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    bot.reply_to(message, f"👑 المالك الحالي:\n\n🆔 `{OWNER_ID}`", parse_mode='Markdown')
    log_activity(user_id, "فحص المالك")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    add_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    update_user_activity(user_id)
    
    if MAINTENANCE_MODE:
        bot.reply_to(message, "⛔ البوت قيد الصيانة حالياً، الرجاء المحاولة لاحقاً")
        return
        
    if is_banned(user_id):
        bot.reply_to(message, "❌ تم حظرك من استخدام البوت")
        return
        
    if get_setting('forced_subscription') == 1 and not is_subscribed(user_id):
        subscribe_msg = get_setting('subscribe_msg')
        keyboard = telebot.types.InlineKeyboardMarkup()
        keyboard.add(telebot.types.InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subscription"))
        bot.reply_to(message, subscribe_msg, reply_markup=keyboard)
        return
        
    # تحديث رسالة الترحيب حسب طلبك
    welcome_text = """
👋 أهلاً بك!
📩 أرسل رابط فيديو تيك توك لتحميله بجودة عالية.
✅ يدعم جميع روابط تيك توك
⚡ سريع، بسيط، ويعمل على جميع الأجهزة
📌 لعرض القائمة: /meenu
📥 جاهز؟ أرسل الرابط وابدأ!
"""
    bot.reply_to(message, welcome_text, parse_mode='Markdown')
    log_activity(user_id, "بدء استخدام البوت")

@bot.message_handler(commands=['fixowner'])
def fix_owner(message):
    if str(message.from_user.id) == "8187185291":
        global OWNER_ID
        OWNER_ID = 8187185291
        bot.reply_to(message, "✅ تم تصحيح المالك! الأن أنت المتحكم")
        logger.info(f"تم تصحيح المالك لـ 8187185291")
        
        try:
            bot.send_message(OWNER_ID, f"✅ تم تحديث هوية المالك بنجاح!\n\n🆔 هويتك: {OWNER_ID}")
        except Exception as e:
            logger.error(f"فشل إرسال تأكيد للمالك: {e}")
    else:
        bot.reply_to(message, "❌ لا تملك صلاحية هذا الأمر!")

@bot.message_handler(commands=['stats'])
def send_stats(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    try:
        stats = get_user_stats()
        daily_stats = get_daily_stats()
        avg_rating = get_average_rating()
        
        report = f"""
📊 **إحصائيات البوت** (الإصدار {BOT_VERSION}):

👤 **المالك:** {OWNER_ID}
⭐ **متوسط التقييم:** {avg_rating:.1f}/5

👥 **المستخدمين:**
• إجمالي المستخدمين: {stats['total_users']}
• المستخدمين النشطين (24 ساعة): {stats['active_users']}
• المستخدمين المحظورين: {stats['banned_users']}

📥 **التنزيلات:**
• إجمالي التنزيلات: {stats['total_downloads']}
• تنزيلات اليوم: {daily_stats['daily_downloads']}

📈 **نشاط اليوم:**
• مستخدمين جدد: {daily_stats['new_users']}
• أحداث البوت: {daily_stats['daily_actions']}

⏰ **التوقيت:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        bot.reply_to(message, report, parse_mode='Markdown')
        log_activity(message.from_user.id, "عرض الإحصائيات")
    except Exception as e:
        bot.reply_to(message, f"❌ حدث خطأ في جلب الإحصائيات: {str(e)}")
        log_error(f"Error in /stats: {str(e)}")

@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    msg = message.text.replace('/broadcast', '').strip()
    if not msg:
        bot.reply_to(message, "استخدام: /broadcast <الرسالة>\n\nمثال: /broadcast أهلاً بكم جميعاً!")
        return
        
    users = get_all_users()
    
    if not users:
        bot.reply_to(message, "❌ لا يوجد مستخدمين لإرسال الإذاعة إليهم")
        return
    
    confirm_msg = f"هل تريد إرسال الإذاعة لـ {len(users)} مستخدم؟\n\nالرسالة:\n{msg}"
    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.row(
        telebot.types.InlineKeyboardButton("✅ نعم", callback_data=f"broadcast_yes:{message.message_id}"),
        telebot.types.InlineKeyboardButton("❌ لا", callback_data="broadcast_no")
    )
    
    with open(f'broadcast_{message.message_id}.txt', 'w', encoding='utf-8') as f:
        f.write(msg)
    
    bot.reply_to(message, confirm_msg, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("broadcast_"))
def handle_broadcast_callback(call):
    if not is_owner(call.from_user.id):
        return
        
    if call.data == "broadcast_no":
        bot.answer_callback_query(call.id, "تم إلغاء الإذاعة")
        bot.edit_message_text("❌ تم إلغاء الإذاعة", call.message.chat.id, call.message.message_id)
        return
    
    if call.data.startswith("broadcast_yes:"):
        msg_id = call.data.split(":")[1]
        
        try:
            with open(f'broadcast_{msg_id}.txt', 'r', encoding='utf-8') as f:
                broadcast_msg = f.read()
                
            os.remove(f'broadcast_{msg_id}.txt')
        except:
            bot.answer_callback_query(call.id, "خطأ: لم يتم العثور على الرسالة")
            return
        
        bot.answer_callback_query(call.id, "بدء الإذاعة...")
        bot.edit_message_text("🔄 جارٍ إرسال الإذاعة...", call.message.chat.id, call.message.message_id)
        
        users = get_all_users()
        success = 0
        failed = 0
        
        for user_id in users:
            try:
                bot.send_message(user_id, broadcast_msg)
                success += 1
                time.sleep(0.1)
            except Exception as e:
                failed += 1
                logger.error(f"خطأ في الإذاعة لـ {user_id}: {e}")
        
        result_msg = f"✅ تم إنهاء الإذاعة:\n\n📤 نجحت: {success}\n❌ فشلت: {failed}"
        bot.edit_message_text(result_msg, call.message.chat.id, call.message.message_id)
        log_activity(call.from_user.id, f"بث رسالة لـ {success} مستخدم")

@bot.message_handler(commands=['ban'])
def ban_user_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    try:
        user_id = int(message.text.split()[1])
        ban_user(user_id)
        bot.reply_to(message, f"✅ تم حظر المستخدم: {user_id}")
        log_activity(message.from_user.id, f"حظر مستخدم {user_id}")
    except (IndexError, ValueError):
        bot.reply_to(message, "استخدام: /ban <ايدي المستخدم>\n\nمثال: /ban 123456789")

@bot.message_handler(commands=['unban'])
def unban_user_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    try:
        user_id = int(message.text.split()[1])
        unban_user(user_id)
        bot.reply_to(message, f"✅ تم رفع الحظر عن المستخدم: {user_id}")
        log_activity(message.from_user.id, f"رفع حظر مستخدم {user_id}")
    except (IndexError, ValueError):
        bot.reply_to(message, "استخدام: /unban <ايدي المستخدم>\n\nمثال: /unban 123456789")

@bot.message_handler(commands=['banned'])
def list_banned_users(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    banned_users = get_banned_users()
    if not banned_users:
        bot.reply_to(message, "❌ لا يوجد مستخدمين محظورين")
        return
        
    response = "👥 **قائمة المستخدمين المحظورين:**\n\n"
    for user in banned_users[:20]:
        username = f"@{user[1]}" if user[1] else "بدون اسم مستخدم"
        name = user[2] or "بدون اسم"
        response += f"🆔 `{user[0]}` - {name} ({username})\n"
    
    if len(banned_users) > 20:
        response += f"\n... و {len(banned_users) - 20} مستخدم آخر"
    
    bot.reply_to(message, response, parse_mode='Markdown')
    log_activity(message.from_user.id, "عرض قائمة المحظورين")

@bot.message_handler(commands=['export'])
def export_users_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    try:
        export_type = message.text.split()[1].lower()
        if export_type not in ['csv', 'json']:
            raise IndexError
    except IndexError:
        bot.reply_to(message, "استخدام: /export <csv|json>\n\nمثال: /export csv")
        return
        
    try:
        file_path = export_users(export_type)
        with open(file_path, 'rb') as f:
            bot.send_document(
                message.chat.id, 
                f,
                caption=f"📊 ملف تصدير المستخدمين ({export_type.upper()})"
            )
        
        os.remove(file_path)
        log_activity(message.from_user.id, f"تصدير بيانات {export_type}")
    except Exception as e:
        bot.reply_to(message, f"❌ حدث خطأ في التصدير: {str(e)}")

@bot.message_handler(commands=['setwelcome'])
def set_welcome_message(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    new_msg = message.text.replace('/setwelcome', '').strip()
    if not new_msg:
        current_msg = get_setting('welcome_msg')
        bot.reply_to(message, f"الرسالة الحالية:\n{current_msg}\n\nاستخدام: /setwelcome <الرسالة الجديدة>")
        return
        
    update_setting('welcome_msg', new_msg)
    bot.reply_to(message, "✅ تم تحديث رسالة الترحيب بنجاح")
    log_activity(message.from_user.id, "تحديث رسالة الترحيب")

@bot.message_handler(commands=['setsubscribe'])
def set_subscribe_message(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    new_msg = message.text.replace('/setsubscribe', '').strip()
    if not new_msg:
        current_msg = get_setting('subscribe_msg')
        bot.reply_to(message, f"الرسالة الحالية:\n{current_msg}\n\nاستخدام: /setsubscribe <الرسالة الجديدة>")
        return
        
    update_setting('subscribe_msg', new_msg)
    bot.reply_to(message, "✅ تم تحديث رسالة الاشتراك بنجاح")
    log_activity(message.from_user.id, "تحديث رسالة الاشتراك")

@bot.message_handler(commands=['subscription'])
def toggle_subscription(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    current_status = get_setting('forced_subscription')
    new_status = 0 if current_status == 1 else 1
    update_setting('forced_subscription', new_status)
    
    status_text = "تم تفعيل" if new_status == 1 else "تم تعطيل"
    bot.reply_to(message, f"✅ {status_text} الاشتراك الإجباري")
    log_activity(message.from_user.id, f"تغيير الاشتراك الإجباري: {new_status}")

@bot.message_handler(commands=['addchannel'])
def add_channel(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    try:
        parts = message.text.split()
        if len(parts) < 2:
            raise IndexError
            
        channel_id = parts[1]
        channel_name = " ".join(parts[2:]) if len(parts) > 2 else "قناة جديدة"
        
        if not channel_id.startswith('@') and not channel_id.startswith('-'):
            channel_id = '@' + channel_id
            
        conn = sqlite3.connect('tiktok_bot.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO channels (channel_id, channel_name, is_primary) VALUES (?, ?, 1)", 
                  (channel_id, channel_name))
        conn.commit()
        bot.reply_to(message, f"✅ تم إضافة القناة: {channel_name} ({channel_id})")
        log_activity(message.from_user.id, f"إضافة قناة: {channel_id}")
    except IndexError:
        bot.reply_to(message, "استخدام: /addchannel <معرف القناة> [اسم القناة]\n\nمثال: /addchannel @mychannel قناتي")
    finally:
        conn.close()

@bot.message_handler(commands=['maintenance'])
def toggle_maintenance(message):
    global MAINTENANCE_MODE
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    status = "✅ تم تفعيل وضع الصيانة" if MAINTENANCE_MODE else "❌ تم تعطيل وضع الصيانة"
    bot.reply_to(message, status)
    log_activity(message.from_user.id, f"تغيير وضع الصيانة: {MAINTENANCE_MODE}")

@bot.message_handler(commands=['logs'])
def send_logs(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    try:
        with open('bot.log', 'rb') as f:
            bot.send_document(message.chat.id, f, caption="📝 ملف سجلات البوت")
        log_activity(message.from_user.id, "تحميل ملف السجلات")
    except FileNotFoundError:
        bot.reply_to(message, "❌ ملف السجلات غير موجود")

@bot.message_handler(commands=['restart'])
def restart_bot(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    bot.reply_to(message, "🔄 جارٍ إعادة تشغيل البوت...")
    log_activity(message.from_user.id, "إعادة تشغيل البوت")
    python = sys.executable
    os.execl(python, python, *sys.argv)

@bot.message_handler(commands=['adminhelp'])
def admin_help(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    help_text = """
🛠️ **أوامر إدارة البوت:**

📊 **الإحصائيات:**
• `/stats` - عرض إحصائيات البوت

📢 **الإذاعة:**
• `/broadcast <رسالة>` - بث رسالة لجميع المستخدمين

👥 **إدارة المستخدمين:**
• `/ban <ايدي>` - حظر مستخدم
• `/unban <ايدي>` - رفع حظر مستخدم  
• `/banned` - قائمة المحظورين
• `/export <csv|json>` - تصدير بيانات المستخدمين

⚙️ **الإعدادات:**
• `/setwelcome <رسالة>` - تغيير رسالة الترحيب
• `/setsubscribe <رسالة>` - تغيير رسالة الاشتراك
• `/subscription` - تفعيل/تعطيل الاشتراك الإجباري
• `/addchannel <معرف> [اسم]` - إضافة قناة للاشتراك
• `/togglenotify` - تفعيل/تعطيل إشعارات المستخدمين الجدد

🔧 **أدوات النظام:**
• `/maintenance` - تفعيل/تعطيل وضع الصيانة
• `/logs` - الحصول على ملف السجلات
• `/restart` - إعادة تشغيل البوت
• `/adminhelp` - عرض هذه المساعدة
    """
    bot.reply_to(message, help_text, parse_mode='Markdown')
    log_activity(message.from_user.id, "طلب مساعدة الأدمن")

@bot.message_handler(commands=['svvab'])
def handle_svvab(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ هذا الأمر متاح فقط للمالك!")
        return
        
    if message.reply_to_message:
        target_msg = message.reply_to_message
        content = ""
        
        if target_msg.text:
            content = target_msg.text
        elif target_msg.caption:
            content = target_msg.caption
        else:
            content = "⚠️ لا يوجد نص في هذه الرسالة"
            
        user_info = f"👤 المستخدم: @{target_msg.from_user.username} ({target_msg.from_user.id})"
        date_info = f"📅 التاريخ: {datetime.fromtimestamp(target_msg.date).strftime('%Y-%m-%d %H:%M:%S')}"
        
        response = f"📝 **محتوى الرسالة:**\n\n{content}\n\n{user_info}\n{date_info}"
        bot.reply_to(message, response, parse_mode='Markdown')
        log_activity(message.from_user.id, "استخدم أمر svvab")
    else:
        bot.reply_to(message, "❌ الرجاء الرد على الرسالة التي تريد نسخ محتواها باستخدام الأمر /svvab")

# ========== معالجة روابط التيك توك ========== #
@bot.message_handler(func=lambda message: re.search(r'(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)', message.text))
def handle_tiktok_link(message):
    user_id = message.from_user.id
    if MAINTENANCE_MODE:
        bot.reply_to(message, "⛔ البوت قيد الصيانة حالياً، الرجاء المحاولة لاحقاً")
        return
        
    if is_banned(user_id):
        bot.reply_to(message, "❌ تم حظرك من استخدام البوت")
        return
        
    if get_setting('forced_subscription') == 1 and not is_subscribed(user_id):
        subscribe_msg = get_setting('subscribe_msg')
        keyboard = telebot.types.InlineKeyboardMarkup()
        keyboard.add(telebot.types.InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subscription"))
        bot.reply_to(message, subscribe_msg, reply_markup=keyboard)
        return
        
    processing_msg = bot.reply_to(message, "⏳ جارٍ تحميل الفيديو، الرجاء الانتظار...")
    
    try:
        video_url = get_tiktok_video(message.text)
        if video_url:
            bot.send_video(message.chat.id, video_url, caption="✅ تم تحميل الفيديو بنجاح!\n\n📥 تم التنزيل بواسطة @Jvrsbot")
            increment_download_count(user_id)
            log_download(user_id, message.text, "success")
            log_activity(user_id, "تنزيل فيديو ناجح")
            bot.delete_message(message.chat.id, processing_msg.message_id)
        else:
            bot.edit_message_text("❌ فشل في تحميل الفيديو، الرجاء المحاولة برابط آخر", 
                                 message.chat.id, processing_msg.message_id)
            log_download(user_id, message.text, "failed")
            log_activity(user_id, "فشل تنزيل فيديو")
    except Exception as e:
        bot.edit_message_text(f"❌ حدث خطأ أثناء معالجة الفيديو: {str(e)}", 
                             message.chat.id, processing_msg.message_id)
        logger.error(f"خطأ في معالجة الفيديو: {str(e)}")
        log_download(user_id, message.text, "error")
        log_activity(user_id, "خطأ في التنزيل")

# ========== معالجة الرسائل الأخرى ========== #
@bot.message_handler(func=lambda message: True, content_types=['photo', 'video', 'document', 'audio', 'text'])
def handle_other_messages(message):
    user_id = message.from_user.id
    if is_banned(user_id) or MAINTENANCE_MODE:
        return
        
    if message.text and message.text.startswith('/'):
        return
        
    if user_id in user_reporting and user_reporting[user_id]:
        return
        
    if message.content_type == 'text':
        bot.reply_to(message, "🔗 الرجاء إرسال رابط فيديو من التيك توك فقط\n\nاستخدم /help لعرض الأوامر المتاحة")

# ========== نظام Keep Alive ========== #
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ البوت يعمل بشكل طبيعي!"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def keep_alive():
    """ترسل طلبات منتظمة لمنع الخمول"""
    base_url = os.getenv("BASE_URL")
    if not base_url:
        logger.warning("BASE_URL غير محدد، تعطيل وظيفة المنبه")
        return
        
    while True:
        try:
            response = requests.get(base_url, timeout=10)
            logger.info(f"تم إرسال طلب إبقاء نشط إلى {base_url} - الحالة: {response.status_code}")
        except Exception as e:
            logger.error(f"فشل في إرسال طلب الإبقاء: {str(e)}")
        
        # الانتظار لمدة 5 دقائق قبل الإرسال التالي
        time.sleep(300)

# ========== بدء تشغيل البوت ========== #
if __name__ == '__main__':
    try:
        logger.info("جارٍ تشغيل البوت...")
        bot_info = bot.get_me()
        logger.info(f"تم تشغيل البوت: @{bot_info.username}")
        
        # تعيين الأوامر المرئية
        set_bot_commands()
        set_admin_commands()
        
        # بدء خادم Flask في خيط منفصل
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info("تم بدء خادم Flask")
        
        # بدء وظيفة المنبه في خيط منفصل
        keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
        keep_alive_thread.start()
        logger.info("تم بدء وظيفة المنبه (Keep Alive)")
        
        # إرسال إشعار للمالك
        if OWNER_ID:
            try:
                bot.send_message(OWNER_ID, f"✅ البوت يعمل الآن!\n\n🤖 اسم البوت: @{bot_info.username}\n📱 الإصدار: {BOT_VERSION}")
            except Exception as e:
                logger.error(f"فشل إرسال إشعار للمالك: {e}")
        
        # حل مشكلة التعارض مع إعادة المحاولة
        bot_running = True
        retry_delay = 5  # البدء بـ 5 ثواني
        max_retry_delay = 60  # أقصى وقت انتظار 60 ثانية
        
        while bot_running:
            try:
                logger.info(f"بدء استقبال التحديثات (المهلة: {retry_delay} ثانية)...")
                
                # استخدم long polling مع skip_pending=True
                bot.infinity_polling(timeout=60, skip_pending=True)
                
                logger.info("تم إيقاف استقبال التحديثات بشكل طبيعي.")
                break  # الخروج من الحلقة إذا تم إيقاف البوت بشكل طبيعي
                
            except telebot.apihelper.ApiTelegramException as api_error:
                if api_error.error_code == 409:
                    logger.error(f"تعارض في الطلبات (409): {api_error.description}")
                    logger.info("يبدو أن هناك نسخة أخرى تعمل. جاري إعادة المحاولة بعد 10 ثواني...")
                    # في حالة 409، ننتظر 10 ثواني ثم نعيد المحاولة
                    time.sleep(10)
                    # نعيد تعيين تأخير إعادة المحاولة
                    retry_delay = 5
                else:
                    logger.error(f"خطأ في واجهة برمجة تيليجرام: {api_error}")
                    logger.info(f"إعادة المحاولة بعد {retry_delay} ثواني...")
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, max_retry_delay)
                    
            except Exception as e:
                logger.error(f"خطأ عام في polling: {e}")
                logger.info(f"إعادة المحاولة بعد {retry_delay} ثواني...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)
        
        logger.info("تم إيقاف البوت")
    except Exception as e:
        logger.exception(f"خطأ فادح: {str(e)}")
        try:
            if OWNER_ID:
                bot.send_message(OWNER_ID, f"⛔ البوت توقف بسبب خطأ:\n\n`{str(e)}`", parse_mode='Markdown')
        except:
            pass
        sys.exit(1)

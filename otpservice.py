# getpaid_otp_bot.py - Complete Full Script (2000+ lines)
import os
import re
import json
import time
import hmac
import base64
import struct
import secrets
import requests
import asyncio
import random
import string
import hashlib
import threading
import csv
import io
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List, Any
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from bs4 import BeautifulSoup

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8343363851:AAEE8FbOno5w-FPmF-JdglznbeS2_tElBd4"
ADMIN_ID = 7064572216
BOT_USERNAME = "OtpServices2_Bot"
MAIN_CHANNEL = "@OtpService2C"
OTP_GROUP = "@OtpService2G"
WEB_LOGIN_URL = "http://139.99.9.4/ints/login"
WEB_API_URL = "http://139.99.9.4/ints/agent/SMSCDRStats"
WEB_USER = "Nazim1"
WEB_PASS = "Nazim1"

OTP_EARN_AMOUNT = 0.30
MIN_WITHDRAW = 500

DATA_FILE = "bot_data.json"
NUMBERS_FILE = "numbers.json"
TEMP_MAIL_FILE = "temp_mail.json"
LOG_FILE = "bot_log.txt"

SECRET_KEY_STATE = 1
WITHDRAW_STATE = 2
BROADCAST_STATE = 3

flask_app = Flask(__name__)

user_balances = {}
user_numbers = {}
active_orders = {}
totp_secrets = {}
available_numbers = {}
pending_withdrawals = {}
user_transactions = {}
user_stats = {}
temp_mail_data = {}
mail_check_tasks = {}
broadcast_tasks = {}
pending_numbers = {}
country_prices = {}
user_referrals = {}
referral_earnings = {}
user_settings = {}
banned_users = {}
user_languages = {}
otp_cache = {}
web_session = None
last_web_login = 0

def log_message(msg):
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(f"{datetime.now().isoformat()} - {msg}\n")
    except: pass

def load_data():
    global user_balances, totp_secrets, available_numbers, pending_withdrawals, user_transactions, user_stats, temp_mail_data, country_prices, user_referrals, referral_earnings, user_settings, banned_users, user_languages
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            user_balances = data.get('balances', {})
            totp_secrets = data.get('totp', {})
            pending_withdrawals = data.get('withdrawals', {})
            user_transactions = data.get('transactions', {})
            user_stats = data.get('stats', {})
            country_prices = data.get('prices', {})
            user_referrals = data.get('referrals', {})
            referral_earnings = data.get('referral_earnings', {})
            user_settings = data.get('settings', {})
            banned_users = data.get('banned', {})
            user_languages = data.get('languages', {})
    except FileNotFoundError:
        pass
    try:
        with open(NUMBERS_FILE, 'r') as f:
            available_numbers = json.load(f)
    except FileNotFoundError:
        available_numbers = {
            "Germany": ["+491551329004", "+491551329005", "+491551329006", "+491551329007", "+491551329008"],
            "Peru": ["+51927234335", "+51904205672", "+51925468328", "+51927023451", "+51901571635"],
            "Myanmar": ["+9591234567", "+9591234568", "+9591234569"],
            "Tanzania": ["+255123456789", "+255123456790", "+255123456791"],
            "Syria": ["+963123456789", "+963123456790", "+963123456791"]
        }
    try:
        with open(TEMP_MAIL_FILE, 'r') as f:
            temp_mail_data = json.load(f)
    except FileNotFoundError:
        temp_mail_data = {}

def save_data():
    with open(DATA_FILE, 'w') as f:
        json.dump({
            'balances': user_balances,
            'totp': totp_secrets,
            'withdrawals': pending_withdrawals,
            'transactions': user_transactions,
            'stats': user_stats,
            'prices': country_prices,
            'referrals': user_referrals,
            'referral_earnings': referral_earnings,
            'settings': user_settings,
            'banned': banned_users,
            'languages': user_languages
        }, f, indent=2)
    with open(NUMBERS_FILE, 'w') as f:
        json.dump(available_numbers, f, indent=2)
    with open(TEMP_MAIL_FILE, 'w') as f:
        json.dump(temp_mail_data, f, indent=2)

load_data()

class WebPanelClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        self.logged_in = False
    
    def solve_captcha(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        math_match = re.search(r'(\d+)\s*\+\s*(\d+)\s*=', html)
        if math_match:
            return str(int(math_match.group(1)) + int(math_match.group(2)))
        num_match = re.search(r'(\d{2,4})', html)
        if num_match:
            return num_match.group(1)
        return None
    
    def login(self):
        global last_web_login
        try:
            if time.time() - last_web_login < 300 and self.logged_in:
                return True
            login_page = self.session.get(WEB_LOGIN_URL, timeout=10)
            if login_page.status_code != 200:
                return False
            captcha = self.solve_captcha(login_page.text)
            login_data = {'username': WEB_USER, 'password': WEB_PASS}
            if captcha:
                login_data['captcha'] = captcha
            response = self.session.post(WEB_LOGIN_URL, data=login_data, timeout=10)
            self.logged_in = response.status_code == 200
            if self.logged_in:
                last_web_login = time.time()
                log_message("Web panel login successful")
            return self.logged_in
        except Exception as e:
            log_message(f"Login error: {e}")
            return False
    
    def get_otp(self, number):
        try:
            if not self.login():
                return None
            response = self.session.get(f"{WEB_API_URL}?number={number}", timeout=10)
            if response.status_code == 200:
                text = response.text
                otp = re.search(r'\b\d{4,6}\b', text)
                if otp:
                    service = "Facebook"
                    services = {'whatsapp': 'WhatsApp', 'telegram': 'Telegram', 'imo': 'IMO', 'instagram': 'Instagram', 'tiktok': 'TikTok', 'google': 'Google', 'twitter': 'Twitter', 'snapchat': 'Snapchat', 'linkedin': 'LinkedIn', 'facebook': 'Facebook', 'fb': 'Facebook'}
                    for key, val in services.items():
                        if key in text.lower():
                            service = val
                            break
                    return {'otp': otp.group(), 'service': service, 'message': text[:200]}
            return None
        except Exception as e:
            log_message(f"OTP fetch error: {e}")
            return None

web_panel = WebPanelClient()

class TOTPGenerator:
    @staticmethod
    def generate_secret():
        return base64.b32encode(secrets.token_bytes(20)).decode('utf-8')
    
    @staticmethod
    def get_code(secret):
        try:
            secret = secret.upper().replace(' ', '')
            padding = 8 - (len(secret) % 8)
            if padding != 8:
                secret += '=' * padding
            key = base64.b32decode(secret)
            counter = int(time.time()) // 30
            msg = struct.pack('>Q', counter)
            h = hmac.new(key, msg, 'sha1').digest()
            offset = h[-1] & 0x0F
            code = (struct.unpack('>I', h[offset:offset+4])[0] & 0x7FFFFFFF) % 1000000
            return f"{code:06d}"
        except:
            return "000000"
    
    @staticmethod
    def time_left():
        return 30 - (int(time.time()) % 30)

class TempMailService:
    @staticmethod
    def generate_email():
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        domains = ['@mailto.plus', '@tempmail.plus', '@tmpmail.org', '@guerrillamail.com', '@10minutemail.net', '@temp-mail.org']
        return username + random.choice(domains)
    
    @staticmethod
    def check_inbox(email):
        try:
            import urllib.parse
            encoded = urllib.parse.quote(email)
            response = requests.get(f"https://api.mail.tm/messages/{encoded}", timeout=5)
            if response.status_code == 200:
                return response.json().get('hydra:member', [])
        except: pass
        try:
            response = requests.get(f"https://www.guerrillamail.com/ajax.php?f=get_email_list&email={email}", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('list'):
                    return data['list']
        except: pass
        return []
    
    @staticmethod
    def wait_for_email(email, timeout=60):
        start = time.time()
        while time.time() - start < timeout:
            messages = TempMailService.check_inbox(email)
            if messages:
                return messages[0]
            time.sleep(3)
        return None

temp_mail = TempMailService()

def get_main_keyboard(is_admin=False):
    keyboard = [
        [InlineKeyboardButton("📱 Number", callback_data="get_number")],
        [InlineKeyboardButton("📧 TempMail", callback_data="tempmail")],
        [InlineKeyboardButton("🔐 2FA", callback_data="twofa")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("👥 Referral", callback_data="referral")],
        [InlineKeyboardButton("📊 Stats", callback_data="mystats")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("📢 Support", callback_data="support")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    if is_admin:
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

def get_number_display_keyboard(numbers, country):
    keyboard = []
    for i, num in enumerate(numbers[:3], 1):
        keyboard.append([InlineKeyboardButton(f"📱 Number {i}: {num}", callback_data=f"copy_{num}")])
    keyboard.append([InlineKeyboardButton("📢 OTP Group", url=f"https://t.me/{OTP_GROUP[1:]}")])
    keyboard.append([InlineKeyboardButton("📢 Main Channel", url=f"https://t.me/{MAIN_CHANNEL[1:]}")])
    keyboard.append([InlineKeyboardButton("🔄 Change Number", callback_data="get_number")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh OTP", callback_data=f"refresh_numbers")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Home", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)

def get_otp_keyboard(number, country, has_otp=False):
    keyboard = []
    if has_otp:
        keyboard.append([InlineKeyboardButton("🔄 Check OTP Again", callback_data=f"check_otp_{number}")])
    else:
        keyboard.append([InlineKeyboardButton("🔄 Check OTP", callback_data=f"check_otp_{number}")])
    keyboard.append([InlineKeyboardButton("📢 OTP Group", url=f"https://t.me/{OTP_GROUP[1:]}")])
    keyboard.append([InlineKeyboardButton("📢 Main Channel", url=f"https://t.me/{MAIN_CHANNEL[1:]}")])
    keyboard.append([InlineKeyboardButton("🔄 Change Number", callback_data="get_number")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Home", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ Add Number", callback_data="admin_add_number")],
        [InlineKeyboardButton("📤 Bulk Upload", callback_data="admin_bulk_upload")],
        [InlineKeyboardButton("🗑 Remove Number", callback_data="admin_remove_number")],
        [InlineKeyboardButton("📋 List Numbers", callback_data="admin_list_numbers")],
        [InlineKeyboardButton("➕ Add Country", callback_data="admin_add_country")],
        [InlineKeyboardButton("💰 Set Country Price", callback_data="admin_set_price")],
        [InlineKeyboardButton("💸 Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("💸 Process Withdrawals", callback_data="admin_process_withdraw")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("📨 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("👥 Users List", callback_data="admin_users")],
        [InlineKeyboardButton("💳 Transaction Log", callback_data="admin_transactions")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ Unban User", callback_data="admin_unban")],
        [InlineKeyboardButton("📥 Export Data", callback_data="admin_export")],
        [InlineKeyboardButton("🔄 Reset System", callback_data="admin_reset")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_2fa_keyboard(secret):
    code = TOTPGenerator.get_code(secret)
    remaining = TOTPGenerator.time_left()
    keyboard = [
        [InlineKeyboardButton(f"🔄 Refresh ({remaining}s)", callback_data="2fa_refresh")],
        [InlineKeyboardButton("📋 Copy Code", callback_data=f"2fa_copy_{code}")],
        [InlineKeyboardButton("📋 Copy Secret", callback_data="2fa_copy_secret")],
        [InlineKeyboardButton("🔄 New Secret", callback_data="2fa_new_secret")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard), code, remaining

def get_tempmail_keyboard(email):
    keyboard = [
        [InlineKeyboardButton("📋 Copy Email", callback_data=f"copy_email_{email}")],
        [InlineKeyboardButton("🔄 Check Inbox", callback_data="check_inbox")],
        [InlineKeyboardButton("⏳ Wait for Email", callback_data="wait_email")],
        [InlineKeyboardButton("🆕 New Email", callback_data="tempmail")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_settings_keyboard(user_id):
    lang = user_languages.get(user_id, 'bn')
    keyboard = [
        [InlineKeyboardButton("🇧🇩 Bengali" + (" ✅" if lang == 'bn' else ""), callback_data="set_lang_bn")],
        [InlineKeyboardButton("🇬🇧 English" + (" ✅" if lang == 'en' else ""), callback_data="set_lang_en")],
        [InlineKeyboardButton("🔔 Notifications " + ("✅" if user_settings.get(user_id, {}).get('notify', True) else "❌"), callback_data="toggle_notify")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_referral_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("📋 Copy Referral Link", callback_data="copy_ref_link")],
        [InlineKeyboardButton("👥 My Referrals", callback_data="my_referrals")],
        [InlineKeyboardButton("💰 Referral Earnings", callback_data="ref_earnings")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_language_text(key, user_id='bn'):
    texts = {
        'welcome': {'bn': '🎉 *GetPaid OTP 2.0 বটে স্বাগতম*', 'en': '🎉 *Welcome to GetPaid OTP 2.0 Bot*'},
        'balance': {'bn': '💰 *আপনার ব্যালেন্স*', 'en': '💰 *Your Balance*'},
        'otp_received': {'bn': '✅ *OTP প্রাপ্ত হয়েছে*', 'en': '✅ *OTP Received*'},
        'no_numbers': {'bn': '❌ *কোন নম্বর উপলব্ধ নেই*', 'en': '❌ *No numbers available*'},
        'insufficient': {'bn': '❌ *পর্যাপ্ত ব্যালেন্স নেই*', 'en': '❌ *Insufficient balance*'},
    }
    return texts.get(key, {}).get(user_languages.get(user_id, 'bn'), texts.get(key, {}).get('en', ''))

async def start(update, context):
    user = update.effective_user
    user_id = user.id
    is_admin = user_id == ADMIN_ID
    
    if user_id in banned_users:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    
    if user_id not in user_balances:
        user_balances[user_id] = 0
        user_stats[user_id] = {'joined': datetime.now().isoformat(), 'total_orders': 0, 'total_earned': 0, 'total_otps': 0}
        user_settings[user_id] = {'notify': True, 'lang': 'bn'}
        user_languages[user_id] = 'bn'
        save_data()
        
        if 'referrer' in context.args:
            try:
                referrer = int(context.args[0])
                if referrer != user_id and referrer in user_balances:
                    user_referrals.setdefault(referrer, []).append(user_id)
                    referral_earnings[referrer] = referral_earnings.get(referrer, 0) + 5
                    user_balances[referrer] = user_balances.get(referrer, 0) + 5
                    save_data()
                    await context.bot.send_message(referrer, f"👥 New referral! +5 TK added to your balance.")
            except: pass
    
    welcome_text = f"""🎉 *Welcome to GetPaid OTP 2.0 Bot* 🎉

👤 *User:* {user.first_name}
🆔 *ID:* `{user_id}`
💰 *Balance:* {user_balances.get(user_id, 0):.2f} TK
📊 *Total Earned:* {user_stats.get(user_id, {}).get('total_earned', 0):.2f} TK

⚡ *How it works:*
• Click 📱 Number - Get a free virtual number
• Receive OTP on that number
• Earn 0.30 TK per OTP received
• Minimum withdrawal: {MIN_WITHDRAW} TK

🔗 *Referral Program:*
• Invite friends and earn 5 TK each!
• Your referral link: `https://t.me/{BOT_USERNAME}?start={user_id}`

👇 *Choose an option:*"""
    
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin))

async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    is_admin = user_id == ADMIN_ID
    
    if user_id in banned_users:
        await query.edit_message_text("❌ You are banned from using this bot.")
        return
    
    if data == "back_main":
        await query.edit_message_text("🏠 *Main Menu*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin))
    
    elif data == "help":
        help_text = """📚 *Help Center* - GetPaid OTP 2.0

🔹 *Number* - Get a free virtual number
   • Click Number button
   • Choose any number from displayed list
   • Click copy to select that number
   • Wait for OTP (1-3 minutes)
   • Earn 0.30 TK per OTP

🔹 *TempMail* - Get temporary email
   • Click TempMail button
   • Email generated instantly
   • Auto-check for incoming mails
   • Copy and use anywhere

🔹 *2FA* - TOTP Authenticator
   • Click 2FA button
   • Send your secret key from Google Authenticator
   • Get 6-digit code with live countdown

🔹 *Balance* - Check earnings
   • View balance and statistics

🔹 *Withdraw* - Withdraw earnings
   • Minimum: 500 TK
   • Methods: bKash, Nagad, Rocket

🔹 *Referral* - Earn more
   • Share your referral link
   • Earn 5 TK per referral

📢 *Channel:* {MAIN_CHANNEL}
👥 *Group:* {OTP_GROUP}
👨‍💻 *Support:* @GetPaidAdmin"""
        await query.edit_message_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]))
    
    elif data == "support":
        support_text = f"""📞 *Support Center*

📢 *Main Channel:* {MAIN_CHANNEL}
👥 *OTP Group:* {OTP_GROUP}

❓ *FAQ:*
• Q: How to earn?
  A: Get number → Receive OTP → Earn 0.30 TK

• Q: Minimum withdrawal?
  A: {MIN_WITHDRAW} TK

• Q: How long does OTP take?
  A: Usually 1-3 minutes

• Q: Can I use multiple numbers?
  A: Yes, you can get new numbers anytime

👨‍💻 *Admin:* @GetPaidAdmin

For any issues, contact admin."""
        await query.edit_message_text(support_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{MAIN_CHANNEL[1:]}")],
            [InlineKeyboardButton("👥 Join Group", url=f"https://t.me/{OTP_GROUP[1:]}")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
        ]))
    
    elif data == "get_number":
        if not available_numbers:
            await query.edit_message_text("❌ *No numbers available*\nContact admin to add numbers.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]))
            return
        
        all_numbers = []
        for country, nums in available_numbers.items():
            for num in nums:
                all_numbers.append({'country': country, 'number': num})
        
        if len(all_numbers) < 3:
            await query.edit_message_text("❌ *Insufficient numbers*\nContact admin.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]))
            return
        
        selected = random.sample(all_numbers, min(3, len(all_numbers)))
        selected_numbers = [s['number'] for s in selected]
        selected_country = selected[0]['country']
        
        context.user_data['selected_numbers'] = selected_numbers
        context.user_data['selected_country'] = selected_country
        
        await query.edit_message_text(
            f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
            f"🇧🇩 *নাজার যাচাই সম্পন্ন*\n"
            f"🌍 *দেশ ও দাম:* {selected_country} (0.00TK)\n\n"
            f"📱 *Number 1:* `{selected_numbers[0]}`\n"
            f"📱 *Number 2:* `{selected_numbers[1]}`\n"
            f"📱 *Number 3:* `{selected_numbers[2]}`\n\n"
            f"🔑 *OTP কোড:* `Waiting...`\n\n"
            f"✅ *NUMBER VERIFIED SUCCESSFULLY*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_number_display_keyboard(selected_numbers, selected_country)
        )
    
    elif data == "refresh_numbers":
        if not available_numbers:
            await query.edit_message_text("❌ No numbers available", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]))
            return
        
        all_numbers = []
        for country, nums in available_numbers.items():
            for num in nums:
                all_numbers.append({'country': country, 'number': num})
        
        if len(all_numbers) < 3:
            await query.edit_message_text("❌ Insufficient numbers", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]))
            return
        
        selected = random.sample(all_numbers, min(3, len(all_numbers)))
        selected_numbers = [s['number'] for s in selected]
        selected_country = selected[0]['country']
        
        context.user_data['selected_numbers'] = selected_numbers
        context.user_data['selected_country'] = selected_country
        
        await query.edit_message_text(
            f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
            f"🇧🇩 *নাজার যাচাই সম্পন্ন*\n"
            f"🌍 *দেশ ও দাম:* {selected_country} (0.00TK)\n\n"
            f"📱 *Number 1:* `{selected_numbers[0]}`\n"
            f"📱 *Number 2:* `{selected_numbers[1]}`\n"
            f"📱 *Number 3:* `{selected_numbers[2]}`\n\n"
            f"🔑 *OTP কোড:* `Waiting...`\n\n"
            f"✅ *NUMBER VERIFIED SUCCESSFULLY*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_number_display_keyboard(selected_numbers, selected_country)
        )
    
    elif data.startswith("copy_"):
        number = data.replace("copy_", "")
        await query.answer(f"✅ Copied: {number}", show_alert=True)
        
        active_orders[user_id] = {
            'number': number,
            'country': context.user_data.get('selected_country', 'Unknown'),
            'start_time': time.time(),
            'status': 'waiting',
            'otp': None,
            'service': None
        }
        
        asyncio.create_task(check_otp_background(context, user_id, number, query.message.chat_id, query.message.message_id))
    
    elif data.startswith("check_otp_"):
        number = data.replace("check_otp_", "")
        if user_id in active_orders and active_orders[user_id].get('otp'):
            otp_data = active_orders[user_id]
            await query.edit_message_text(
                f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
                f"🇧🇩 *নাজার যাচাই সম্পন্ন*\n"
                f"🌍 *দেশ ও দাম:* {otp_data.get('country', 'Unknown')} (0.00TK)\n\n"
                f"🔑 *OTP কোড:* `{otp_data['otp']}` ✅\n\n"
                f"🔧 *Service:* {otp_data.get('service', 'Unknown')}\n\n"
                f"💰 *Earned:* +{OTP_EARN_AMOUNT} TK\n"
                f"💵 *Balance:* {user_balances.get(user_id, 0):.2f} TK\n\n"
                f"✅ *NUMBER VERIFIED SUCCESSFULLY*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_otp_keyboard(number, otp_data.get('country', 'Unknown'), True)
            )
        else:
            result = web_panel.get_otp(number)
            if result and result.get('otp'):
                otp = result['otp']
                service = result.get('service', 'Unknown')
                
                user_balances[user_id] = user_balances.get(user_id, 0) + OTP_EARN_AMOUNT
                user_stats[user_id]['total_orders'] = user_stats[user_id].get('total_orders', 0) + 1
                user_stats[user_id]['total_earned'] = user_stats[user_id].get('total_earned', 0) + OTP_EARN_AMOUNT
                user_stats[user_id]['total_otps'] = user_stats[user_id].get('total_otps', 0) + 1
                save_data()
                
                active_orders[user_id] = {
                    'number': number,
                    'country': context.user_data.get('selected_country', 'Unknown'),
                    'otp': otp,
                    'service': service
                }
                
                await query.edit_message_text(
                    f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
                    f"🇧🇩 *নাজার যাচাই সম্পন্ন*\n"
                    f"🌍 *দেশ ও দাম:* {context.user_data.get('selected_country', 'Unknown')} (0.00TK)\n\n"
                    f"🔑 *OTP কোড:* `{otp}` ✅\n\n"
                    f"🔧 *Service:* {service}\n\n"
                    f"💰 *Earned:* +{OTP_EARN_AMOUNT} TK\n"
                    f"💵 *Balance:* {user_balances[user_id]:.2f} TK\n\n"
                    f"✅ *NUMBER VERIFIED SUCCESSFULLY*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_otp_keyboard(number, context.user_data.get('selected_country', 'Unknown'), True)
                )
                
                await context.bot.send_message(OTP_GROUP, 
                    f"🔐 *GetPaid OTP 2.0 | OTP RCV*\n\n"
                    f"📱 *Number:* `{number[-10:]}`\n"
                    f"🌍 *Country:* {context.user_data.get('selected_country', 'Unknown')}\n"
                    f"🔧 *Service:* {service}\n"
                    f"✅ *Status:* CLAIMED\n"
                    f"🔑 *OTP Code:* `{otp}`\n\n"
                    f"`#{otp} is your {service} verification code`\n\n"
                    f"🔗 @{BOT_USERNAME} | {MAIN_CHANNEL}", 
                    parse_mode=ParseMode.MARKDOWN)
                
                await context.bot.send_message(user_id,
                    f"🔐 *OTP Received!*\n\n"
                    f"📱 *Number:* `{number[-10:]}`\n"
                    f"🔧 *Service:* {service}\n"
                    f"🔑 *OTP:* `{otp}`\n\n"
                    f"💰 *+{OTP_EARN_AMOUNT} TK added!*\n"
                    f"💵 *New Balance:* {user_balances[user_id]:.2f} TK",
                    parse_mode=ParseMode.MARKDOWN)
            else:
                await query.answer("Still waiting for OTP... Please wait 1-2 minutes", show_alert=True)
    
    elif data == "twofa":
        await query.edit_message_text(
            "🔐 *2FA Authenticator*\n\n"
            "📝 *Send your Authenticator Secret Key*\n\n"
            "Example: `JBSWY3DPEHPK3PXP`\n\n"
            "You can get this key from:\n"
            "• Google Authenticator\n"
            "• Microsoft Authenticator\n"
            "• Any 2FA app\n\n"
            "Type `/cancel` to cancel",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]])
        )
        return SECRET_KEY_STATE
    
    elif data == "2fa_refresh":
        if user_id in totp_secrets:
            secret = totp_secrets[user_id]
            code = TOTPGenerator.get_code(secret)
            remaining = TOTPGenerator.time_left()
            kb, _, _ = get_2fa_keyboard(secret)
            await query.edit_message_text(
                f"🔐 *2FA Authenticator*\n\n"
                f"🔑 *Your Secret Key:*\n`{secret}`\n\n"
                f"🔢 *Current Code:* `{code}`\n"
                f"⏱ *Valid for:* {remaining} seconds\n\n"
                f"💡 Use this code for 2FA verification\n"
                f"• Works with Google Authenticator\n"
                f"• Code changes every 30 seconds",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
        else:
            await query.edit_message_text("❌ No secret key found. Please send your secret key first.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]))
    
    elif data == "2fa_new_secret":
        new_secret = TOTPGenerator.generate_secret()
        totp_secrets[user_id] = new_secret
        save_data()
        code = TOTPGenerator.get_code(new_secret)
        remaining = TOTPGenerator.time_left()
        kb, _, _ = get_2fa_keyboard(new_secret)
        await query.edit_message_text(
            f"🔐 *New 2FA Secret Generated*\n\n"
            f"🔑 *Your New Secret Key:*\n`{new_secret}`\n\n"
            f"🔢 *Current Code:* `{code}`\n"
            f"⏱ *Valid for:* {remaining} seconds\n\n"
            f"⚠️ Save this secret key in your 2FA app!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
    
    elif data.startswith("2fa_copy_"):
        code = data.replace("2fa_copy_", "")
        await query.answer(f"✅ Code copied: {code}", show_alert=True)
    
    elif data == "2fa_copy_secret":
        if user_id in totp_secrets:
            await query.answer(f"✅ Secret key copied!", show_alert=True)
    
    elif data == "tempmail":
        email = temp_mail.generate_email()
        temp_mail_data[user_id] = {'email': email, 'created': time.time(), 'messages': [], 'last_check': 0}
        save_data()
        
        if user_id in mail_check_tasks:
            mail_check_tasks[user_id].cancel()
        mail_check_tasks[user_id] = asyncio.create_task(auto_check_mail(context, user_id))
        
        await query.edit_message_text(
            f"📧 *Your Temporary Email*\n\n"
            f"📨 `{email}`\n\n"
            f"✅ Email is ready!\n"
            f"📬 Incoming mails will appear here automatically.\n"
            f"⏱ Email expires in 60 minutes.\n\n"
            f"💡 Copy this email and use it anywhere.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_tempmail_keyboard(email)
        )
    
    elif data == "check_inbox":
        if user_id in temp_mail_data:
            email = temp_mail_data[user_id]['email']
            messages = temp_mail.check_inbox(email)
            
            if messages:
                temp_mail_data[user_id]['messages'] = messages
                save_data()
                msg = "📬 *Your Inbox*\n\n"
                for m in messages[:5]:
                    msg += f"📧 *From:* {m.get('from', 'Unknown')}\n"
                    msg += f"📝 *Subject:* {m.get('subject', 'No subject')}\n"
                    body = m.get('body', m.get('text', ''))[:150]
                    msg += f"💬 {body}...\n"
                    msg += "➖➖➖➖➖➖\n\n"
                await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=get_tempmail_keyboard(email))
            else:
                await query.edit_message_text("📭 *No messages yet*\n\nWaiting for incoming emails...\n💡 Send a test email to see it here!", parse_mode=ParseMode.MARKDOWN, reply_markup=get_tempmail_keyboard(email))
        else:
            await query.edit_message_text("❌ No active email. Generate a new one.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🆕 New Email", callback_data="tempmail")]]))
    
    elif data == "wait_email":
        if user_id in temp_mail_data:
            email = temp_mail_data[user_id]['email']
            await query.edit_message_text("⏳ *Waiting for email...*\n\nThis may take up to 60 seconds.\nPlease wait...", parse_mode=ParseMode.MARKDOWN)
            message = temp_mail.wait_for_email(email, 60)
            if message:
                temp_mail_data[user_id]['messages'] = [message]
                save_data()
                await query.edit_message_text(
                    f"📬 *New Email Received!*\n\n"
                    f"📧 *From:* {message.get('from', 'Unknown')}\n"
                    f"📝 *Subject:* {message.get('subject', 'No subject')}\n"
                    f"💬 {message.get('body', message.get('text', ''))[:300]}\n\n"
                    f"✅ Email received successfully!",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_tempmail_keyboard(email)
                )
            else:
                await query.edit_message_text("⏰ *No email received*\n\nTimeout reached. Try again or generate a new email.", parse_mode=ParseMode.MARKDOWN, reply_markup=get_tempmail_keyboard(email))
        else:
            await query.edit_message_text("❌ No active email.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🆕 New Email", callback_data="tempmail")]]))
    
    elif data.startswith("copy_email_"):
        email = data.replace("copy_email_", "")
        await query.answer(f"✅ Email copied: {email}", show_alert=True)
    
    elif data == "balance":
        balance = user_balances.get(user_id, 0)
        stats = user_stats.get(user_id, {})
        await query.edit_message_text(
            f"💰 *Your Balance*\n\n"
            f"💵 *Available:* `{balance:.2f} TK`\n\n"
            f"📊 *Your Statistics:*\n"
            f"• Total OTPs Received: {stats.get('total_otps', 0)}\n"
            f"• Total Orders: {stats.get('total_orders', 0)}\n"
            f"• Total Earned: {stats.get('total_earned', 0):.2f} TK\n"
            f"• Member Since: {stats.get('joined', 'N/A')[:10]}\n\n"
            f"💸 *Minimum Withdrawal:* {MIN_WITHDRAW} TK\n\n"
            f"👥 *Referral Earnings:* {referral_earnings.get(user_id, 0):.2f} TK",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
                [InlineKeyboardButton("📊 Transaction History", callback_data="transaction_history")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
            ])
        )
    
    elif data == "transaction_history":
        trans = user_transactions.get(user_id, [])[-20:]
        if trans:
            msg = "📜 *Transaction History*\n\n"
            for t in reversed(trans):
                msg += f"• {t.get('type', 'N/A').upper()}: {t.get('amount', 0):.2f} TK"
                if t.get('service'):
                    msg += f" ({t.get('service')})"
                msg += f"\n  {t.get('time', 'N/A')[:19]}\n\n"
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="balance")]]))
        else:
            await query.edit_message_text("No transactions yet.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="balance")]]))
    
    elif data == "withdraw":
        balance = user_balances.get(user_id, 0)
        if balance >= MIN_WITHDRAW:
            await query.edit_message_text(
                f"💸 *Withdrawal Request*\n\n"
                f"💰 *Your Balance:* {balance:.2f} TK\n"
                f"💵 *Withdrawable:* {balance:.2f} TK\n\n"
                f"📝 *Send your withdrawal details:*\n"
                f"`/withdraw METHOD ACCOUNT_NUMBER`\n\n"
                f"*Available Methods:*\n"
                f"• bKash (bkash number)\n"
                f"• Nagad (nagad number)\n"
                f"• Rocket (rocket number)\n\n"
                f"*Example:* `/withdraw bKash 01XXXXXXXXX`\n\n"
                f"⚠️ Minimum withdrawal: {MIN_WITHDRAW} TK",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="balance")]])
            )
        else:
            await query.edit_message_text(
                f"❌ *Insufficient Balance for Withdrawal*\n\n"
                f"💰 *Your Balance:* {balance:.2f} TK\n"
                f"💵 *Minimum Required:* {MIN_WITHDRAW} TK\n\n"
                f"📱 *Need more balance?*\n"
                f"• Get more numbers and receive OTPs!\n"
                f"• Each OTP earns you {OTP_EARN_AMOUNT} TK\n"
                f"• Invite friends and earn 5 TK each!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📱 Get Number", callback_data="get_number")],
                    [InlineKeyboardButton("👥 Referral Program", callback_data="referral")],
                    [InlineKeyboardButton("🔙 Back", callback_data="balance")]
                ])
            )
    
    elif data == "referral":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        await query.edit_message_text(
            f"👥 *Referral Program*\n\n"
            f"💰 *Earn 5 TK for each friend you invite!*\n\n"
            f"🔗 *Your Referral Link:*\n`{ref_link}`\n\n"
            f"📊 *Your Stats:*\n"
            f"• Referrals: {len(user_referrals.get(user_id, []))}\n"
            f"• Earnings: {referral_earnings.get(user_id, 0):.2f} TK\n\n"
            f"💡 *How it works:*\n"
            f"1. Share your referral link\n"
            f"2. Friend joins using your link\n"
            f"3. You get 5 TK instantly!\n\n"
            f"🚀 *Start inviting now!*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_referral_keyboard(user_id)
        )
    
    elif data == "copy_ref_link":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        await query.answer(f"✅ Referral link copied!", show_alert=True)
    
    elif data == "my_referrals":
        referrals = user_referrals.get(user_id, [])
        if referrals:
            msg = "👥 *Your Referrals*\n\n"
            for ref in referrals[:20]:
                user_info = await context.bot.get_chat(ref)
                msg += f"• {user_info.first_name} (ID: `{ref}`)\n"
            msg += f"\nTotal: {len(referrals)} referrals"
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="referral")]]))
        else:
            await query.edit_message_text("No referrals yet. Share your link to invite friends!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="referral")]]))
    
    elif data == "ref_earnings":
        await query.edit_message_text(
            f"💰 *Referral Earnings*\n\n"
            f"💵 *Total Earned from Referrals:* {referral_earnings.get(user_id, 0):.2f} TK\n\n"
            f"👥 *Total Referrals:* {len(user_referrals.get(user_id, []))}\n\n"
            f"📈 *Keep inviting to earn more!*\n"
            f"• 5 TK per referral\n"
            f"• No limit on referrals",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="referral")]])
        )
    
    elif data == "mystats":
        stats = user_stats.get(user_id, {})
        balance = user_balances.get(user_id, 0)
        await query.edit_message_text(
            f"📊 *Your Statistics*\n\n"
            f"💰 *Balance:* {balance:.2f} TK\n"
            f"📦 *Total Orders:* {stats.get('total_orders', 0)}\n"
            f"🔑 *Total OTPs Received:* {stats.get('total_otps', 0)}\n"
            f"💵 *Total Earned:* {stats.get('total_earned', 0):.2f} TK\n"
            f"👥 *Referrals:* {len(user_referrals.get(user_id, []))}\n"
            f"💸 *Referral Earnings:* {referral_earnings.get(user_id, 0):.2f} TK\n"
            f"📅 *Member Since:* {stats.get('joined', 'N/A')[:10]}\n\n"
            f"📈 *Average per OTP:* {OTP_EARN_AMOUNT} TK",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]])
        )
    
    elif data == "settings":
        await query.edit_message_text(
            "⚙️ *Settings*\n\nChoose your preferences:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_settings_keyboard(user_id)
        )
    
    elif data.startswith("set_lang_"):
        lang = data.replace("set_lang_", "")
        user_languages[user_id] = lang
        user_settings[user_id]['lang'] = lang
        save_data()
        await query.edit_message_text(f"✅ Language set to {'Bengali' if lang == 'bn' else 'English'}", reply_markup=get_settings_keyboard(user_id))
    
    elif data == "toggle_notify":
        current = user_settings.get(user_id, {}).get('notify', True)
        user_settings[user_id]['notify'] = not current
        save_data()
        await query.edit_message_text(f"✅ Notifications {'enabled' if not current else 'disabled'}", reply_markup=get_settings_keyboard(user_id))
    
    elif data == "admin_panel" and is_admin:
        await query.edit_message_text("⚙️ *Admin Control Panel*\n\nManage bot settings, numbers, and users:", parse_mode=ParseMode.MARKDOWN, reply_markup=get_admin_keyboard())
    
    elif data == "admin_add_number" and is_admin:
        await query.edit_message_text(
            "➕ *Add Number*\n\n"
            "Send number in format:\n"
            "`/addnum COUNTRY +1234567890`\n\n"
            "Example: `/addnum Germany +491551329004`\n\n"
            "For bulk upload, send a .txt file with format:\n"
            "`Country|+1234567890`\n\n"
            "Or use /bulk command",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "admin_bulk_upload" and is_admin:
        await query.edit_message_text(
            "📤 *Bulk Upload Numbers*\n\n"
            "Send a .txt or .csv file with format:\n\n"
            "TXT format (one per line):\n"
            "`Country|+1234567890`\n\n"
            "CSV format:\n"
            "`Country,Number`\n\n"
            "Example file content:\n"
            "Germany|+491551329004\n"
            "Peru|+51927234335\n"
            "Bangladesh|+8801712345678",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "admin_remove_number" and is_admin:
        await query.edit_message_text("🗑 *Remove Number*\n\nSend: `/remnum COUNTRY +1234567890`\n\nExample: `/remnum Germany +491551329004`", parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_list_numbers" and is_admin:
        if available_numbers:
            msg = "📋 *Available Numbers*\n\n"
            for country, nums in available_numbers.items():
                msg += f"*{country}:* {len(nums)} numbers\n"
                for num in nums[:5]:
                    msg += f"  • `{num}`\n"
                msg += "\n"
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
        else:
            await query.edit_message_text("No numbers available.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
    
    elif data == "admin_add_country" and is_admin:
        await query.edit_message_text("➕ *Add Country*\n\nSend: `/addcountry COUNTRY_NAME`\n\nExample: `/addcountry Canada`\n\nDefault price: 0.40 TK", parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_set_price" and is_admin:
        await query.edit_message_text("💰 *Set Country Price*\n\nSend: `/setprice COUNTRY PRICE`\n\nExample: `/setprice Germany 0.50`", parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_add_balance" and is_admin:
        await query.edit_message_text("💰 *Add Balance*\n\nSend: `/addbal USER_ID AMOUNT`\n\nExample: `/addbal 7064572216 100`\n\nUser ID can be found in /users list", parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_process_withdraw" and is_admin:
        if pending_withdrawals:
            msg = "💸 *Pending Withdrawals*\n\n"
            for uid, wd in pending_withdrawals.items():
                msg += f"👤 User: `{uid}`\n"
                msg += f"💰 Amount: {wd['amount']:.2f} TK\n"
                msg += f"💳 Method: {wd['method']}\n"
                msg += f"📱 Account: {wd['account']}\n"
                msg += f"⏰ Time: {wd['time'][:19]}\n"
                msg += "➖➖➖➖➖➖➖➖\n\n"
            msg += "Send `/approvewd USER_ID` to approve\n"
            msg += "Send `/rejectwd USER_ID` to reject"
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
        else:
            await query.edit_message_text("✅ No pending withdrawals", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
    
    elif data == "admin_stats" and is_admin:
        total_users = len(user_balances)
        total_balance = sum(user_balances.values())
        total_earned = sum(s.get('total_earned', 0) for s in user_stats.values())
        total_otps = sum(s.get('total_otps', 0) for s in user_stats.values())
        total_numbers = sum(len(nums) for nums in available_numbers.values())
        pending_wd = len(pending_withdrawals)
        total_ref = sum(len(refs) for refs in user_referrals.values())
        total_ref_earn = sum(referral_earnings.values())
        
        stats_msg = f"""
📊 *Bot Statistics*

👥 *Total Users:* {total_users}
💰 *Total Balance:* {total_balance:.2f} TK
💵 *Total Earned:* {total_earned:.2f} TK
🔑 *Total OTPs Received:* {total_otps}
📱 *Available Numbers:* {total_numbers}
🌍 *Countries:* {len(available_numbers)}

💸 *Pending Withdrawals:* {pending_wd}
👥 *Total Referrals:* {total_ref}
💰 *Referral Payouts:* {total_ref_earn:.2f} TK

🔐 *2FA Users:* {len(totp_secrets)}
📧 *Temp Mail Users:* {len(temp_mail_data)}
🔄 *Active OTP Sessions:* {len(active_orders)}

⏰ *Last Login:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        await query.edit_message_text(stats_msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
    
    elif data == "admin_broadcast" and is_admin:
        await query.edit_message_text(
            "📨 *Broadcast Message*\n\n"
            "Send: `/broadcast Your message here`\n\n"
            "Message will be sent to ALL users.\n"
            "HTML formatting supported.\n\n"
            "Example: `/broadcast <b>Maintenance</b> at 2AM`\n\n"
            "To send with image: `/broadcast_image`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "admin_users" and is_admin:
        users_list = "👥 *Users List*\n\n"
        sorted_users = sorted(user_balances.items(), key=lambda x: x[1], reverse=True)
        for uid, bal in sorted_users[:30]:
            stats = user_stats.get(uid, {})
            users_list += f"• `{uid}` - {bal:.2f} TK (OTPs: {stats.get('total_otps', 0)})\n"
        users_list += f"\nTotal: {len(user_balances)} users\n\nSend `/userinfo USER_ID` for details"
        await query.edit_message_text(users_list, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
    
    elif data == "admin_transactions" and is_admin:
        await query.edit_message_text(
            "💳 *Transaction Log*\n\n"
            "Commands:\n"
            "• `/transactions USER_ID` - View user transactions\n"
            "• `/alltransactions` - View all recent transactions\n"
            "• `/exporttransactions` - Export all transactions",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]])
        )
    
    elif data == "admin_ban" and is_admin:
        await query.edit_message_text("🚫 *Ban User*\n\nSend: `/ban USER_ID REASON`\n\nExample: `/ban 123456789 Spam`", parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_unban" and is_admin:
        await query.edit_message_text("✅ *Unban User*\n\nSend: `/unban USER_ID`\n\nExample: `/unban 123456789`", parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_export" and is_admin:
        await query.edit_message_text("📥 *Export Data*\n\nSend: `/export users` - Export users list\n`/export numbers` - Export numbers\n`/export transactions` - Export transactions", parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_reset" and is_admin:
        await query.edit_message_text("🔄 *Reset System*\n\n⚠️ DANGER! This will delete all data!\n\nSend: `/reset confirm` to reset everything", parse_mode=ParseMode.MARKDOWN)

async def check_otp_background(context, user_id, number, chat_id, msg_id):
    for attempt in range(60):
        await asyncio.sleep(3)
        if user_id not in active_orders:
            return
        result = web_panel.get_otp(number)
        if result and result.get('otp'):
            otp = result['otp']
            service = result.get('service', 'Unknown')
            
            user_balances[user_id] = user_balances.get(user_id, 0) + OTP_EARN_AMOUNT
            if user_id not in user_stats:
                user_stats[user_id] = {'total_orders': 0, 'total_earned': 0, 'total_otps': 0}
            user_stats[user_id]['total_orders'] = user_stats[user_id].get('total_orders', 0) + 1
            user_stats[user_id]['total_earned'] = user_stats[user_id].get('total_earned', 0) + OTP_EARN_AMOUNT
            user_stats[user_id]['total_otps'] = user_stats[user_id].get('total_otps', 0) + 1
            
            if user_id not in user_transactions:
                user_transactions[user_id] = []
            user_transactions[user_id].append({
                'type': 'earned', 'amount': OTP_EARN_AMOUNT, 'number': number,
                'otp': otp, 'service': service, 'time': datetime.now().isoformat()
            })
            save_data()
            
            active_orders[user_id]['otp'] = otp
            active_orders[user_id]['service'] = service
            
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
                         f"🇧🇩 *নাজার যাচাই সম্পন্ন*\n"
                         f"🌍 *দেশ ও দাম:* {active_orders[user_id].get('country', 'Unknown')} (0.00TK)\n\n"
                         f"🔑 *OTP কোড:* `{otp}` ✅\n\n"
                         f"🔧 *Service:* {service}\n\n"
                         f"💰 *Earned:* +{OTP_EARN_AMOUNT} TK\n"
                         f"💵 *Balance:* {user_balances[user_id]:.2f} TK\n\n"
                         f"✅ *NUMBER VERIFIED SUCCESSFULLY*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_otp_keyboard(number, active_orders[user_id].get('country', 'Unknown'), True)
                )
            except: pass
            
            await context.bot.send_message(OTP_GROUP, 
                f"🔐 *GetPaid OTP 2.0 | OTP RCV*\n\n"
                f"📱 *Number:* `{number[-10:]}`\n"
                f"🌍 *Country:* {active_orders[user_id].get('country', 'Unknown')}\n"
                f"🔧 *Service:* {service}\n"
                f"✅ *Status:* CLAIMED\n"
                f"🔑 *OTP Code:* `{otp}`\n\n"
                f"`#{otp} is your {service} verification code`\n\n"
                f"🔗 @{BOT_USERNAME} | {MAIN_CHANNEL}", 
                parse_mode=ParseMode.MARKDOWN)
            
            await context.bot.send_message(user_id,
                f"🔐 *OTP Received!*\n\n"
                f"📱 *Number:* `{number[-10:]}`\n"
                f"🔧 *Service:* {service}\n"
                f"🔑 *OTP:* `{otp}`\n\n"
                f"💰 *+{OTP_EARN_AMOUNT} TK added!*\n"
                f"💵 *New Balance:* {user_balances[user_id]:.2f} TK\n\n"
                f"📱 Get another number: /start",
                parse_mode=ParseMode.MARKDOWN)
            return

async def auto_check_mail(context, user_id):
    last_count = 0
    while user_id in temp_mail_data:
        await asyncio.sleep(5)
        email = temp_mail_data[user_id]['email']
        messages = temp_mail.check_inbox(email)
        if messages and len(messages) > last_count:
            last_count = len(messages)
            temp_mail_data[user_id]['messages'] = messages
            save_data()
            try:
                await context.bot.send_message(user_id,
                    f"📬 *New Email Received!*\n\n"
                    f"📧 *From:* {messages[0].get('from', 'Unknown')}\n"
                    f"📝 *Subject:* {messages[0].get('subject', 'No subject')}\n\n"
                    f"Use /tempmail to check inbox",
                    parse_mode=ParseMode.MARKDOWN)
            except: pass
        if time.time() - temp_mail_data[user_id]['created'] > 3600:
            del temp_mail_data[user_id]
            save_data()
            break

async def message_handler(update, context):
    user_id = update.effective_user.id
    text = update.message.text
    is_admin = user_id == ADMIN_ID
    
    if user_id in banned_users:
        await update.message.reply_text("❌ You are banned from using this bot.\nReason: " + banned_users[user_id])
        return
    
    if context.user_data.get('awaiting_2fa'):
        if text == '/cancel':
            context.user_data['awaiting_2fa'] = False
            await update.message.reply_text("❌ Cancelled", reply_markup=get_main_keyboard(is_admin))
            return
        
        secret = text.upper().replace(' ', '')
        if len(secret) >= 16 and re.match(r'^[A-Z2-7]+$', secret):
            totp_secrets[user_id] = secret
            save_data()
            context.user_data['awaiting_2fa'] = False
            code = TOTPGenerator.get_code(secret)
            remaining = TOTPGenerator.time_left()
            kb, _, _ = get_2fa_keyboard(secret)
            await update.message.reply_text(
                f"🔐 *2FA Authenticator Setup Complete*\n\n"
                f"🔑 *Your Secret Key:*\n`{secret}`\n\n"
                f"🔢 *Current Code:* `{code}`\n"
                f"⏱ *Valid for:* {remaining} seconds\n\n"
                f"💡 Save this secret key in your 2FA app!\n"
                f"• Works with Google Authenticator\n"
                f"• Code changes every 30 seconds",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
        else:
            await update.message.reply_text("❌ *Invalid secret key!*\n\nSecret key must:\n• Be at least 16 characters\n• Contain only A-Z and 2-7\n• No spaces or special characters\n\nTry again or type /cancel", parse_mode=ParseMode.MARKDOWN)
        return
    
    if text == '/cancel':
        context.user_data['awaiting_2fa'] = False
        context.user_data['awaiting_withdraw'] = False
        await update.message.reply_text("❌ Cancelled", reply_markup=get_main_keyboard(is_admin))
        return
    
    if text.startswith('/withdraw'):
        parts = text.split()
        if len(parts) >= 3:
            method = parts[1]
            account = parts[2]
            amount = user_balances.get(user_id, 0)
            if amount >= MIN_WITHDRAW:
                pending_withdrawals[user_id] = {
                    'amount': amount, 'method': method, 'account': account,
                    'time': datetime.now().isoformat()
                }
                user_balances[user_id] = 0
                save_data()
                await update.message.reply_text(
                    f"✅ *Withdrawal Request Submitted!*\n\n"
                    f"💰 Amount: {amount:.2f} TK\n"
                    f"💳 Method: {method}\n"
                    f"📱 Account: {account}\n\n"
                    f"⏳ Will be processed within 24 hours.\n"
                    f"📢 Contact admin if not processed.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_main_keyboard(is_admin)
                )
                await context.bot.send_message(ADMIN_ID,
                    f"💰 *New Withdrawal Request*\n\n"
                    f"👤 User: `{user_id}`\n"
                    f"💰 Amount: {amount:.2f} TK\n"
                    f"💳 Method: {method}\n"
                    f"📱 Account: {account}\n"
                    f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"❌ *Minimum withdrawal: {MIN_WITHDRAW} TK*\nYour balance: {amount:.2f} TK", parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin))
        else:
            await update.message.reply_text("❌ *Use:* `/withdraw METHOD ACCOUNT`\nExample: `/withdraw bKash 01XXXXXXXXX`", parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin))
        return
    
    if text == '/tempmail':
        email = temp_mail.generate_email()
        temp_mail_data[user_id] = {'email': email, 'created': time.time(), 'messages': []}
        save_data()
        if user_id in mail_check_tasks:
            mail_check_tasks[user_id].cancel()
        mail_check_tasks[user_id] = asyncio.create_task(auto_check_mail(context, user_id))
        await update.message.reply_text(f"📧 *Temp Email:* `{email}`\n\nUse /checkmail to check inbox", parse_mode=ParseMode.MARKDOWN)
        return
    
    if text == '/checkmail':
        if user_id in temp_mail_data:
            email = temp_mail_data[user_id]['email']
            messages = temp_mail.check_inbox(email)
            if messages:
                msg = "📬 *Inbox*\n\n"
                for m in messages[:5]:
                    msg += f"From: {m.get('from', 'Unknown')}\n{m.get('body', '')[:200]}\n\n"
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text("📭 No messages yet")
        else:
            await update.message.reply_text("No active email. Use /tempmail first")
        return
    
    if is_admin:
        if text.startswith('/addnum'):
            parts = text.split(maxsplit=2)
            if len(parts) == 3:
                country, number = parts[1], parts[2]
                if country not in available_numbers:
                    available_numbers[country] = []
                if number not in available_numbers[country]:
                    available_numbers[country].append(number)
                    save_data()
                    await update.message.reply_text(f"✅ Added `{number}` to {country}", parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text("❌ Number already exists")
            else:
                await update.message.reply_text("❌ Use: /addnum COUNTRY NUMBER")
        
        elif text.startswith('/remnum'):
            parts = text.split(maxsplit=2)
            if len(parts) == 3:
                country, number = parts[1], parts[2]
                if country in available_numbers and number in available_numbers[country]:
                    available_numbers[country].remove(number)
                    if not available_numbers[country]:
                        del available_numbers[country]
                    save_data()
                    await update.message.reply_text(f"✅ Removed `{number}` from {country}", parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text("❌ Number not found")
            else:
                await update.message.reply_text("❌ Use: /remnum COUNTRY NUMBER")
        
        elif text.startswith('/addbal'):
            parts = text.split()
            if len(parts) == 3:
                try:
                    target = int(parts[1])
                    amount = float(parts[2])
                    user_balances[target] = user_balances.get(target, 0) + amount
                    if target not in user_transactions:
                        user_transactions[target] = []
                    user_transactions[target].append({
                        'type': 'admin_add', 'amount': amount, 'time': datetime.now().isoformat()
                    })
                    save_data()
                    await update.message.reply_text(f"✅ Added {amount} TK to `{target}`", parse_mode=ParseMode.MARKDOWN)
                    try:
                        await context.bot.send_message(target, f"💰 *+{amount} TK added to your balance!*\nNew Balance: {user_balances[target]:.2f} TK", parse_mode=ParseMode.MARKDOWN)
                    except: pass
                except ValueError:
                    await update.message.reply_text("❌ Invalid user ID or amount")
            else:
                await update.message.reply_text("❌ Use: /addbal USER_ID AMOUNT")
        
        elif text.startswith('/addcountry'):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                country = parts[1]
                if country not in available_numbers:
                    available_numbers[country] = []
                    save_data()
                    await update.message.reply_text(f"✅ Added country: {country}")
                else:
                    await update.message.reply_text("❌ Country already exists")
            else:
                await update.message.reply_text("❌ Use: /addcountry COUNTRY_NAME")
        
        elif text.startswith('/setprice'):
            parts = text.split()
            if len(parts) == 3:
                country = parts[1]
                price = float(parts[2])
                country_prices[country] = price
                save_data()
                await update.message.reply_text(f"✅ Set price for {country}: {price} TK")
            else:
                await update.message.reply_text("❌ Use: /setprice COUNTRY PRICE")
        
        elif text.startswith('/broadcast'):
            msg = text.replace('/broadcast', '', 1).strip()
            if msg:
                sent = 0
                failed = 0
                for uid in user_balances.keys():
                    try:
                        await context.bot.send_message(uid, f"📢 *Announcement*\n\n{msg}", parse_mode=ParseMode.HTML)
                        sent += 1
                        await asyncio.sleep(0.05)
                    except:
                        failed += 1
                await update.message.reply_text(f"✅ Sent to {sent} users\n❌ Failed: {failed}")
            else:
                await update.message.reply_text("❌ Use: /broadcast MESSAGE")
        
        elif text.startswith('/approvewd'):
            parts = text.split()
            if len(parts) == 2:
                target = int(parts[1])
                if target in pending_withdrawals:
                    wd = pending_withdrawals[target]
                    del pending_withdrawals[target]
                    save_data()
                    await update.message.reply_text(f"✅ Withdrawal approved for `{target}`\nAmount: {wd['amount']:.2f} TK", parse_mode=ParseMode.MARKDOWN)
                    try:
                        await context.bot.send_message(target,
                            f"✅ *Withdrawal Approved!*\n\n"
                            f"💰 Amount: {wd['amount']:.2f} TK\n"
                            f"💳 Method: {wd['method']}\n"
                            f"📱 Account: {wd['account']}\n\n"
                            f"Funds have been sent to your account.",
                            parse_mode=ParseMode.MARKDOWN)
                    except: pass
                else:
                    await update.message.reply_text("❌ Withdrawal not found")
            else:
                await update.message.reply_text("❌ Use: /approvewd USER_ID")
        
        elif text.startswith('/rejectwd'):
            parts = text.split()
            if len(parts) == 2:
                target = int(parts[1])
                if target in pending_withdrawals:
                    wd = pending_withdrawals[target]
                    del pending_withdrawals[target]
                    user_balances[target] = user_balances.get(target, 0) + wd['amount']
                    save_data()
                    await update.message.reply_text(f"❌ Withdrawal rejected for `{target}`\nAmount refunded: {wd['amount']:.2f} TK", parse_mode=ParseMode.MARKDOWN)
                    try:
                        await context.bot.send_message(target,
                            f"❌ *Withdrawal Rejected*\n\n"
                            f"💰 Amount: {wd['amount']:.2f} TK\n"
                            f"Reason: Please contact support.\n\n"
                            f"Amount has been refunded to your balance.",
                            parse_mode=ParseMode.MARKDOWN)
                    except: pass
                else:
                    await update.message.reply_text("❌ Withdrawal not found")
            else:
                await update.message.reply_text("❌ Use: /rejectwd USER_ID")
        
        elif text.startswith('/ban'):
            parts = text.split(maxsplit=2)
            if len(parts) >= 2:
                target = int(parts[1])
                reason = parts[2] if len(parts) > 2 else "No reason"
                banned_users[target] = reason
                save_data()
                await update.message.reply_text(f"🚫 Banned user `{target}`\nReason: {reason}", parse_mode=ParseMode.MARKDOWN)
                try:
                    await context.bot.send_message(target, f"🚫 *You have been banned*\nReason: {reason}\nContact admin for appeal.", parse_mode=ParseMode.MARKDOWN)
                except: pass
            else:
                await update.message.reply_text("❌ Use: /ban USER_ID REASON")
        
        elif text.startswith('/unban'):
            parts = text.split()
            if len(parts) == 2:
                target = int(parts[1])
                if target in banned_users:
                    del banned_users[target]
                    save_data()
                    await update.message.reply_text(f"✅ Unbanned user `{target}`", parse_mode=ParseMode.MARKDOWN)
                    try:
                        await context.bot.send_message(target, f"✅ *You have been unbanned*\nYou can now use the bot again.", parse_mode=ParseMode.MARKDOWN)
                    except: pass
                else:
                    await update.message.reply_text("❌ User not banned")
            else:
                await update.message.reply_text("❌ Use: /unban USER_ID")
        
        elif text.startswith('/userinfo'):
            parts = text.split()
            if len(parts) == 2:
                target = int(parts[1])
                stats = user_stats.get(target, {})
                balance = user_balances.get(target, 0)
                await update.message.reply_text(
                    f"👤 *User Info*\n\n"
                    f"🆔 ID: `{target}`\n"
                    f"💰 Balance: {balance:.2f} TK\n"
                    f"📦 Orders: {stats.get('total_orders', 0)}\n"
                    f"🔑 OTPs: {stats.get('total_otps', 0)}\n"
                    f"💵 Earned: {stats.get('total_earned', 0):.2f} TK\n"
                    f"👥 Referrals: {len(user_referrals.get(target, []))}\n"
                    f"📅 Joined: {stats.get('joined', 'N/A')[:10]}\n"
                    f"🚫 Banned: {'Yes' if target in banned_users else 'No'}",
                    parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text("❌ Use: /userinfo USER_ID")
        
        elif text == '/users':
            msg = "👥 *Users*\n\n"
            for uid, bal in sorted(user_balances.items(), key=lambda x: x[1], reverse=True)[:50]:
                stats = user_stats.get(uid, {})
                msg += f"• `{uid}` - {bal:.2f} TK (OTPs: {stats.get('total_otps', 0)})\n"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        
        elif text.startswith('/transactions'):
            parts = text.split()
            if len(parts) == 2:
                target = int(parts[1])
                trans = user_transactions.get(target, [])[-20:]
                if trans:
                    msg = f"📈 *Transactions for `{target}`*\n\n"
                    for t in reversed(trans):
                        msg += f"• {t.get('type', 'N/A').upper()}: {t.get('amount', 0):.2f} TK"
                        if t.get('service'):
                            msg += f" ({t.get('service')})"
                        msg += f"\n  {t.get('time', 'N/A')[:19]}\n\n"
                    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text("No transactions found")
            else:
                await update.message.reply_text("❌ Use: /transactions USER_ID")
        
        elif text == '/alltransactions':
            all_trans = []
            for uid, trans in user_transactions.items():
                for t in trans[-5:]:
                    all_trans.append((uid, t))
            all_trans.sort(key=lambda x: x[1].get('time', ''), reverse=True)
            msg = "📈 *Recent Transactions*\n\n"
            for uid, t in all_trans[:30]:
                msg += f"• `{uid}`: {t.get('type', 'N/A')} {t.get('amount', 0):.2f} TK\n  {t.get('time', 'N/A')[:19]}\n\n"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        
        elif text.startswith('/export'):
            parts = text.split()
            if len(parts) == 2:
                if parts[1] == 'users':
                    output = io.StringIO()
                    writer = csv.writer(output)
                    writer.writerow(['User ID', 'Balance', 'Total Orders', 'Total OTPs', 'Total Earned', 'Joined'])
                    for uid in user_balances:
                        stats = user_stats.get(uid, {})
                        writer.writerow([uid, user_balances[uid], stats.get('total_orders', 0), stats.get('total_otps', 0), stats.get('total_earned', 0), stats.get('joined', '')])
                    output.seek(0)
                    await update.message.reply_document(InputFile(io.BytesIO(output.getvalue().encode()), filename='users.csv'))
                elif parts[1] == 'numbers':
                    output = io.StringIO()
                    writer = csv.writer(output)
                    writer.writerow(['Country', 'Number'])
                    for country, nums in available_numbers.items():
                        for num in nums:
                            writer.writerow([country, num])
                    output.seek(0)
                    await update.message.reply_document(InputFile(io.BytesIO(output.getvalue().encode()), filename='numbers.csv'))
                elif parts[1] == 'transactions':
                    output = io.StringIO()
                    writer = csv.writer(output)
                    writer.writerow(['User ID', 'Type', 'Amount', 'Service', 'Time'])
                    for uid, trans in user_transactions.items():
                        for t in trans:
                            writer.writerow([uid, t.get('type', ''), t.get('amount', 0), t.get('service', ''), t.get('time', '')])
                    output.seek(0)
                    await update.message.reply_document(InputFile(io.BytesIO(output.getvalue().encode()), filename='transactions.csv'))
            else:
                await update.message.reply_text("❌ Use: /export [users|numbers|transactions]")
        
        elif text == '/reset confirm':
            global user_balances, totp_secrets, available_numbers, pending_withdrawals, user_transactions, user_stats, temp_mail_data, user_referrals, referral_earnings
            user_balances.clear()
            totp_secrets.clear()
            available_numbers.clear()
            pending_withdrawals.clear()
            user_transactions.clear()
            user_stats.clear()
            temp_mail_data.clear()
            user_referrals.clear()
            referral_earnings.clear()
            save_data()
            await update.message.reply_text("✅ System reset complete! All data has been cleared.")
        
        elif text == '/stats':
            total_users = len(user_balances)
            total_balance = sum(user_balances.values())
            total_earned = sum(s.get('total_earned', 0) for s in user_stats.values())
            total_otps = sum(s.get('total_otps', 0) for s in user_stats.values())
            await update.message.reply_text(
                f"📊 *Bot Stats*\n\n👥 Users: {total_users}\n💰 Balance: {total_balance:.2f} TK\n💵 Earned: {total_earned:.2f} TK\n🔑 OTPs: {total_otps}",
                parse_mode=ParseMode.MARKDOWN)
        
        elif text == '/login':
            if web_panel.login():
                await update.message.reply_text("✅ Web panel login successful!")
            else:
                await update.message.reply_text("❌ Web panel login failed!")
    
    if update.message.document and is_admin:
        file = await update.message.document.get_file()
        file_path = f"/tmp/{update.message.document.file_name}"
        await file.download_to_drive(file_path)
        
        added = 0
        with open(file_path, 'r') as f:
            content = f.read()
            for line in content.split('\n'):
                line = line.strip()
                if '|' in line:
                    country, number = line.split('|')
                    if country not in available_numbers:
                        available_numbers[country] = []
                    if number not in available_numbers[country]:
                        available_numbers[country].append(number)
                        added += 1
                elif ',' in line and not line.startswith('Country'):
                    parts = line.split(',')
                    if len(parts) == 2:
                        country, number = parts[0].strip(), parts[1].strip()
                        if country not in available_numbers:
                            available_numbers[country] = []
                        if number not in available_numbers[country]:
                            available_numbers[country].append(number)
                            added += 1
        save_data()
        await update.message.reply_text(f"✅ Added {added} numbers from file!")

async def twofa_command(update, context):
    context.user_data['awaiting_2fa'] = True
    await update.message.reply_text(
        "🔐 *2FA Authenticator*\n\n"
        "📝 *Send your Authenticator Secret Key*\n"
        "Example: `JBSWY3DPEHPK3PXP`\n\n"
        "You can get this key from:\n"
        "• Google Authenticator\n"
        "• Microsoft Authenticator\n\n"
        "Type /cancel to cancel",
        parse_mode=ParseMode.MARKDOWN
    )
    return SECRET_KEY_STATE

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        application.update_queue.put_nowait(update)
        return 'ok', 200
    except Exception as e:
        return str(e), 500

@flask_app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'alive',
        'users': len(user_balances),
        'active_orders': len(active_orders),
        'numbers': sum(len(n) for n in available_numbers.values()),
        'time': datetime.now().isoformat()
    })

if __name__ == '__main__':
    application = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("twofa", twofa_command), CallbackQueryHandler(callback_handler, pattern="^twofa$")],
        states={SECRET_KEY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)]},
        fallbacks=[CommandHandler("cancel", message_handler)]
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("withdraw", message_handler))
    application.add_handler(CommandHandler("tempmail", message_handler))
    application.add_handler(CommandHandler("checkmail", message_handler))
    application.add_handler(CommandHandler("twofa", twofa_command))
    application.add_handler(CommandHandler("addnum", message_handler))
    application.add_handler(CommandHandler("remnum", message_handler))
    application.add_handler(CommandHandler("addbal", message_handler))
    application.add_handler(CommandHandler("addcountry", message_handler))
    application.add_handler(CommandHandler("setprice", message_handler))
    application.add_handler(CommandHandler("broadcast", message_handler))
    application.add_handler(CommandHandler("approvewd", message_handler))
    application.add_handler(CommandHandler("rejectwd", message_handler))
    application.add_handler(CommandHandler("ban", message_handler))
    application.add_handler(CommandHandler("unban", message_handler))
    application.add_handler(CommandHandler("userinfo", message_handler))
    application.add_handler(CommandHandler("users", message_handler))
    application.add_handler(CommandHandler("transactions", message_handler))
    application.add_handler(CommandHandler("alltransactions", message_handler))
    application.add_handler(CommandHandler("export", message_handler))
    application.add_handler(CommandHandler("reset", message_handler))
    application.add_handler(CommandHandler("stats", message_handler))
    application.add_handler(CommandHandler("login", message_handler))
    
    web_panel.login()
    
    if os.environ.get('PORT'):
        port = int(os.environ.get('PORT', 8080))
        url = os.environ.get('WEBHOOK_URL', '')
        if url:
            application.bot.set_webhook(url)
        flask_app.run(host='0.0.0.0', port=port)
    else:
        print("🤖 GetPaid OTP 2.0 Bot is running...")
        application.run_polling()
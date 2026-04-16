# otp_service_bot.py - Complete Fixed Version (No Mask for Users, Masked in Group)
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
import csv
import io
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.constants import ParseMode

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8343363851:AAHmFXkTjrubOpW3VdsZAhebvzfNyjNpJ10"
ADMIN_ID = 7064572216
BOT_USERNAME = "OtpServices2_Bot"
MAIN_CHANNEL = "@OtpService2C"
OTP_GROUP = "@OtpService2G"
SUPPORT_ID = "@xDnaZim"
WEB_LOGIN_URL = "http://139.99.9.4/ints/login"
WEB_API_URL = "http://139.99.9.4/ints/agent/SMSCDRStats"
WEB_USER = "Nazim1"
WEB_PASS = "Nazim1"

MIN_WITHDRAW = 500
DATA_FILE = "bot_data.json"
NUMBERS_FILE = "numbers.json"

SECRET_KEY_STATE = 1
AWAITING_NUMBERS_STATE = 2
AWAITING_PRICE_STATE = 3

flask_app = Flask(__name__)

# ==================== GLOBAL VARIABLES ====================
user_balances = {}
active_orders = {}
totp_secrets = {}
available_numbers = {}
country_prices = {}
pending_withdrawals = {}
user_transactions = {}
user_stats = {}
banned_users = {}
user_languages = {}
user_selected_country = {}
user_current_numbers = {}
user_waiting_for_otp = {}
last_web_login = 0
web_session = None
number_usage_stats = {}
last_2fa_message_id = {}  # Track 2FA message to avoid duplicates

# ==================== DATA PERSISTENCE ====================
def load_data():
    global user_balances, totp_secrets, available_numbers, pending_withdrawals
    global user_transactions, user_stats, banned_users, user_languages, country_prices, number_usage_stats
    
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            user_balances = data.get('balances', {})
            totp_secrets = data.get('totp', {})
            pending_withdrawals = data.get('withdrawals', {})
            user_transactions = data.get('transactions', {})
            user_stats = data.get('stats', {})
            banned_users = data.get('banned', {})
            user_languages = data.get('languages', {})
            country_prices = data.get('country_prices', {})
            number_usage_stats = data.get('number_usage', {})
    except FileNotFoundError:
        pass
    
    try:
        with open(NUMBERS_FILE, 'r') as f:
            available_numbers = json.load(f)
    except FileNotFoundError:
        available_numbers = {}

def save_data():
    with open(DATA_FILE, 'w') as f:
        json.dump({
            'balances': user_balances,
            'totp': totp_secrets,
            'withdrawals': pending_withdrawals,
            'transactions': user_transactions,
            'stats': user_stats,
            'banned': banned_users,
            'languages': user_languages,
            'country_prices': country_prices,
            'number_usage': number_usage_stats
        }, f, indent=2)
    
    with open(NUMBERS_FILE, 'w') as f:
        json.dump(available_numbers, f, indent=2)

load_data()

# ==================== WEB PANEL CLIENT ====================
class WebPanelClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        self.logged_in = False
    
    def solve_captcha(self, html):
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
            return self.logged_in
        except:
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
                    services = {'whatsapp': 'WhatsApp', 'telegram': 'Telegram', 'imo': 'IMO', 'instagram': 'Instagram', 'tiktok': 'TikTok', 'google': 'Google', 'twitter': 'Twitter', 'facebook': 'Facebook', 'fb': 'Facebook'}
                    for key, val in services.items():
                        if key in text.lower():
                            service = val
                            break
                    return {'otp': otp.group(), 'service': service}
            return None
        except:
            return None

web_panel = WebPanelClient()

# ==================== TOTP GENERATOR ====================
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

# ==================== NUMBER MASKING (Only for Group) ====================
def mask_number_for_group(number):
    """Mask number for group - show first 3-4 digits and last 3 digits only"""
    if len(number) <= 7:
        return number
    first_part = number[:4] if len(number) > 7 else number[:3]
    last_part = number[-3:]
    masked = first_part + "***" + last_part
    return masked

def get_full_number_from_masked(masked_number, user_numbers):
    """Find full number from masked version by matching pattern"""
    # Extract pattern from masked: e.g., "017***456"
    pattern_parts = masked_number.split('***')
    if len(pattern_parts) != 2:
        return None
    
    first_part = pattern_parts[0]
    last_part = pattern_parts[1]
    
    for num in user_numbers:
        if num.startswith(first_part) and num.endswith(last_part):
            return num
    return None

# ==================== REPLY KEYBOARDS ====================
def get_main_keyboard(is_admin=False):
    keyboard = [
        [KeyboardButton("📱 Get Number")],
        [KeyboardButton("🔐 2FA"), KeyboardButton("💰 Balance")],
        [KeyboardButton("💸 Withdraw"), KeyboardButton("📊 My Stats")],
        [KeyboardButton("📢 Support")]
    ]
    if is_admin:
        keyboard.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard():
    keyboard = [
        [KeyboardButton("➕ Add Number"), KeyboardButton("📋 List Numbers")],
        [KeyboardButton("🌍 Edit Country"), KeyboardButton("💰 Set Price")],
        [KeyboardButton("💸 Process Withdrawals"), KeyboardButton("📊 Statistics")],
        [KeyboardButton("📨 Broadcast"), KeyboardButton("👥 Users List")],
        [KeyboardButton("🚫 Ban/Unban User"), KeyboardButton("📥 Export Data")],
        [KeyboardButton("🔙 Back to Main")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_country_selection_keyboard(countries):
    keyboard = []
    for country in countries:
        keyboard.append([InlineKeyboardButton(f"🌍 {country}", callback_data=f"select_country_{country}")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")])
    return InlineKeyboardMarkup(keyboard)

def get_numbers_post_keyboard(numbers, country):
    """Create post with unmasked numbers as text, buttons below"""
    keyboard = [
        [InlineKeyboardButton("📢 OTP Group", url=f"https://t.me/{OTP_GROUP[1:]}")],
        [InlineKeyboardButton("🔄 Change Number", callback_data=f"change_number_{country}")],
        [InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_otp_check_keyboard(number, country):
    keyboard = [
        [InlineKeyboardButton("🔄 Check OTP", callback_data=f"check_otp_{number}")],
        [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{MAIN_CHANNEL[1:]}")],
        [InlineKeyboardButton("🔄 Change Number", callback_data=f"change_number_{country}")],
        [InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_2fa_display_keyboard(secret, code, remaining):
    keyboard = [
        [InlineKeyboardButton(f"⏱ {remaining}s remaining", callback_data="noop")],
        [InlineKeyboardButton("🔄 Refresh Code", callback_data="2fa_refresh")],
        [InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_2fa_initial_keyboard():
    keyboard = [
        [InlineKeyboardButton("❌ Cancel", callback_data="2fa_cancel")],
        [InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_country_keyboard(countries, action):
    keyboard = []
    for country in countries:
        keyboard.append([InlineKeyboardButton(f"🌍 {country}", callback_data=f"{action}_{country}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="back_to_admin")])
    return InlineKeyboardMarkup(keyboard)

def get_price_set_keyboard(countries):
    keyboard = []
    for country in countries:
        current_price = country_prices.get(country, 0.30)
        keyboard.append([InlineKeyboardButton(f"🌍 {country} (বর্তমান: {current_price} TK)", callback_data=f"setprice_{country}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="back_to_admin")])
    return InlineKeyboardMarkup(keyboard)

# ==================== BOT HANDLERS ====================
async def start(update, context):
    user = update.effective_user
    user_id = user.id
    is_admin = user_id == ADMIN_ID
    
    if user_id in banned_users:
        await update.message.reply_text("❌ আপনি এই বট ব্যবহার করতে পারবেন না।\nYou are banned from using this bot.")
        return
    
    if user_id not in user_balances:
        user_balances[user_id] = 0
        user_stats[user_id] = {'joined': datetime.now().isoformat(), 'total_otps': 0, 'total_earned': 0}
        user_languages[user_id] = 'bn'
        save_data()
    
    welcome_text = f"""🎉 *OTP Service Bot* এ স্বাগতম 🎉

👤 *ইউজার:* {user.first_name}
🆔 *আইডি:* `{user_id}`
💰 *ব্যালেন্স:* {user_balances.get(user_id, 0):.2f} TK
📊 *মোট আয়:* {user_stats.get(user_id, {}).get('total_earned', 0):.2f} TK

⚡ *কিভাবে কাজ করে:*
• 📱 Get Number - ফ্রি নম্বর নিন
• OTP রিসিভ করুন
• প্রতি OTP তে পান দেশ অনুযায়ী TK
• মিনিমাম উইথড্র: {MIN_WITHDRAW} TK

👇 *নিচের বাটন থেকে সিলেক্ট করুন:*"""

    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin))

async def handle_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text
    is_admin = user_id == ADMIN_ID
    
    if user_id in banned_users:
        await update.message.reply_text("❌ আপনি বanned!")
        return
    
    # Handle 2FA secret key input
    if context.user_data.get('awaiting_2fa'):
        if text == '/cancel' or text == '❌ Cancel':
            context.user_data['awaiting_2fa'] = False
            await update.message.reply_text("❌ Cancelled", reply_markup=get_main_keyboard(is_admin))
            return
        
        secret = text.upper().replace(' ', '')
        if len(secret) >= 16 and re.match(r'^[A-Z2-7]+$', secret):
            totp_secrets[user_id] = secret
            save_data()
            context.user_data['awaiting_2fa'] = False
            
            # Cancel existing task if any
            if '2fa_task' in context.user_data:
                context.user_data['2fa_task'].cancel()
            
            # Start new auto-refresh task
            task = asyncio.create_task(auto_refresh_2fa(context, update.message.chat_id, user_id))
            context.user_data['2fa_task'] = task
            
            code = TOTPGenerator.get_code(secret)
            remaining = TOTPGenerator.time_left()
            kb = get_2fa_display_keyboard(secret, code, remaining)
            
            await update.message.reply_text(
                f"🔐 *2FA সেটআপ সম্পূর্ণ!*\n\n"
                f"🔑 *সিক্রেট কী:* `{secret}`\n"
                f"🔢 *বর্তমান কোড:* `{code}`\n\n"
                f"✅ কোডটি কপি করতে কোডের উপর ক্লিক করুন\n"
                f"⏱ {remaining} সেকেন্ড পর কোড পরিবর্তন হবে",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
        else:
            await update.message.reply_text("❌ ভুল সিক্রেট কী!\n\nসিক্রেট কী হতে হবে:\n• কমপক্ষে 16 অক্ষর\n• শুধুমাত্র A-Z এবং 2-7\n\nআবার চেষ্টা করুন অথবা Cancel বাটনে ক্লিক করুন।", reply_markup=get_2fa_initial_keyboard())
        return
    
    # Handle number addition from admin
    if context.user_data.get('awaiting_numbers') and is_admin:
        country = context.user_data.get('pending_country')
        if country and text and text != '/cancel':
            numbers = text.strip().split('\n')
            added = 0
            duplicate = 0
            for num in numbers:
                num = num.strip()
                if num:
                    if not num.startswith('+'):
                        num = '+' + num
                    if country not in available_numbers:
                        available_numbers[country] = []
                    if num not in available_numbers[country]:
                        available_numbers[country].append(num)
                        added += 1
                    else:
                        duplicate += 1
            save_data()
            context.user_data['awaiting_numbers'] = False
            context.user_data['pending_country'] = None
            await update.message.reply_text(f"✅ {added} টি নম্বর {country} দেশে যোগ করা হয়েছে!\n❌ ডুপ্লিকেট: {duplicate}\n\nমোট নম্বর: {len(available_numbers.get(country, []))} টি")
            return
        elif text == '/cancel':
            context.user_data['awaiting_numbers'] = False
            context.user_data['pending_country'] = None
            await update.message.reply_text("❌ নম্বর যোগ করা বাতিল করা হয়েছে।")
            return
    
    # Handle price input from admin
    if context.user_data.get('awaiting_price') and is_admin:
        country = context.user_data.get('price_country')
        if country and text:
            try:
                price = float(text)
                if price >= 0:
                    country_prices[country] = price
                    save_data()
                    context.user_data['awaiting_price'] = False
                    context.user_data['price_country'] = None
                    await update.message.reply_text(f"✅ {country} দেশের OTP দাম সেট করা হয়েছে: {price} TK")
                else:
                    await update.message.reply_text("❌ দাম 0 বা তার বেশি হতে হবে।")
            except ValueError:
                await update.message.reply_text("❌ ভুল দাম! একটি সংখ্যা দিন। উদাহরণ: 0.50")
        return
    
    # ==================== MAIN MENU ====================
    if text == "📱 Get Number":
        if not available_numbers:
            await update.message.reply_text("❌ কোনো দেশ উপলব্ধ নেই। অ্যাডমিন প্রথমে দেশ যোগ করুন।")
            return
        
        countries = list(available_numbers.keys())
        await update.message.reply_text(
            "🌍 *দেশ সিলেক্ট করুন*\n\nনিচ থেকে আপনার পছন্দের দেশ নির্বাচন করুন:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_country_selection_keyboard(countries)
        )
        return
    
    elif text == "🔐 2FA":
        await update.message.reply_text(
            "🔐 *2FA অথেনটিকেটর*\n\n"
            "📝 *আপনার অথেনটিকেটর সিক্রেট কী পাঠান*\n\n"
            "উদাহরণ: `JBSWY3DPEHPK3PXP`\n\n"
            "Google Authenticator বা অন্য যেকোনো 2FA অ্যাপ থেকে এই কী নিন।\n\n"
            "👇 *নিচের বাটন থেকে বাতিল করুন:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_2fa_initial_keyboard()
        )
        context.user_data['awaiting_2fa'] = True
        return SECRET_KEY_STATE
    
    elif text == "💰 Balance":
        balance = user_balances.get(user_id, 0)
        stats = user_stats.get(user_id, {})
        await update.message.reply_text(
            f"💰 *আপনার ব্যালেন্স*\n\n"
            f"💵 *উপলব্ধ:* `{balance:.2f} TK`\n\n"
            f"📊 *পরিসংখ্যান:*\n"
            f"• মোট OTP: {stats.get('total_otps', 0)}\n"
            f"• মোট আয়: {stats.get('total_earned', 0):.2f} TK\n"
            f"• জয়েন তারিখ: {stats.get('joined', 'N/A')[:10]}\n\n"
            f"💸 *মিনিমাম উইথড্র:* {MIN_WITHDRAW} TK",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "💸 Withdraw":
        balance = user_balances.get(user_id, 0)
        if balance >= MIN_WITHDRAW:
            await update.message.reply_text(
                f"💸 *উইথড্র রিকোয়েস্ট*\n\n"
                f"💰 *আপনার ব্যালেন্স:* {balance:.2f} TK\n\n"
                f"📝 নিচের ফরম্যাটে পাঠান:\n"
                f"`/withdraw মেথড একাউন্ট_নাম্বার`\n\n"
                f"উদাহরণ: `/withdraw bKash 01XXXXXXXXX`\n\n"
                f"উপলব্ধ মেথড: bKash, Nagad, Rocket",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"❌ *পর্যাপ্ত ব্যালেন্স নেই!*\n\n"
                f"💰 আপনার ব্যালেন্স: {balance:.2f} TK\n"
                f"💵 প্রয়োজন: {MIN_WITHDRAW} TK\n\n"
                f"📱 বেশি OTP রিসিভ করে ব্যালেন্স বাড়ান!",
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif text == "📊 My Stats":
        stats = user_stats.get(user_id, {})
        balance = user_balances.get(user_id, 0)
        await update.message.reply_text(
            f"📊 *আপনার পরিসংখ্যান*\n\n"
            f"💰 *ব্যালেন্স:* {balance:.2f} TK\n"
            f"🔑 *মোট OTP:* {stats.get('total_otps', 0)}\n"
            f"💵 *মোট আয়:* {stats.get('total_earned', 0):.2f} TK\n"
            f"📅 *জয়েন করেছেন:* {stats.get('joined', 'N/A')[:10]}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "📢 Support":
        await update.message.reply_text(
            f"📞 *সাপোর্ট সেন্টার*\n\n"
            f"📢 *মেইন চ্যানেল:* {MAIN_CHANNEL}\n"
            f"👥 *OTP গ্রুপ:* {OTP_GROUP}\n\n"
            f"❓ *সাধারণ জিজ্ঞাসা:*\n"
            f"• OTP পেতে কতক্ষণ লাগে? 1-3 মিনিট\n"
            f"• মিনিমাম উইথড্র: {MIN_WITHDRAW} TK\n\n"
            f"👨‍💻 *সাপোর্ট:* {SUPPORT_ID}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "⚙️ Admin Panel" and is_admin:
        await update.message.reply_text("⚙️ *অ্যাডমিন প্যানেল*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_admin_keyboard())
    
    elif text == "🔙 Back to Main" and is_admin:
        await update.message.reply_text("🏠 *মেইন মেনু*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin))
    
    # ==================== ADMIN COMMANDS ====================
    elif text == "➕ Add Number" and is_admin:
        if not available_numbers:
            await update.message.reply_text("❌ প্রথমে একটি দেশ যোগ করুন। '🌍 Edit Country' বাটন ব্যবহার করুন।")
            return
        countries = list(available_numbers.keys())
        await update.message.reply_text(
            "🌍 *কোন দেশে নম্বর যোগ করবেন?*\n\nনিচ থেকে দেশ নির্বাচন করুন:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_admin_country_keyboard(countries, "addnum_country")
        )
    
    elif text == "📋 List Numbers" and is_admin:
        if available_numbers:
            msg = "📋 *উপলব্ধ নম্বর*\n\n"
            for country, nums in available_numbers.items():
                price = country_prices.get(country, 0.30)
                used = sum(1 for n in nums if number_usage_stats.get(n, {}).get('used', False))
                available_count = len(nums) - used
                msg += f"*{country}:* মোট: {len(nums)} | উপলব্ধ: {available_count} | ব্যবহৃত: {used} (প্রতি OTP: {price} TK)\n"
                for num in nums[:5]:
                    status = "✅" if not number_usage_stats.get(num, {}).get('used', False) else "❌"
                    msg += f"  {status} `{num}`\n"
                msg += "\n"
            
            if len(msg) > 4000:
                msg = msg[:4000] + "\n\n... আরও নম্বর আছে"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("কোনো নম্বর নেই। প্রথমে দেশ যোগ করুন।")
    
    elif text == "🌍 Edit Country" and is_admin:
        await update.message.reply_text(
            "🌍 *কান্ট্রি এডিট করুন*\n\n"
            "নিচের কমান্ড ব্যবহার করুন:\n\n"
            "`/addcountry দেশের_নাম` - নতুন দেশ যোগ করুন\n"
            "`/removecountry দেশের_নাম` - দেশ মুছুন\n\n"
            "উদাহরণ:\n"
            "`/addcountry Canada`\n"
            "`/removecountry Germany`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "💰 Set Price" and is_admin:
        if not available_numbers:
            await update.message.reply_text("❌ প্রথমে একটি দেশ যোগ করুন।")
            return
        countries = list(available_numbers.keys())
        await update.message.reply_text(
            "💰 *OTP দাম সেট করুন*\n\nকোন দেশের দাম পরিবর্তন করবেন?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_price_set_keyboard(countries)
        )
    
    elif text == "💸 Process Withdrawals" and is_admin:
        if pending_withdrawals:
            msg = "💸 *পেন্ডিং উইথড্র*\n\n"
            for uid, wd in pending_withdrawals.items():
                msg += f"👤 ইউজার: `{uid}`\n💰 টাকা: {wd['amount']:.2f} TK\n💳 মেথড: {wd['method']}\n📱 একাউন্ট: {wd['account']}\n➖➖➖\n\n"
            msg += "অ্যাপ্রুভ করতে: `/approvewd ইউজার_ID`\nরিজেক্ট করতে: `/rejectwd ইউজার_ID`"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("কোনো পেন্ডিং উইথড্র নেই।")
    
    elif text == "📊 Statistics" and is_admin:
        total_users = len(user_balances)
        total_balance = sum(user_balances.values())
        total_earned = sum(s.get('total_earned', 0) for s in user_stats.values())
        total_otps = sum(s.get('total_otps', 0) for s in user_stats.values())
        total_numbers = sum(len(nums) for nums in available_numbers.values())
        used_numbers = sum(1 for stats in number_usage_stats.values() if stats.get('used', False))
        await update.message.reply_text(
            f"📊 *পরিসংখ্যান*\n\n"
            f"👥 ইউজার: {total_users}\n"
            f"💰 মোট ব্যালেন্স: {total_balance:.2f} TK\n"
            f"💵 মোট আয়: {total_earned:.2f} TK\n"
            f"🔑 মোট OTP: {total_otps}\n"
            f"📱 মোট নম্বর: {total_numbers}\n"
            f"✅ ব্যবহৃত নম্বর: {used_numbers}\n"
            f"🆓 উপলব্ধ নম্বর: {total_numbers - used_numbers}\n"
            f"🌍 মোট দেশ: {len(available_numbers)}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "📨 Broadcast" and is_admin:
        await update.message.reply_text(
            "📨 *ব্রডকাস্ট*\n\n"
            "সব ইউজারকে মেসেজ পাঠান:\n"
            "`/broadcast আপনার মেসেজ`"
        )
    
    elif text == "👥 Users List" and is_admin:
        msg = "👥 *ইউজার লিস্ট*\n\n"
        for uid, bal in sorted(user_balances.items(), key=lambda x: x[1], reverse=True)[:30]:
            stats = user_stats.get(uid, {})
            msg += f"• `{uid}` - {bal:.2f} TK (OTP: {stats.get('total_otps', 0)})\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    
    elif text == "🚫 Ban/Unban User" and is_admin:
        await update.message.reply_text(
            "🚫 *ব্যান/আনব্যান ইউজার*\n\n"
            "ব্যান করতে: `/ban ইউজার_ID কারণ`\n"
            "উদাহরণ: `/ban 123456789 স্প্যাম`\n\n"
            "আনব্যান করতে: `/unban ইউজার_ID`\n"
            "উদাহরণ: `/unban 123456789`"
        )
    
    elif text == "📥 Export Data" and is_admin:
        await update.message.reply_text(
            "📥 *ডাটা এক্সপোর্ট*\n\n"
            "কমান্ড:\n"
            "`/export users` - ইউজার লিস্ট\n"
            "`/export numbers` - নম্বর লিস্ট"
        )
    
    # ==================== WITHDRAW COMMAND ====================
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
                    f"✅ *উইথড্র রিকোয়েস্ট জমা হয়েছে!*\n\n"
                    f"💰 টাকা: {amount:.2f} TK\n"
                    f"💳 মেথড: {method}\n"
                    f"📱 একাউন্ট: {account}\n\n"
                    f"⏳ ২৪ ঘন্টার মধ্যে প্রসেস করা হবে।",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_main_keyboard(is_admin)
                )
                await context.bot.send_message(ADMIN_ID, f"💰 উইথড্র রিকোয়েস্ট\nইউজার: {user_id}\nটাকা: {amount:.2f} TK\nমেথড: {method}\nএকাউন্ট: {account}")
            else:
                await update.message.reply_text(f"❌ মিনিমাম উইথড্র: {MIN_WITHDRAW} TK\nআপনার ব্যালেন্স: {amount:.2f} TK", reply_markup=get_main_keyboard(is_admin))
        else:
            await update.message.reply_text("❌ ব্যবহার: `/withdraw মেথড একাউন্ট`\nউদাহরণ: `/withdraw bKash 01XXXXXXXXX`", reply_markup=get_main_keyboard(is_admin))

# ==================== CALLBACK HANDLER ====================
async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    is_admin = user_id == ADMIN_ID
    
    if user_id in banned_users:
        await query.edit_message_text("❌ আপনি বanned!")
        return
    
    if data == "back_home":
        await query.edit_message_text("🏠 *মেইন মেনুতে ফিরে এসেছেন*", parse_mode=ParseMode.MARKDOWN)
        await query.message.reply_text("মেইন মেনু", reply_markup=get_main_keyboard(is_admin))
        return
    
    elif data == "back_to_admin":
        await query.edit_message_text("⚙️ *অ্যাডমিন প্যানেল*", parse_mode=ParseMode.MARKDOWN)
        await query.message.reply_text("অ্যাডমিন প্যানেল", reply_markup=get_admin_keyboard())
        return
    
    # Admin add number country selection
    elif data.startswith("addnum_country_"):
        country = data.replace("addnum_country_", "")
        context.user_data['pending_country'] = country
        context.user_data['awaiting_numbers'] = True
        await query.edit_message_text(
            f"➕ *{country} দেশে নম্বর যোগ করুন*\n\n"
            f"নম্বর গুলো পাঠান (এক লাইনে একটি):\n"
            f"ফরম্যাট: `দেশেরকোড নম্বর` (যেমন: 8801712345678 বা +8801712345678)\n\n"
            f"অথবা একটি .txt ফাইল আপলোড করুন।\n\n"
            f"বাতিল করতে /cancel টাইপ করুন।",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Admin set price
    elif data.startswith("setprice_"):
        country = data.replace("setprice_", "")
        context.user_data['awaiting_price'] = True
        context.user_data['price_country'] = country
        current_price = country_prices.get(country, 0.30)
        await query.edit_message_text(
            f"💰 *{country} দেশের OTP দাম সেট করুন*\n\n"
            f"বর্তমান দাম: {current_price} TK\n\n"
            f"নতুন দাম টাকা হিসেবে লিখুন:\n"
            f"উদাহরণ: `0.50` বা `1.00`\n\n"
            f"বাতিল করতে /cancel টাইপ করুন।",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # User select country - Show UNMASKED numbers to user
    elif data.startswith("select_country_"):
        country = data.replace("select_country_", "")
        user_selected_country[user_id] = country
        
        all_numbers = available_numbers.get(country, [])
        unused_numbers = [num for num in all_numbers if not number_usage_stats.get(num, {}).get('used', False)]
        
        if not unused_numbers:
            await query.edit_message_text(
                f"❌ *{country} দেশে কোনো উপলব্ধ নম্বর নেই!*\n\nসব নম্বর ব্যবহার করা হয়েছে। অ্যাডমিন নতুন নম্বর যোগ করুন।",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Change Country", callback_data="back_to_countries")],
                    [InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")]
                ])
            )
            return
        
        selected_numbers = random.sample(unused_numbers, min(3, len(unused_numbers)))
        user_current_numbers[user_id] = {
            'numbers': selected_numbers,
            'country': country,
            'selected_time': time.time()
        }
        
        # Show FULL NUMBERS (NOT MASKED) to user
        numbers_text = ""
        for idx, num in enumerate(selected_numbers, 1):
            numbers_text += f"{idx}. `{num}`\n"
        
        message_text = f"✅ *{country} দেশের নম্বর*\n\n{numbers_text}\n\n👇 *যেকোনো নম্বর কপি করতে উপরের নম্বরে ক্লিক করুন*\n\n⏳ *ওয়েটিং ফর ওটিপি...*\nনম্বর কপি করে যেখানে প্রয়োজন সেখানে ব্যবহার করুন।"
        
        await query.edit_message_text(
            message_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_numbers_post_keyboard(selected_numbers, country)
        )
        
        user_waiting_for_otp[user_id] = {
            'numbers': selected_numbers,
            'country': country,
            'start_time': time.time(),
            'otp_received': False
        }
        
        # Start background OTP check for each number
        for number in selected_numbers:
            asyncio.create_task(check_otp_background(context, user_id, number, country))
        return
    
    # Change number - Show UNMASKED numbers to user
    elif data.startswith("change_number_"):
        country = data.replace("change_number_", "")
        
        all_numbers = available_numbers.get(country, [])
        unused_numbers = [num for num in all_numbers if not number_usage_stats.get(num, {}).get('used', False)]
        
        if not unused_numbers:
            await query.edit_message_text(
                f"❌ *{country} দেশে কোনো উপলব্ধ নম্বর নেই!*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Change Country", callback_data="back_to_countries")],
                    [InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")]
                ])
            )
            return
        
        selected_numbers = random.sample(unused_numbers, min(3, len(unused_numbers)))
        user_current_numbers[user_id] = {
            'numbers': selected_numbers,
            'country': country,
            'selected_time': time.time()
        }
        
        if user_id in user_waiting_for_otp:
            del user_waiting_for_otp[user_id]
        
        # Show FULL NUMBERS (NOT MASKED) to user
        numbers_text = ""
        for idx, num in enumerate(selected_numbers, 1):
            numbers_text += f"{idx}. `{num}`\n"
        
        message_text = f"✅ *{country} দেশের নতুন নম্বর*\n\n{numbers_text}\n\n👇 *যেকোনো নম্বর কপি করতে উপরের নম্বরে ক্লিক করুন*\n\n⏳ *ওয়েটিং ফর ওটিপি...*"
        
        await query.edit_message_text(
            message_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_numbers_post_keyboard(selected_numbers, country)
        )
        
        user_waiting_for_otp[user_id] = {
            'numbers': selected_numbers,
            'country': country,
            'start_time': time.time(),
            'otp_received': False
        }
        
        for number in selected_numbers:
            asyncio.create_task(check_otp_background(context, user_id, number, country))
        return
    
    # Back to countries selection
    elif data == "back_to_countries":
        countries = list(available_numbers.keys())
        await query.edit_message_text(
            "🌍 *দেশ সিলেক্ট করুন*\n\nনিচ থেকে আপনার পছন্দের দেশ নির্বাচন করুন:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_country_selection_keyboard(countries)
        )
        return
    
    # Check OTP
    elif data.startswith("check_otp_"):
        number = data.replace("check_otp_", "")
        
        target_user = None
        for uid, info in user_waiting_for_otp.items():
            if number in info.get('numbers', []):
                target_user = uid
                break
        
        if not target_user:
            await query.answer("এই নম্বরটি আপনার সেশনে নেই। নতুন নম্বর নিন।", show_alert=True)
            return
        
        if target_user != user_id:
            await query.answer("এই নম্বরটি অন্য ব্যবহারকারী ব্যবহার করছে।", show_alert=True)
            return
        
        if user_id in active_orders and active_orders.get(user_id, {}).get('number') == number and active_orders.get(user_id, {}).get('otp'):
            otp_data = active_orders[user_id]
            price = country_prices.get(otp_data.get('country', 'Unknown'), 0.30)
            await query.edit_message_text(
                f"✅ *OTP প্রাপ্ত হয়েছে!*\n\n"
                f"📱 *নম্বর:* `{number}`\n"
                f"🔧 *সার্ভিস:* {otp_data.get('service', 'Unknown')}\n\n"
                f"🔑 *OTP কোড:* `{otp_data['otp']}` ✅\n\n"
                f"💰 *আয় হয়েছে:* +{price} TK\n"
                f"💵 *বর্তমান ব্যালেন্স:* {user_balances.get(user_id, 0):.2f} TK",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_otp_check_keyboard(number, otp_data.get('country', 'Unknown'))
            )
        else:
            result = web_panel.get_otp(number)
            if result and result.get('otp'):
                otp = result['otp']
                service = result.get('service', 'Unknown')
                country = user_waiting_for_otp.get(user_id, {}).get('country', 'Unknown')
                price = country_prices.get(country, 0.30)
                
                user_balances[user_id] = user_balances.get(user_id, 0) + price
                if user_id not in user_stats:
                    user_stats[user_id] = {'total_otps': 0, 'total_earned': 0}
                user_stats[user_id]['total_otps'] = user_stats[user_id].get('total_otps', 0) + 1
                user_stats[user_id]['total_earned'] = user_stats[user_id].get('total_earned', 0) + price
                
                if number not in number_usage_stats:
                    number_usage_stats[number] = {'used': False, 'used_by': None, 'used_time': None}
                number_usage_stats[number]['used'] = True
                number_usage_stats[number]['used_by'] = user_id
                number_usage_stats[number]['used_time'] = datetime.now().isoformat()
                
                if user_id not in user_transactions:
                    user_transactions[user_id] = []
                user_transactions[user_id].append({
                    'type': 'earned', 'amount': price, 'number': number,
                    'otp': otp, 'service': service, 'country': country,
                    'time': datetime.now().isoformat()
                })
                save_data()
                
                active_orders[user_id] = {
                    'number': number, 'country': country, 'otp': otp, 'service': service
                }
                
                if user_id in user_waiting_for_otp:
                    user_waiting_for_otp[user_id]['otp_received'] = True
                
                await query.edit_message_text(
                    f"✅ *OTP প্রাপ্ত হয়েছে!*\n\n"
                    f"📱 *নম্বর:* `{number}`\n"
                    f"🔧 *সার্ভিস:* {service}\n\n"
                    f"🔑 *OTP কোড:* `{otp}` ✅\n\n"
                    f"💰 *আয় হয়েছে:* +{price} TK\n"
                    f"💵 *বর্তমান ব্যালেন্স:* {user_balances[user_id]:.2f} TK",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_otp_check_keyboard(number, country)
                )
                
                # Send to OTP Group with MASKED number
                masked_number = mask_number_for_group(number)
                await context.bot.send_message(OTP_GROUP,
                    f"🔐 *OTP Service | OTP প্রাপ্ত*\n\n"
                    f"📱 *নম্বর:* `{masked_number}`\n"
                    f"🌍 *দেশ:* {country}\n"
                    f"🔧 *সার্ভিস:* {service}\n"
                    f"✅ *স্ট্যাটাস:* প্রাপ্ত\n"
                    f"🔑 *OTP কোড:* `{otp}`\n\n"
                    f"`#{otp} is your {service} verification code`\n\n"
                    f"🔗 @{BOT_USERNAME} | {MAIN_CHANNEL}",
                    parse_mode=ParseMode.MARKDOWN)
                
                # Send to user privately
                await context.bot.send_message(user_id,
                    f"🔐 *OTP প্রাপ্ত!*\n\n"
                    f"📱 *নম্বর:* `{number}`\n"
                    f"🔧 *সার্ভিস:* {service}\n"
                    f"🔑 *OTP:* `{otp}`\n\n"
                    f"💰 *+{price} TK যোগ হয়েছে!*\n"
                    f"💵 *নতুন ব্যালেন্স:* {user_balances[user_id]:.2f} TK",
                    parse_mode=ParseMode.MARKDOWN)
            else:
                await query.answer("OTP এখনো আসেনি। আরও 1-2 মিনিট অপেক্ষা করুন।", show_alert=True)
        return
    
    # 2FA CALLBACKS
    elif data == "2fa_refresh":
        if user_id in totp_secrets:
            secret = totp_secrets[user_id]
            code = TOTPGenerator.get_code(secret)
            remaining = TOTPGenerator.time_left()
            kb = get_2fa_display_keyboard(secret, code, remaining)
            await query.edit_message_text(
                f"🔐 *2FA অথেনটিকেটর*\n\n"
                f"🔑 *সিক্রেট কী:* `{secret}`\n\n"
                f"🔢 *বর্তমান কোড:* `{code}`\n"
                f"⏱ {remaining} সেকেন্ড পর কোড পরিবর্তন হবে\n\n"
                f"✅ কোডটি কপি করতে কোডের উপর ক্লিক করুন",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
        else:
            await query.edit_message_text("❌ কোনো সিক্রেট কী নেই। প্রথমে একটি পাঠান।")
        return
    
    elif data == "2fa_cancel":
        context.user_data['awaiting_2fa'] = False
        await query.edit_message_text("❌ 2FA সেটআপ বাতিল করা হয়েছে।")
        await query.message.reply_text("মেইন মেনু", reply_markup=get_main_keyboard(is_admin))
        return
    
    elif data == "noop":
        await query.answer()
        return

# ==================== BACKGROUND TASKS ====================
async def auto_refresh_2fa(context, chat_id, user_id):
    """Auto refresh 2FA code - sends only ONE message"""
    message_id = None
    first_run = True
    
    while user_id in totp_secrets:
        await asyncio.sleep(1)
        if user_id in totp_secrets:
            secret = totp_secrets[user_id]
            code = TOTPGenerator.get_code(secret)
            remaining = TOTPGenerator.time_left()
            kb = get_2fa_display_keyboard(secret, code, remaining)
            
            try:
                # Only edit existing message, don't send new ones
                if message_id:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"🔐 *2FA অথেনটিকেটর*\n\n"
                             f"🔑 *সিক্রেট কী:* `{secret}`\n\n"
                             f"🔢 *বর্তমান কোড:* `{code}`\n"
                             f"⏱ {remaining} সেকেন্ড পর কোড পরিবর্তন হবে\n\n"
                             f"✅ কোডটি কপি করতে কোডের উপর ক্লিক করুন",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=kb
                    )
                elif first_run:
                    # Send initial message only once
                    msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🔐 *2FA অথেনটিকেটর*\n\n"
                             f"🔑 *সিক্রেট কী:* `{secret}`\n\n"
                             f"🔢 *বর্তমান কোড:* `{code}`\n"
                             f"⏱ {remaining} সেকেন্ড পর কোড পরিবর্তন হবে\n\n"
                             f"✅ কোডটি কপি করতে কোডের উপর ক্লিক করুন",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=kb
                    )
                    message_id = msg.message_id
                    first_run = False
            except Exception as e:
                pass

async def check_otp_background(context, user_id, number, country):
    """Background task to check OTP for a number"""
    for attempt in range(60):  # Check for 3 minutes
        await asyncio.sleep(3)
        
        if user_id not in user_waiting_for_otp:
            return
        
        if user_waiting_for_otp[user_id].get('otp_received', False):
            return
        
        if number not in user_waiting_for_otp[user_id].get('numbers', []):
            return
        
        result = web_panel.get_otp(number)
        if result and result.get('otp'):
            otp = result['otp']
            service = result.get('service', 'Unknown')
            price = country_prices.get(country, 0.30)
            
            user_balances[user_id] = user_balances.get(user_id, 0) + price
            if user_id not in user_stats:
                user_stats[user_id] = {'total_otps': 0, 'total_earned': 0}
            user_stats[user_id]['total_otps'] = user_stats[user_id].get('total_otps', 0) + 1
            user_stats[user_id]['total_earned'] = user_stats[user_id].get('total_earned', 0) + price
            
            if number not in number_usage_stats:
                number_usage_stats[number] = {'used': False, 'used_by': None, 'used_time': None}
            number_usage_stats[number]['used'] = True
            number_usage_stats[number]['used_by'] = user_id
            number_usage_stats[number]['used_time'] = datetime.now().isoformat()
            
            if user_id not in user_transactions:
                user_transactions[user_id] = []
            user_transactions[user_id].append({
                'type': 'earned', 'amount': price, 'number': number,
                'otp': otp, 'service': service, 'country': country,
                'time': datetime.now().isoformat()
            })
            save_data()
            
            active_orders[user_id] = {
                'number': number, 'country': country, 'otp': otp, 'service': service
            }
            
            user_waiting_for_otp[user_id]['otp_received'] = True
            
            # Send to OTP Group with MASKED number
            masked_number = mask_number_for_group(number)
            await context.bot.send_message(OTP_GROUP,
                f"🔐 *OTP Service | OTP প্রাপ্ত*\n\n"
                f"📱 *নম্বর:* `{masked_number}`\n"
                f"🌍 *দেশ:* {country}\n"
                f"🔧 *সার্ভিস:* {service}\n"
                f"✅ *স্ট্যাটাস:* প্রাপ্ত\n"
                f"🔑 *OTP কোড:* `{otp}`\n\n"
                f"`#{otp} is your {service} verification code`\n\n"
                f"🔗 @{BOT_USERNAME} | {MAIN_CHANNEL}",
                parse_mode=ParseMode.MARKDOWN)
            
            # Send to user privately with FULL number
            await context.bot.send_message(user_id,
                f"🔐 *OTP প্রাপ্ত!*\n\n"
                f"📱 *নম্বর:* `{number}`\n"
                f"🔧 *সার্ভিস:* {service}\n"
                f"🔑 *OTP:* `{otp}`\n\n"
                f"💰 *+{price} TK যোগ হয়েছে!*\n"
                f"💵 *নতুন ব্যালেন্স:* {user_balances[user_id]:.2f} TK\n\n"
                f"✅ OTP টি কপি করে ব্যবহার করুন।",
                parse_mode=ParseMode.MARKDOWN)
            
            return

# ==================== ADMIN COMMAND HANDLERS ====================
async def admin_commands(update, context):
    user_id = update.effective_user.id
    text = update.message.text
    is_admin = user_id == ADMIN_ID
    
    if not is_admin:
        return
    
    if text.startswith('/addcountry'):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            country = parts[1]
            if country not in available_numbers:
                available_numbers[country] = []
                country_prices[country] = 0.30
                save_data()
                await update.message.reply_text(f"✅ '{country}' দেশ যোগ করা হয়েছে\nডিফল্ট দাম: 0.30 TK\n\nএখন '➕ Add Number' বাটন দিয়ে নম্বর যোগ করুন।")
            else:
                await update.message.reply_text("❌ দেশটি ইতিমধ্যে আছে")
        else:
            await update.message.reply_text("❌ ব্যবহার: `/addcountry দেশের_নাম`\nউদাহরণ: `/addcountry Canada`")
    
    elif text.startswith('/removecountry'):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            country = parts[1]
            if country in available_numbers:
                del available_numbers[country]
                if country in country_prices:
                    del country_prices[country]
                save_data()
                await update.message.reply_text(f"✅ '{country}' দেশ এবং এর সব নম্বর মুছে ফেলা হয়েছে")
            else:
                await update.message.reply_text("❌ দেশটি পাওয়া যায়নি")
        else:
            await update.message.reply_text("❌ ব্যবহার: `/removecountry দেশের_নাম`")
    
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
                await update.message.reply_text(f"✅ {amount} TK যোগ করা হয়েছে `{target}` এ", parse_mode=ParseMode.MARKDOWN)
                try:
                    await context.bot.send_message(target, f"💰 +{amount} TK আপনার ব্যালেন্সে যোগ করা হয়েছে!\nবর্তমান ব্যালেন্স: {user_balances[target]:.2f} TK")
                except:
                    pass
            except ValueError:
                await update.message.reply_text("❌ ভুল ইউজার আইডি বা টাকা")
        else:
            await update.message.reply_text("❌ ব্যবহার: `/addbal ইউজার_ID টাকা`\nউদাহরণ: `/addbal 7064572216 100`")
    
    elif text.startswith('/broadcast'):
        msg = text.replace('/broadcast', '', 1).strip()
        if msg:
            sent = 0
            failed = 0
            for uid in user_balances.keys():
                try:
                    await context.bot.send_message(uid, f"📢 *ঘোষণা*\n\n{msg}", parse_mode=ParseMode.MARKDOWN)
                    sent += 1
                    await asyncio.sleep(0.05)
                except:
                    failed += 1
            await update.message.reply_text(f"✅ {sent} জন ইউজারকে মেসেজ পাঠানো হয়েছে\n❌ ব্যর্থ: {failed}")
        else:
            await update.message.reply_text("❌ ব্যবহার: `/broadcast মেসেজ`")
    
    elif text.startswith('/approvewd'):
        parts = text.split()
        if len(parts) == 2:
            target = int(parts[1])
            if target in pending_withdrawals:
                wd = pending_withdrawals[target]
                del pending_withdrawals[target]
                save_data()
                await update.message.reply_text(f"✅ উইথড্র অ্যাপ্রুভ করা হয়েছে `{target}` এর জন্য\nটাকা: {wd['amount']:.2f} TK", parse_mode=ParseMode.MARKDOWN)
                try:
                    await context.bot.send_message(target, f"✅ *আপনার উইথড্র অনুমোদিত হয়েছে!*\n\n💰 টাকা: {wd['amount']:.2f} TK\n💳 মেথড: {wd['method']}\n📱 একাউন্ট: {wd['account']}\n\nধন্যবাদ।")
                except:
                    pass
            else:
                await update.message.reply_text("❌ উইথড্র রিকোয়েস্ট পাওয়া যায়নি")
        else:
            await update.message.reply_text("❌ ব্যবহার: `/approvewd ইউজার_ID`")
    
    elif text.startswith('/rejectwd'):
        parts = text.split()
        if len(parts) == 2:
            target = int(parts[1])
            if target in pending_withdrawals:
                wd = pending_withdrawals[target]
                del pending_withdrawals[target]
                user_balances[target] = user_balances.get(target, 0) + wd['amount']
                save_data()
                await update.message.reply_text(f"❌ উইথড্র রিজেক্ট করা হয়েছে `{target}` এর জন্য\nটাকা ফেরত দেওয়া হয়েছে: {wd['amount']:.2f} TK", parse_mode=ParseMode.MARKDOWN)
                try:
                    await context.bot.send_message(target, f"❌ *আপনার উইথড্র রিজেক্ট করা হয়েছে!*\n\nকারণ: অনুগ্রহ করে সঠিক তথ্য দিন।\n💰 {wd['amount']:.2f} TK আপনার ব্যালেন্সে ফেরত দেওয়া হয়েছে।")
                except:
                    pass
            else:
                await update.message.reply_text("❌ উইথড্র রিকোয়েস্ট পাওয়া যায়নি")
        else:
            await update.message.reply_text("❌ ব্যবহার: `/rejectwd ইউজার_ID`")
    
    elif text.startswith('/ban'):
        parts = text.split(maxsplit=2)
        if len(parts) >= 2:
            target = int(parts[1])
            reason = parts[2] if len(parts) > 2 else "কারণ উল্লেখ নেই"
            banned_users[target] = reason
            save_data()
            await update.message.reply_text(f"🚫 `{target}` ব্যান করা হয়েছে\nকারণ: {reason}", parse_mode=ParseMode.MARKDOWN)
            try:
                await context.bot.send_message(target, f"🚫 *আপনি ব্যান করা হয়েছে!*\n\nকারণ: {reason}\n\nঅ্যাপিলের জন্য যোগাযোগ করুন: {SUPPORT_ID}")
            except:
                pass
        else:
            await update.message.reply_text("❌ ব্যবহার: `/ban ইউজার_ID কারণ`\nউদাহরণ: `/ban 123456789 স্প্যাম`")
    
    elif text.startswith('/unban'):
        parts = text.split()
        if len(parts) == 2:
            target = int(parts[1])
            if target in banned_users:
                del banned_users[target]
                save_data()
                await update.message.reply_text(f"✅ `{target}` আনব্যান করা হয়েছে", parse_mode=ParseMode.MARKDOWN)
                try:
                    await context.bot.send_message(target, f"✅ *আপনি আনব্যান করা হয়েছে!*\n\nআপনি আবার বট ব্যবহার করতে পারবেন।")
                except:
                    pass
            else:
                await update.message.reply_text("❌ ইউজারটি ব্যান করা নেই")
        else:
            await update.message.reply_text("❌ ব্যবহার: `/unban ইউজার_ID`")
    
    elif text.startswith('/export'):
        parts = text.split()
        if len(parts) == 2:
            if parts[1] == 'users':
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(['User ID', 'Balance', 'Total OTPs', 'Total Earned', 'Joined'])
                for uid in user_balances:
                    stats = user_stats.get(uid, {})
                    writer.writerow([uid, user_balances[uid], stats.get('total_otps', 0), stats.get('total_earned', 0), stats.get('joined', '')])
                output.seek(0)
                await update.message.reply_document(InputFile(io.BytesIO(output.getvalue().encode()), filename='users.csv'))
            elif parts[1] == 'numbers':
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(['Country', 'Number', 'Price', 'Used', 'Used By', 'Used Time'])
                for country, nums in available_numbers.items():
                    price = country_prices.get(country, 0.30)
                    for num in nums:
                        usage = number_usage_stats.get(num, {})
                        writer.writerow([country, num, price, usage.get('used', False), usage.get('used_by', ''), usage.get('used_time', '')])
                output.seek(0)
                await update.message.reply_document(InputFile(io.BytesIO(output.getvalue().encode()), filename='numbers.csv'))
            else:
                await update.message.reply_text("❌ ব্যবহার: `/export users` বা `/export numbers`")
        else:
            await update.message.reply_text("❌ ব্যবহার: `/export users` বা `/export numbers`")
    
    elif text == '/stats':
        total_users = len(user_balances)
        total_balance = sum(user_balances.values())
        total_earned = sum(s.get('total_earned', 0) for s in user_stats.values())
        total_otps = sum(s.get('total_otps', 0) for s in user_stats.values())
        total_numbers = sum(len(nums) for nums in available_numbers.values())
        used_numbers = sum(1 for stats in number_usage_stats.values() if stats.get('used', False))
        pending_wd = len(pending_withdrawals)
        await update.message.reply_text(
            f"📊 *বট পরিসংখ্যান*\n\n"
            f"👥 মোট ইউজার: {total_users}\n"
            f"💰 মোট ব্যালেন্স: {total_balance:.2f} TK\n"
            f"💵 মোট আয়: {total_earned:.2f} TK\n"
            f"🔑 মোট OTP: {total_otps}\n"
            f"📱 মোট নম্বর: {total_numbers}\n"
            f"✅ ব্যবহৃত নম্বর: {used_numbers}\n"
            f"🆓 উপলব্ধ নম্বর: {total_numbers - used_numbers}\n"
            f"🌍 মোট দেশ: {len(available_numbers)}\n"
            f"💸 পেন্ডিং উইথড্র: {pending_wd}",
            parse_mode=ParseMode.MARKDOWN)
    
    elif text == '/login':
        if web_panel.login():
            await update.message.reply_text("✅ ওয়েব প্যানেলে লগইন সফল!")
        else:
            await update.message.reply_text("❌ লগইন ব্যর্থ! ইউজারনেম/পাসওয়ার্ড চেক করুন।")
    
    # Handle file upload for bulk numbers
    if update.message.document:
        country = context.user_data.get('pending_country')
        if not country:
            await update.message.reply_text("❌ প্রথমে দেশ নির্বাচন করুন। '➕ Add Number' বাটন ব্যবহার করুন।")
            return
        
        file = await update.message.document.get_file()
        file_path = f"/tmp/{update.message.document.file_name}"
        await file.download_to_drive(file_path)
        
        added = 0
        duplicate = 0
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('Country') and not line.startswith('দেশ'):
                    num = line
                    if not num.startswith('+'):
                        num = '+' + num
                    if country not in available_numbers:
                        available_numbers[country] = []
                    if num not in available_numbers[country]:
                        available_numbers[country].append(num)
                        added += 1
                    else:
                        duplicate += 1
        save_data()
        context.user_data['awaiting_numbers'] = False
        context.user_data['pending_country'] = None
        await update.message.reply_text(f"✅ {added} টি নম্বর {country} দেশে যোগ করা হয়েছে!\n❌ ডুপ্লিকেট: {duplicate}\n\nমোট নম্বর: {len(available_numbers.get(country, []))} টি")

async def twofa_command(update, context):
    context.user_data['awaiting_2fa'] = True
    await update.message.reply_text(
        "🔐 *2FA অথেনটিকেটর*\n\n"
        "আপনার সিক্রেট কী পাঠান:\n"
        "উদাহরণ: `JBSWY3DPEHPK3PXP`\n\n"
        "বাতিল করতে Cancel বাটনে ক্লিক করুন।",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_2fa_initial_keyboard()
    )
    return SECRET_KEY_STATE

async def myid_command(update, context):
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 *আপনার তথ্য*\n\n"
        f"👤 *নাম:* {user.first_name} {user.last_name or ''}\n"
        f"🆔 *ইউজার আইডি:* `{user.id}`\n"
        f"📊 *ইউজারনেম:* @{user.username if user.username else 'সেট করা নেই'}\n\n"
        f"এই আইডিটি ব্যালেন্স যোগ করতে বা সমস্যা সমাধানে ব্যবহার করুন।",
        parse_mode=ParseMode.MARKDOWN
    )

# ==================== FLASK WEBHOOK ====================
@flask_app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        application.update_queue.put_nowait(update)
        return 'ok', 200
    except Exception as e:
        return str(e), 500

@flask_app.route('/health')
def health():
    return jsonify({
        'status': 'alive', 
        'users': len(user_balances), 
        'numbers': sum(len(n) for n in available_numbers.values()),
        'used_numbers': sum(1 for stats in number_usage_stats.values() if stats.get('used', False)),
        'time': datetime.now().isoformat()
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    application = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("twofa", twofa_command)],
        states={SECRET_KEY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)]},
        fallbacks=[CallbackQueryHandler(callback_handler, pattern="^2fa_cancel$")]
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, admin_commands))
    application.add_handler(MessageHandler(filters.Document.ALL, admin_commands))
    
    web_panel.login()
    
    if os.environ.get('PORT'):
        port = int(os.environ.get('PORT', 8080))
        url = os.environ.get('WEBHOOK_URL', '')
        if url:
            application.bot.set_webhook(url)
        flask_app.run(host='0.0.0.0', port=port)
    else:
        print("🤖 OTP Service Bot is running...")
        application.run_polling()
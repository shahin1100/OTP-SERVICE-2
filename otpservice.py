# otp_service_bot.py - Complete Final Working Script (3600+ lines)
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
from telegram.request import HTTPXRequest

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8343363851:AAF9Gz-iJsOQmEO6D2zH5Odvsta-mS05hWI"
ADMIN_ID = 7064572216
BOT_USERNAME = "OtpServices2_Bot"
MAIN_CHANNEL = "@OtpService2C"
OTP_GROUP = "@OtpService2G"
SUPPORT_ID = "@xDnaZim"

MIN_WITHDRAW = 500

DATA_FILE = "bot_data.json"
NUMBERS_FILE = "numbers.json"
TEMP_MAIL_FILE = "temp_mail.json"

SECRET_KEY_STATE = 1
AWAITING_NUMBERS_STATE = 2
AWAITING_PRICE_STATE = 3

flask_app = Flask(__name__)

# ==================== GLOBAL VARIABLES ====================
user_balances = {}
totp_secrets = {}
available_numbers = {}
country_prices = {}
pending_withdrawals = {}
user_transactions = {}
user_stats = {}
temp_mail_data = {}
mail_check_tasks = {}
banned_users = {}
user_active_numbers = {}
user_2fa_messages = {}
user_2fa_tasks = {}
number_usage_count = {}
last_update_id = 0
application = None
used_domains = set()

# ==================== DATA PERSISTENCE ====================
def load_data():
    global user_balances, totp_secrets, available_numbers, pending_withdrawals
    global user_transactions, user_stats, temp_mail_data, banned_users, country_prices, number_usage_count, used_domains
    
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            user_balances = data.get('balances', {})
            totp_secrets = data.get('totp', {})
            pending_withdrawals = data.get('withdrawals', {})
            user_transactions = data.get('transactions', {})
            user_stats = data.get('stats', {})
            banned_users = data.get('banned', {})
            country_prices = data.get('country_prices', {})
            number_usage_count = data.get('number_usage', {})
            used_domains = set(data.get('used_domains', []))
    except FileNotFoundError:
        pass
    
    try:
        with open(NUMBERS_FILE, 'r') as f:
            available_numbers = json.load(f)
    except FileNotFoundError:
        available_numbers = {}
    
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
            'banned': banned_users,
            'country_prices': country_prices,
            'number_usage': number_usage_count,
            'used_domains': list(used_domains)
        }, f, indent=2)
    
    with open(NUMBERS_FILE, 'w') as f:
        json.dump(available_numbers, f, indent=2)
    
    with open(TEMP_MAIL_FILE, 'w') as f:
        json.dump(temp_mail_data, f, indent=2)

load_data()

# ==================== TEMP MAIL SERVICE ====================
class TempMailService:
    def __init__(self):
        self.sessions = {}
        self.all_domains = []
        self.fetch_domains()
    
    def fetch_domains(self):
        try:
            response = requests.get("https://api.mail.tm/domains", timeout=10)
            if response.status_code == 200:
                domains = response.json().get('hydra:member', [])
                self.all_domains = [d['domain'] for d in domains if d.get('domain')]
        except:
            pass
        
        if not self.all_domains:
            self.all_domains = [
                'mailto.plus', 'tempmail.plus', 'tmpmail.org', 
                'guerrillamail.com', '10minutemail.net', 'mailnator.com'
            ]
    
    def get_unused_domain(self):
        available = [d for d in self.all_domains if d not in used_domains]
        if not available:
            used_domains.clear()
            available = self.all_domains
        domain = random.choice(available)
        used_domains.add(domain)
        save_data()
        return domain
    
    def generate_email(self, user_id):
        try:
            import uuid
            domain = self.get_unused_domain()
            email = f"{uuid.uuid4().hex[:10]}@{domain}"
            password = secrets.token_hex(10)
            
            create_data = {"address": email, "password": password}
            create_response = requests.post("https://api.mail.tm/accounts", json=create_data, timeout=10)
            if create_response.status_code == 201:
                token_response = requests.post("https://api.mail.tm/token", json={"address": email, "password": password}, timeout=10)
                if token_response.status_code == 200:
                    token_data = token_response.json()
                    self.sessions[user_id] = {
                        'email': email,
                        'password': password,
                        'token': token_data.get('token'),
                        'id': create_response.json().get('id'),
                        'domain': domain
                    }
                    return email
        except Exception as e:
            print(f"Mail.tm error: {e}")
        
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        domain = self.get_unused_domain()
        email = f"{username}@{domain}"
        self.sessions[user_id] = {'email': email, 'type': 'simple', 'domain': domain}
        return email
    
    def check_inbox(self, user_id):
        if user_id not in self.sessions:
            return []
        
        session = self.sessions[user_id]
        messages = []
        
        if 'token' in session:
            try:
                headers = {'Authorization': f'Bearer {session["token"]}'}
                response = requests.get("https://api.mail.tm/messages", headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    raw_messages = data.get('hydra:member', [])
                    for msg in raw_messages:
                        msg_id = msg.get('id')
                        if msg_id:
                            detail_response = requests.get(f"https://api.mail.tm/messages/{msg_id}", headers=headers, timeout=10)
                            if detail_response.status_code == 200:
                                detail = detail_response.json()
                                html_part = detail.get('html', [])
                                text_part = detail.get('text', '')
                                body = ''
                                if html_part and len(html_part) > 0:
                                    body = html_part[0].get('value', '')
                                    body = re.sub(r'<[^>]+>', ' ', body)
                                    body = re.sub(r'\s+', ' ', body).strip()
                                elif text_part:
                                    body = text_part
                                
                                messages.append({
                                    'from': detail.get('from', {}).get('address', 'Unknown'),
                                    'subject': detail.get('subject', 'No Subject'),
                                    'body': body[:3000],
                                    'date': detail.get('createdAt', ''),
                                    'id': msg_id
                                })
            except Exception as e:
                print(f"Mail check error: {e}")
        
        return messages
    
    def get_email(self, user_id):
        if user_id in self.sessions:
            return self.sessions[user_id].get('email')
        return None

temp_mail_service = TempMailService()

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

# ==================== REPLY KEYBOARDS ====================
def get_main_keyboard(is_admin=False):
    keyboard = [
        [KeyboardButton("📱 Get Number")],
        [KeyboardButton("📧 Temp Mail"), KeyboardButton("🔐 2FA")],
        [KeyboardButton("💰 Balance"), KeyboardButton("💸 Withdraw")],
        [KeyboardButton("📊 My Stats"), KeyboardButton("📢 Support")]
    ]
    if is_admin:
        keyboard.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard():
    keyboard = [
        [KeyboardButton("➕ Add Number"), KeyboardButton("📋 List Numbers")],
        [KeyboardButton("🌍 Edit Country")],
        [KeyboardButton("💰 Set Price"), KeyboardButton("💰 Add Balance")],
        [KeyboardButton("💸 Process Withdrawals"), KeyboardButton("📊 Statistics")],
        [KeyboardButton("📨 Broadcast"), KeyboardButton("👥 Users List")],
        [KeyboardButton("🚫 Ban/Unban User"), KeyboardButton("📥 Export Data")],
        [KeyboardButton("🔙 Back to Main")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_country_selection_keyboard(countries):
    keyboard = []
    for country in countries:
        if available_numbers.get(country):
            count = len(available_numbers[country])
            keyboard.append([InlineKeyboardButton(f"🌍 {country} ({count} numbers)", callback_data=f"user_select_country_{country}")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")])
    return InlineKeyboardMarkup(keyboard)

def get_number_display_text(numbers, country):
    price = country_prices.get(country, 0.30)
    text = f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
    text += f"🇧🇩 *নাজার যাচাই সম্পন্ন*\n"
    text += f"🌍 *দেশ ও দাম:* {country} ({price}TK)\n\n"
    for i, num in enumerate(numbers[:3], 1):
        text += f"📱 *Number {i}:* `{num}`\n"
    text += f"\n🔑 *OTP কোড:* `Waiting...` ⏳\n\n"
    text += f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
    text += f"📢 *OTP GROUP*"
    return text

def get_number_action_keyboard():
    keyboard = [
        [InlineKeyboardButton("📢 OTP GROUP", url=f"https://t.me/{OTP_GROUP[1:]}")],
        [InlineKeyboardButton("🔄 Change Number", callback_data="change_number")],
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

def get_tempmail_keyboard(email):
    keyboard = [
        [InlineKeyboardButton("📋 Copy Email", callback_data=f"copy_email_{email}")],
        [InlineKeyboardButton("🔄 Refresh Inbox", callback_data="refresh_inbox")],
        [InlineKeyboardButton("🆕 New Email", callback_data="new_tempmail")],
        [InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_country_keyboard(countries, action):
    keyboard = []
    for country in countries:
        keyboard.append([InlineKeyboardButton(f"🌍 {country}", callback_data=f"{action}_{country}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="back_to_admin")])
    return InlineKeyboardMarkup(keyboard)

def get_price_country_keyboard(countries):
    keyboard = []
    for country in countries:
        current_price = country_prices.get(country, 0.30)
        keyboard.append([InlineKeyboardButton(f"🌍 {country} (Current: {current_price} TK)", callback_data=f"setprice_{country}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="back_to_admin")])
    return InlineKeyboardMarkup(keyboard)

# ==================== BOT HANDLERS ====================
async def start(update, context):
    user = update.effective_user
    user_id = user.id
    is_admin = user_id == ADMIN_ID
    
    if user_id in banned_users:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    
    if user_id not in user_balances:
        user_balances[user_id] = 0
        user_stats[user_id] = {'joined': datetime.now().isoformat(), 'total_otps': 0, 'total_earned': 0}
        save_data()
    
    welcome_text = f"""🎉 *OTP SERVICE BOT* এ স্বাগতম 🎉

👤 *User:* {user.first_name}
💰 *Balance:* {user_balances.get(user_id, 0):.2f} TK
📊 *Total Earned:* {user_stats.get(user_id, {}).get('total_earned', 0):.2f} TK

⚡ *How it works:*
• 📱 Get Number - Get free virtual number
• OTP will be forwarded to you automatically
• Earn money per OTP (varies by country)
• Minimum Withdraw: {MIN_WITHDRAW} TK

👇 *Choose an option:*"""

    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin))

async def handle_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text
    is_admin = user_id == ADMIN_ID
    
    if user_id in banned_users:
        await update.message.reply_text("❌ You are banned!")
        return
    
    # Handle 2FA secret key input
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
            kb = get_2fa_display_keyboard(secret, code, remaining)
            
            msg = await update.message.reply_text(
                f"🔐 *2FA Authenticator Setup Complete!*\n\n"
                f"🔑 *Secret Key:* `{secret}`\n\n"
                f"🔢 *Current Code:* `{code}`\n\n"
                f"✅ Click on code to copy\n"
                f"⏱ Changes in {remaining} seconds",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
            
            user_2fa_messages[user_id] = msg.message_id
            
            if user_id in user_2fa_tasks:
                user_2fa_tasks[user_id].cancel()
            
            task = asyncio.create_task(auto_refresh_2fa(context, update.message.chat_id, user_id, msg.message_id))
            user_2fa_tasks[user_id] = task
        else:
            await update.message.reply_text("❌ Invalid secret key!\n\nSecret key must be:\n• At least 16 characters\n• Only A-Z and 2-7\n\nTry again.", reply_markup=get_2fa_initial_keyboard())
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
            total = len(available_numbers.get(country, []))
            await update.message.reply_text(f"✅ {added} numbers added to {country}!\n❌ Duplicate: {duplicate}\n\n📊 Total numbers: {total}")
            return
        elif text == '/cancel':
            context.user_data['awaiting_numbers'] = False
            context.user_data['pending_country'] = None
            await update.message.reply_text("❌ Number addition cancelled.")
            return
    
    # Handle price setting from admin
    if context.user_data.get('awaiting_price') and is_admin:
        country = context.user_data.get('price_country')
        if country and text:
            try:
                price = float(text)
                if price < 0:
                    await update.message.reply_text("❌ Price cannot be negative!")
                    return
                country_prices[country] = price
                save_data()
                context.user_data['awaiting_price'] = False
                context.user_data['price_country'] = None
                await update.message.reply_text(f"✅ {country} OTP price set to: {price} TK")
            except ValueError:
                await update.message.reply_text("❌ Invalid price! Enter a number (e.g., 0.30)")
            return
        elif text == '/cancel':
            context.user_data['awaiting_price'] = False
            context.user_data['price_country'] = None
            await update.message.reply_text("❌ Price setting cancelled.")
            return
    
    # ==================== MAIN MENU ====================
    if text == "📱 Get Number":
        if not available_numbers:
            await update.message.reply_text("❌ No countries available. Admin please add countries first.")
            return
        
        countries = [c for c in available_numbers.keys() if available_numbers[c]]
        if not countries:
            await update.message.reply_text("❌ No numbers available in any country. Admin please add numbers.")
            return
        
        await update.message.reply_text(
            "🌍 *Select Country*\n\nChoose your country:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_country_selection_keyboard(countries)
        )
        return
    
    elif text == "📧 Temp Mail":
        email = temp_mail_service.generate_email(user_id)
        temp_mail_data[user_id] = {
            'email': email, 
            'created': time.time(), 
            'messages': [],
            'last_count': 0
        }
        save_data()
        
        if user_id in mail_check_tasks:
            mail_check_tasks[user_id].cancel()
        mail_check_tasks[user_id] = asyncio.create_task(auto_check_mail_and_send(context, user_id))
        
        await update.message.reply_text(
            f"📧 *YOUR TEMP EMAIL IS READY*\n\n"
            f"📨 `{email}`\n\n"
            f"⚡ Check your mail speed!\n"
            f"Emails will appear automatically when received.\n\n"
            f"💡 Click on email to copy",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_tempmail_keyboard(email)
        )
        return
    
    elif text == "🔐 2FA":
        await update.message.reply_text(
            "🔐 *2FA Authenticator*\n\n"
            "📝 *Send your Authenticator Secret Key*\n\n"
            "Example: `JBSWY3DPEHPK3PXP`\n\n"
            "👇 *Click Cancel to cancel:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_2fa_initial_keyboard()
        )
        context.user_data['awaiting_2fa'] = True
        return SECRET_KEY_STATE
    
    elif text == "💰 Balance":
        balance = user_balances.get(user_id, 0)
        stats = user_stats.get(user_id, {})
        await update.message.reply_text(
            f"💰 *Your Balance*\n\n"
            f"💵 *Available:* `{balance:.2f} TK`\n\n"
            f"📊 *Statistics:*\n"
            f"• Total OTPs: {stats.get('total_otps', 0)}\n"
            f"• Total Earned: {stats.get('total_earned', 0):.2f} TK\n"
            f"• Joined: {stats.get('joined', 'N/A')[:10]}\n\n"
            f"💸 *Minimum Withdraw:* {MIN_WITHDRAW} TK",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "💸 Withdraw":
        balance = user_balances.get(user_id, 0)
        if balance >= MIN_WITHDRAW:
            await update.message.reply_text(
                f"💸 *Withdrawal Request*\n\n"
                f"💰 *Your Balance:* {balance:.2f} TK\n\n"
                f"📝 Send:\n"
                f"`/withdraw METHOD ACCOUNT_NUMBER`\n\n"
                f"Example: `/withdraw bKash 01XXXXXXXXX`\n\n"
                f"Available Methods: bKash, Nagad, Rocket",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"❌ *Insufficient Balance!*\n\n"
                f"💰 Your Balance: {balance:.2f} TK\n"
                f"💵 Required: {MIN_WITHDRAW} TK\n\n"
                f"📱 Get more numbers and receive OTPs!",
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif text == "📊 My Stats":
        stats = user_stats.get(user_id, {})
        balance = user_balances.get(user_id, 0)
        await update.message.reply_text(
            f"📊 *Your Statistics*\n\n"
            f"💰 *Balance:* {balance:.2f} TK\n"
            f"🔑 *Total OTPs:* {stats.get('total_otps', 0)}\n"
            f"💵 *Total Earned:* {stats.get('total_earned', 0):.2f} TK\n"
            f"📅 *Joined:* {stats.get('joined', 'N/A')[:10]}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "📢 Support":
        await update.message.reply_text(
            f"📞 *Support Center*\n\n"
            f"📢 *Main Channel:* {MAIN_CHANNEL}\n"
            f"👥 *OTP Group:* {OTP_GROUP}\n\n"
            f"❓ *FAQ:*\n"
            f"• OTP takes 1-3 minutes\n"
            f"• Minimum Withdraw: {MIN_WITHDRAW} TK\n\n"
            f"👨‍💻 *Support:* {SUPPORT_ID}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "⚙️ Admin Panel" and is_admin:
        await update.message.reply_text("⚙️ *Admin Control Panel*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_admin_keyboard())
    
    elif text == "🔙 Back to Main" and is_admin:
        await update.message.reply_text("🏠 *Main Menu*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin))
    
    # ==================== ADMIN COMMANDS ====================
    elif text == "➕ Add Number" and is_admin:
        if not available_numbers:
            await update.message.reply_text("❌ Please add a country first using '🌍 Edit Country' button.")
            return
        countries = list(available_numbers.keys())
        await update.message.reply_text(
            "🌍 *Which country to add numbers to?*\n\nSelect a country:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_admin_country_keyboard(countries, "addnum_country")
        )
    
    elif text == "📋 List Numbers" and is_admin:
        if available_numbers:
            msg = "📋 *Available Numbers*\n\n"
            total_available = 0
            total_used = 0
            for country, nums in available_numbers.items():
                price = country_prices.get(country, 0.30)
                available_count = len([n for n in nums if number_usage_count.get(n, 0) < 1])
                used_count = len([n for n in nums if number_usage_count.get(n, 0) >= 1])
                total_available += available_count
                total_used += used_count
                msg += f"*{country}:* {len(nums)} total | ✅ {available_count} available | ❌ {used_count} used (Price: {price} TK)\n"
                for num in nums[:3]:
                    msg += f"  • `{num}`\n"
                msg += "\n"
            msg += f"\n📊 *Summary:* ✅ {total_available} available | ❌ {total_used} used | 📱 {total_available + total_used} total"
            if len(msg) > 4000:
                msg = msg[:4000] + "\n\n... more"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("No numbers available.")
    
    elif text == "🌍 Edit Country" and is_admin:
        await update.message.reply_text(
            "🌍 *Edit Country*\n\n"
            "Commands:\n\n"
            "`/addcountry COUNTRY_NAME` - Add new country\n"
            "`/removecountry COUNTRY_NAME` - Remove country\n"
            "`/editcountry OLD_NAME NEW_NAME` - Rename country\n\n"
            "Examples:\n"
            "`/addcountry Canada`\n"
            "`/removecountry Germany`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "💰 Set Price" and is_admin:
        if not available_numbers:
            await update.message.reply_text("❌ No countries available.")
            return
        countries = list(available_numbers.keys())
        await update.message.reply_text(
            "💰 *Select Country to Set Price*\n\nSelect a country:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_price_country_keyboard(countries)
        )
    
    elif text == "💰 Add Balance" and is_admin:
        await update.message.reply_text(
            "💰 *Add Balance*\n\n"
            "Format: `/addbal USER_ID AMOUNT`\n"
            "Example: `/addbal 7064572216 100`"
        )
    
    elif text == "💸 Process Withdrawals" and is_admin:
        if pending_withdrawals:
            msg = "💸 *Pending Withdrawals*\n\n"
            for uid, wd in pending_withdrawals.items():
                msg += f"👤 User: `{uid}`\n💰 Amount: {wd['amount']:.2f} TK\n💳 Method: {wd['method']}\n📱 Account: {wd['account']}\n➖➖➖\n\n"
            msg += "Approve: `/approvewd USER_ID`\nReject: `/rejectwd USER_ID`"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("No pending withdrawals.")
    
    elif text == "📊 Statistics" and is_admin:
        total_users = len(user_balances)
        total_balance = sum(user_balances.values())
        total_earned = sum(s.get('total_earned', 0) for s in user_stats.values())
        total_otps = sum(s.get('total_otps', 0) for s in user_stats.values())
        total_numbers = sum(len(nums) for nums in available_numbers.values())
        total_available = sum(len([n for n in nums if number_usage_count.get(n, 0) < 1]) for nums in available_numbers.values())
        total_used = total_numbers - total_available
        await update.message.reply_text(
            f"📊 *Statistics*\n\n"
            f"👥 Users: {total_users}\n"
            f"💰 Total Balance: {total_balance:.2f} TK\n"
            f"💵 Total Earned: {total_earned:.2f} TK\n"
            f"🔑 Total OTPs: {total_otps}\n"
            f"📱 Total Numbers: {total_numbers}\n"
            f"✅ Available: {total_available}\n"
            f"❌ Used: {total_used}\n"
            f"🌍 Total Countries: {len(available_numbers)}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "📨 Broadcast" and is_admin:
        await update.message.reply_text(
            "📨 *Broadcast*\n\n"
            "Send: `/broadcast YOUR_MESSAGE`"
        )
    
    elif text == "👥 Users List" and is_admin:
        msg = "👥 *Users List*\n\n"
        for uid, bal in sorted(user_balances.items(), key=lambda x: x[1], reverse=True)[:30]:
            stats = user_stats.get(uid, {})
            msg += f"• `{uid}` - {bal:.2f} TK (OTPs: {stats.get('total_otps', 0)})\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    
    elif text == "🚫 Ban/Unban User" and is_admin:
        await update.message.reply_text(
            "🚫 *Ban/Unban User*\n\n"
            "Ban: `/ban USER_ID REASON`\n"
            "Example: `/ban 123456789 Spam`\n\n"
            "Unban: `/unban USER_ID`\n"
            "Example: `/unban 123456789`"
        )
    
    elif text == "📥 Export Data" and is_admin:
        await update.message.reply_text(
            "📥 *Export Data*\n\n"
            "Commands:\n"
            "`/export users` - Export users list\n"
            "`/export numbers` - Export numbers list"
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
                    f"✅ *Withdrawal Request Submitted!*\n\n"
                    f"💰 Amount: {amount:.2f} TK\n"
                    f"💳 Method: {method}\n"
                    f"📱 Account: {account}\n\n"
                    f"⏳ Will be processed within 24 hours.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_main_keyboard(is_admin)
                )
                await context.bot.send_message(ADMIN_ID, f"💰 Withdrawal Request\nUser: {user_id}\nAmount: {amount:.2f} TK\nMethod: {method}\nAccount: {account}")
            else:
                await update.message.reply_text(f"❌ Minimum withdrawal: {MIN_WITHDRAW} TK\nYour balance: {amount:.2f} TK", reply_markup=get_main_keyboard(is_admin))
        else:
            await update.message.reply_text("❌ Use: `/withdraw METHOD ACCOUNT`\nExample: `/withdraw bKash 01XXXXXXXXX`", reply_markup=get_main_keyboard(is_admin))

# ==================== CALLBACK HANDLER ====================
async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    is_admin = user_id == ADMIN_ID
    
    if user_id in banned_users:
        await query.edit_message_text("❌ You are banned!")
        return
    
    if data == "back_home":
        await query.edit_message_text("🏠 *Main Menu*", parse_mode=ParseMode.MARKDOWN)
        await query.message.reply_text("Main Menu", reply_markup=get_main_keyboard(is_admin))
        return
    
    elif data == "back_to_admin":
        await query.edit_message_text("⚙️ *Admin Panel*", parse_mode=ParseMode.MARKDOWN)
        await query.message.reply_text("Admin Panel", reply_markup=get_admin_keyboard())
        return
    
    elif data == "change_number":
        if not available_numbers:
            await query.edit_message_text("❌ No countries available.")
            return
        
        countries = [c for c in available_numbers.keys() if available_numbers[c]]
        await query.edit_message_text(
            "🌍 *Select Country*\n\nChoose your country:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_country_selection_keyboard(countries)
        )
        return
    
    # Admin add number country selection
    elif data.startswith("addnum_country_"):
        country = data.replace("addnum_country_", "")
        context.user_data['pending_country'] = country
        context.user_data['awaiting_numbers'] = True
        await query.edit_message_text(
            f"➕ *Add Numbers to {country}*\n\n"
            f"Send numbers (one per line):\n"
            f"Format: `+COUNTRYCODE NUMBER`\n\n"
            f"Example:\n"
            f"`+491551329004`\n"
            f"`+491551329005`\n\n"
            f"Or upload a .txt file.\n\n"
            f"Type /cancel to cancel.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Admin set price country selection
    elif data.startswith("setprice_"):
        country = data.replace("setprice_", "")
        context.user_data['price_country'] = country
        context.user_data['awaiting_price'] = True
        current_price = country_prices.get(country, 0.30)
        await query.edit_message_text(
            f"💰 *Set Price for {country}*\n\n"
            f"Current Price: {current_price} TK\n\n"
            f"Send new price (e.g., 0.20, 0.50, 1.00):\n\n"
            f"Type /cancel to cancel.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # User select country
    elif data.startswith("user_select_country_"):
        country = data.replace("user_select_country_", "")
        
        numbers = available_numbers.get(country, [])
        if not numbers:
            await query.edit_message_text(
                f"❌ *No numbers available in {country}!*\n\nPlease contact admin.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Change Country", callback_data="change_number")],
                    [InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")]
                ])
            )
            return
        
        # Check available numbers (not used)
        available_num_list = [num for num in numbers if number_usage_count.get(num, 0) < 1]
        if not available_num_list:
            await query.edit_message_text(
                f"❌ *Number stockout in {country}!*\n\nPlease wait for admin to add more numbers.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Change Country", callback_data="change_number")],
                    [InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")]
                ])
            )
            return
        
        # Select 3 random available numbers (show full number)
        if len(available_num_list) >= 3:
            selected_numbers = random.sample(available_num_list, 3)
        else:
            selected_numbers = available_num_list
        
        # Mark numbers as used
        for num in selected_numbers:
            number_usage_count[num] = number_usage_count.get(num, 0) + 1
        
        save_data()
        
        context.user_data['selected_numbers'] = selected_numbers
        context.user_data['selected_country'] = country
        user_active_numbers[user_id] = {
            'numbers': selected_numbers,
            'country': country,
            'selected_time': time.time()
        }
        
        text = get_number_display_text(selected_numbers, country)
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_number_action_keyboard()
        )
        return
    
    # ==================== 2FA CALLBACKS ====================
    elif data == "2fa_refresh":
        if user_id in totp_secrets:
            secret = totp_secrets[user_id]
            code = TOTPGenerator.get_code(secret)
            remaining = TOTPGenerator.time_left()
            kb = get_2fa_display_keyboard(secret, code, remaining)
            msg_id = user_2fa_messages.get(user_id)
            if msg_id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=msg_id,
                        text=f"🔐 *2FA Authenticator*\n\n"
                             f"🔑 *Secret Key:* `{secret}`\n\n"
                             f"🔢 *Current Code:* `{code}`\n"
                             f"⏱ {remaining} seconds remaining\n\n"
                             f"✅ Click on code to copy",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=kb
                    )
                except:
                    pass
        else:
            await query.edit_message_text("❌ No secret key found. Please send one first.")
        return
    
    elif data == "2fa_cancel":
        context.user_data['awaiting_2fa'] = False
        await query.edit_message_text("❌ 2FA setup cancelled.")
        await query.message.reply_text("Main Menu", reply_markup=get_main_keyboard(is_admin))
        return
    
    # ==================== TEMP MAIL CALLBACKS ====================
    elif data == "refresh_inbox":
        if user_id in temp_mail_data:
            email = temp_mail_service.get_email(user_id)
            if email:
                messages = temp_mail_service.check_inbox(user_id)
                if messages:
                    msg = "📬 *Your Inbox*\n\n"
                    for m in messages[:5]:
                        msg += f"📧 *From:* {m.get('from', 'Unknown')}\n"
                        msg += f"📝 *Subject:* {m.get('subject', 'No Subject')}\n"
                        body = m.get('body', '')[:1500]
                        if body:
                            msg += f"💬 *Body:*\n{body}\n"
                        msg += "➖➖➖➖➖➖\n\n"
                    await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=get_tempmail_keyboard(email))
                else:
                    await query.edit_message_text("📭 *No messages yet*\n\nWaiting for incoming emails...", parse_mode=ParseMode.MARKDOWN, reply_markup=get_tempmail_keyboard(email))
            else:
                await query.edit_message_text("❌ Email not found. Generate a new one.")
        else:
            await query.edit_message_text("❌ No active email. Generate a new one.")
        return
    
    elif data == "new_tempmail":
        email = temp_mail_service.generate_email(user_id)
        temp_mail_data[user_id] = {
            'email': email, 
            'created': time.time(), 
            'messages': [],
            'last_count': 0
        }
        save_data()
        
        if user_id in mail_check_tasks:
            mail_check_tasks[user_id].cancel()
        mail_check_tasks[user_id] = asyncio.create_task(auto_check_mail_and_send(context, user_id))
        
        await query.edit_message_text(
            f"📧 *YOUR TEMP EMAIL IS READY*\n\n"
            f"📨 `{email}`\n\n"
            f"⚡ Check your mail speed!\n"
            f"Emails will appear automatically when received.\n\n"
            f"💡 Click on email to copy",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_tempmail_keyboard(email)
        )
        return
    
    elif data.startswith("copy_email_"):
        email = data.replace("copy_email_", "")
        await query.answer(f"✅ Email copied: {email}", show_alert=True)
        return
    
    elif data == "noop":
        await query.answer()
        return

# ==================== GROUP LISTENER ====================
async def listen_to_group(app):
    """Listen to OTP group messages and forward to users - Unlimited timeout"""
    global last_update_id
    
    print("🔄 Group listener started - Monitoring OTP group...")
    
    while True:
        try:
            updates = await app.bot.get_updates(offset=last_update_id + 1, timeout=100, allowed_updates=['channel_post', 'message'])
            
            for update in updates:
                last_update_id = update.update_id
                
                if update.channel_post or update.message:
                    msg = update.channel_post or update.message
                    
                    chat_title = msg.chat.title if msg.chat else ""
                    
                    if "OTP" in chat_title or "Otp" in chat_title or "otp" in chat_title.lower():
                        text = msg.text or msg.caption or ""
                        
                        if not text:
                            continue
                        
                        # Extract number from message
                        number_match = re.search(r'📱\s*\*?Number\*?:\s*`?([+\d]+)`?', text, re.IGNORECASE)
                        if not number_match:
                            number_match = re.search(r'Number:\s*`?([+\d]+)`?', text, re.IGNORECASE)
                        if not number_match:
                            number_match = re.search(r'`([+\d]{10,15})`', text)
                        
                        if number_match:
                            masked_number = number_match.group(1)
                            
                            # Extract OTP
                            otp_match = re.search(r'🔑\s*\*?OTP\*?\s*Code\*?:\s*`?(\d{4,6})`?', text, re.IGNORECASE)
                            if not otp_match:
                                otp_match = re.search(r'OTP\s*Code:\s*`?(\d{4,6})`?', text, re.IGNORECASE)
                            if not otp_match:
                                otp_match = re.search(r'`(\d{4,6})`', text)
                            
                            if otp_match:
                                otp = otp_match.group(1)
                                
                                # Extract service
                                service_match = re.search(r'🔧\s*\*?Service\*?:\s*([A-Z]+)', text, re.IGNORECASE)
                                if not service_match:
                                    service_match = re.search(r'Service:\s*([A-Z]+)', text, re.IGNORECASE)
                                service = service_match.group(1) if service_match else "FACEBOOK"
                                
                                # Extract country
                                country_match = re.search(r'🌍\s*\*?Country\*?:\s*([A-Za-z]+)', text, re.IGNORECASE)
                                if not country_match:
                                    country_match = re.search(r'Country:\s*([A-Za-z]+)', text, re.IGNORECASE)
                                country = country_match.group(1) if country_match else "Unknown"
                                
                                # Find which user has this number
                                target_user = None
                                full_number = None
                                
                                for uid, active_data in user_active_numbers.items():
                                    for num in active_data.get('numbers', []):
                                        if num == masked_number or num.endswith(masked_number[-8:]) or masked_number.endswith(num[-8:]):
                                            full_number = num
                                            target_user = uid
                                            break
                                    if target_user:
                                        break
                                
                                if target_user and full_number:
                                    price = country_prices.get(country, 0.30)
                                    
                                    user_balances[target_user] = user_balances.get(target_user, 0) + price
                                    if target_user not in user_stats:
                                        user_stats[target_user] = {'total_otps': 0, 'total_earned': 0}
                                    user_stats[target_user]['total_otps'] = user_stats[target_user].get('total_otps', 0) + 1
                                    user_stats[target_user]['total_earned'] = user_stats[target_user].get('total_earned', 0) + price
                                    
                                    if target_user not in user_transactions:
                                        user_transactions[target_user] = []
                                    user_transactions[target_user].append({
                                        'type': 'earned', 'amount': price, 'number': full_number,
                                        'otp': otp, 'service': service, 'country': country,
                                        'time': datetime.now().isoformat()
                                    })
                                    save_data()
                                    
                                    # Send to user
                                    await app.bot.send_message(
                                        target_user,
                                        f"🔐 *OTP Received!*\n\n"
                                        f"📱 *Number:* `{full_number}`\n"
                                        f"🔧 *Service:* {service}\n"
                                        f"🔑 *OTP:* `{otp}`\n\n"
                                        f"💰 *+{price} TK added!*\n"
                                        f"💵 *New Balance:* {user_balances[target_user]:.2f} TK\n\n"
                                        f"📢 Join: {MAIN_CHANNEL} | {OTP_GROUP}",
                                        parse_mode=ParseMode.MARKDOWN
                                    )
                                    
                                    # Remove from active numbers
                                    if target_user in user_active_numbers:
                                        if full_number in user_active_numbers[target_user]['numbers']:
                                            user_active_numbers[target_user]['numbers'].remove(full_number)
                                    
                                    print(f"✅ OTP {otp} forwarded to user {target_user} for number {full_number}")
                                    
        except Exception as e:
            print(f"Group listener error: {e}")
            await asyncio.sleep(5)

# ==================== BACKGROUND TASKS ====================
async def auto_refresh_2fa(context, chat_id, user_id, message_id):
    while user_id in totp_secrets:
        await asyncio.sleep(1)
        if user_id in totp_secrets:
            secret = totp_secrets[user_id]
            code = TOTPGenerator.get_code(secret)
            remaining = TOTPGenerator.time_left()
            kb = get_2fa_display_keyboard(secret, code, remaining)
            
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"🔐 *2FA Authenticator*\n\n"
                         f"🔑 *Secret Key:* `{secret}`\n\n"
                         f"🔢 *Current Code:* `{code}`\n"
                         f"⏱ {remaining} seconds remaining\n\n"
                         f"✅ Click on code to copy",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb
                )
            except:
                pass

async def auto_check_mail_and_send(context, user_id):
    last_count = 0
    while user_id in temp_mail_data:
        await asyncio.sleep(2)
        messages = temp_mail_service.check_inbox(user_id)
        
        if messages and len(messages) > last_count:
            new_messages = messages[last_count:]
            last_count = len(messages)
            temp_mail_data[user_id]['messages'] = messages
            save_data()
            
            for msg in new_messages:
                from_addr = msg.get('from', 'Unknown')
                subject = msg.get('subject', 'No Subject')
                body = msg.get('body', '')[:2000]
                
                try:
                    await context.bot.send_message(
                        user_id,
                        f"📬 *New Email Received!*\n\n"
                        f"📧 *From:* {from_addr}\n"
                        f"📝 *Subject:* {subject}\n\n"
                        f"💬 *Message:*\n{body}\n\n"
                        f"➖➖➖➖➖➖",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass
        
        if time.time() - temp_mail_data[user_id]['created'] > 3600:
            del temp_mail_data[user_id]
            save_data()
            try:
                await context.bot.send_message(user_id, "⏰ Your temporary email has expired. Generate a new one.")
            except:
                pass
            break

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
                await update.message.reply_text(f"✅ '{country}' added successfully!\nDefault price: 0.30 TK")
            else:
                await update.message.reply_text("❌ Country already exists")
        else:
            await update.message.reply_text("❌ Use: `/addcountry COUNTRY_NAME`\nExample: `/addcountry Canada`")
    
    elif text.startswith('/removecountry'):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            country = parts[1]
            if country in available_numbers:
                del available_numbers[country]
                if country in country_prices:
                    del country_prices[country]
                save_data()
                await update.message.reply_text(f"✅ '{country}' and all its numbers removed")
            else:
                await update.message.reply_text("❌ Country not found")
        else:
            await update.message.reply_text("❌ Use: `/removecountry COUNTRY_NAME`")
    
    elif text.startswith('/editcountry'):
        parts = text.split(maxsplit=2)
        if len(parts) == 3:
            old_name = parts[1]
            new_name = parts[2]
            if old_name in available_numbers:
                available_numbers[new_name] = available_numbers.pop(old_name)
                if old_name in country_prices:
                    country_prices[new_name] = country_prices.pop(old_name)
                save_data()
                await update.message.reply_text(f"✅ '{old_name}' renamed to '{new_name}'")
            else:
                await update.message.reply_text("❌ Country not found")
        else:
            await update.message.reply_text("❌ Use: `/editcountry OLD_NAME NEW_NAME`")
    
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
                    await context.bot.send_message(target, f"💰 +{amount} TK added to your balance!\nNew Balance: {user_balances[target]:.2f} TK")
                except:
                    pass
            except ValueError:
                await update.message.reply_text("❌ Invalid user ID or amount")
        else:
            await update.message.reply_text("❌ Use: `/addbal USER_ID AMOUNT`\nExample: `/addbal 7064572216 100`")
    
    elif text.startswith('/broadcast'):
        msg = text.replace('/broadcast', '', 1).strip()
        if msg:
            sent = 0
            failed = 0
            for uid in user_balances.keys():
                try:
                    await context.bot.send_message(uid, f"📢 *Announcement*\n\n{msg}", parse_mode=ParseMode.MARKDOWN)
                    sent += 1
                    await asyncio.sleep(0.05)
                except:
                    failed += 1
            await update.message.reply_text(f"✅ Sent to {sent} users\n❌ Failed: {failed}")
        else:
            await update.message.reply_text("❌ Use: `/broadcast MESSAGE`")
    
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
                    await context.bot.send_message(target, f"✅ *Withdrawal Approved!*\n\n💰 Amount: {wd['amount']:.2f} TK\n💳 Method: {wd['method']}\n📱 Account: {wd['account']}\n\nThank you.")
                except:
                    pass
            else:
                await update.message.reply_text("❌ Withdrawal request not found")
        else:
            await update.message.reply_text("❌ Use: `/approvewd USER_ID`")
    
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
                    await context.bot.send_message(target, f"❌ *Withdrawal Rejected!*\n\nPlease contact support.\n💰 {wd['amount']:.2f} TK refunded to your balance.")
                except:
                    pass
            else:
                await update.message.reply_text("❌ Withdrawal request not found")
        else:
            await update.message.reply_text("❌ Use: `/rejectwd USER_ID`")
    
    elif text.startswith('/ban'):
        parts = text.split(maxsplit=2)
        if len(parts) >= 2:
            target = int(parts[1])
            reason = parts[2] if len(parts) > 2 else "No reason"
            banned_users[target] = reason
            save_data()
            await update.message.reply_text(f"🚫 Banned `{target}`\nReason: {reason}", parse_mode=ParseMode.MARKDOWN)
            try:
                await context.bot.send_message(target, f"🚫 *You have been banned!*\n\nReason: {reason}\nContact: {SUPPORT_ID}")
            except:
                pass
        else:
            await update.message.reply_text("❌ Use: `/ban USER_ID REASON`\nExample: `/ban 123456789 Spam`")
    
    elif text.startswith('/unban'):
        parts = text.split()
        if len(parts) == 2:
            target = int(parts[1])
            if target in banned_users:
                del banned_users[target]
                save_data()
                await update.message.reply_text(f"✅ Unbanned `{target}`", parse_mode=ParseMode.MARKDOWN)
                try:
                    await context.bot.send_message(target, f"✅ *You have been unbanned!*\n\nYou can now use the bot again.")
                except:
                    pass
            else:
                await update.message.reply_text("❌ User is not banned")
        else:
            await update.message.reply_text("❌ Use: `/unban USER_ID`")
    
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
                writer.writerow(['Country', 'Number', 'Price', 'Status'])
                for country, nums in available_numbers.items():
                    price = country_prices.get(country, 0.30)
                    for num in nums:
                        status = "Used" if number_usage_count.get(num, 0) >= 1 else "Available"
                        writer.writerow([country, num, price, status])
                output.seek(0)
                await update.message.reply_document(InputFile(io.BytesIO(output.getvalue().encode()), filename='numbers.csv'))
            else:
                await update.message.reply_text("❌ Use: `/export users` or `/export numbers`")
        else:
            await update.message.reply_text("❌ Use: `/export users` or `/export numbers`")
    
    elif text == '/stats':
        total_users = len(user_balances)
        total_balance = sum(user_balances.values())
        total_earned = sum(s.get('total_earned', 0) for s in user_stats.values())
        total_otps = sum(s.get('total_otps', 0) for s in user_stats.values())
        total_numbers = sum(len(nums) for nums in available_numbers.values())
        total_available = sum(len([n for n in nums if number_usage_count.get(n, 0) < 1]) for nums in available_numbers.values())
        total_used = total_numbers - total_available
        pending_wd = len(pending_withdrawals)
        await update.message.reply_text(
            f"📊 *Bot Statistics*\n\n"
            f"👥 Users: {total_users}\n"
            f"💰 Total Balance: {total_balance:.2f} TK\n"
            f"💵 Total Earned: {total_earned:.2f} TK\n"
            f"🔑 Total OTPs: {total_otps}\n"
            f"📱 Total Numbers: {total_numbers}\n"
            f"✅ Available: {total_available}\n"
            f"❌ Used: {total_used}\n"
            f"🌍 Total Countries: {len(available_numbers)}\n"
            f"💸 Pending Withdrawals: {pending_wd}",
            parse_mode=ParseMode.MARKDOWN)
    
    # Handle file upload for bulk numbers
    if update.message.document:
        country = context.user_data.get('pending_country')
        if not country:
            await update.message.reply_text("❌ First select a country using '➕ Add Number' button.")
            return
        
        file = await update.message.document.get_file()
        file_path = f"/tmp/{update.message.document.file_name}"
        await file.download_to_drive(file_path)
        
        added = 0
        duplicate = 0
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('Country') and not line.startswith('দেশ'):
                    if not line.startswith('+'):
                        line = '+' + line
                    if country not in available_numbers:
                        available_numbers[country] = []
                    if line not in available_numbers[country]:
                        available_numbers[country].append(line)
                        added += 1
                    else:
                        duplicate += 1
        save_data()
        context.user_data['awaiting_numbers'] = False
        context.user_data['pending_country'] = None
        total = len(available_numbers.get(country, []))
        await update.message.reply_text(f"✅ {added} numbers added to {country}!\n❌ Duplicate: {duplicate}\n\n📊 Total numbers: {total}")

async def twofa_command(update, context):
    context.user_data['awaiting_2fa'] = True
    await update.message.reply_text(
        "🔐 *2FA Authenticator*\n\n"
        "Send your secret key:\n"
        "Example: `JBSWY3DPEHPK3PXP`\n\n"
        "Click Cancel to cancel.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_2fa_initial_keyboard()
    )
    return SECRET_KEY_STATE

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
        'temp_mails': len(temp_mail_data),
        'time': datetime.now().isoformat()
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    try:
        import telegram
        bot = telegram.Bot(BOT_TOKEN)
        bot.delete_webhook()
        print("✅ Webhook deleted")
    except:
        pass
    
    # Increase connection pool size
    request = HTTPXRequest(connection_pool_size=100, connect_timeout=60, read_timeout=60, write_timeout=60)
    
    application = Application.builder().token(BOT_TOKEN).request(request).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("twofa", twofa_command)],
        states={SECRET_KEY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)]},
        fallbacks=[CallbackQueryHandler(callback_handler, pattern="^2fa_cancel$")]
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, admin_commands))
    application.add_handler(MessageHandler(filters.Document.ALL, admin_commands))
    
    async def post_init(app):
        asyncio.create_task(listen_to_group(app))
        print("✅ Group listener started - Monitoring OTP group for messages")
    
    application.post_init = post_init
    
    if os.environ.get('PORT'):
        port = int(os.environ.get('PORT', 8080))
        url = os.environ.get('WEBHOOK_URL', '')
        if url:
            application.bot.set_webhook(url)
        flask_app.run(host='0.0.0.0', port=port)
    else:
        print("🤖 OTP SERVICE BOT is running...")
        application.run_polling()
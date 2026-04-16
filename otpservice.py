# otp_service_bot.py - Complete Final Working Script
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
number_usage_count = {}
last_update_id = 0
application = None

# ==================== DATA PERSISTENCE ====================
def load_data():
    global user_balances, totp_secrets, available_numbers, pending_withdrawals
    global user_transactions, user_stats, temp_mail_data, banned_users, country_prices, number_usage_count
    
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
            'number_usage': number_usage_count
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
    
    def generate_email(self, user_id):
        try:
            import uuid
            response = requests.get("https://api.mail.tm/domains", timeout=10)
            if response.status_code == 200:
                domains = response.json().get('hydra:member', [])
                if domains:
                    domain = domains[0]['domain']
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
                                'token': token_data.get('token'),
                                'id': create_response.json().get('id')
                            }
                            return email
        except:
            pass
        
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        email = f"{username}@10minutemail.net"
        self.sessions[user_id] = {'email': email}
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
                                body = detail.get('text', '')
                                if not body:
                                    html_part = detail.get('html', [])
                                    if html_part:
                                        body = html_part[0].get('value', '')
                                        body = re.sub(r'<[^>]+>', ' ', body)
                                        body = re.sub(r'\s+', ' ', body).strip()
                                
                                messages.append({
                                    'from': detail.get('from', {}).get('address', 'Unknown'),
                                    'subject': detail.get('subject', 'No Subject'),
                                    'body': body[:2000],
                                    'date': detail.get('createdAt', '')
                                })
            except:
                pass
        
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
            keyboard.append([InlineKeyboardButton(f"🌍 {country} ({count} numbers)", callback_data=f"select_country_{country}")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_country_keyboard(countries):
    keyboard = []
    for country in countries:
        keyboard.append([InlineKeyboardButton(f"🌍 {country}", callback_data=f"admin_addnum_{country}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="back_to_admin")])
    return InlineKeyboardMarkup(keyboard)

def get_price_country_keyboard(countries):
    keyboard = []
    for country in countries:
        current_price = country_prices.get(country, 0.30)
        keyboard.append([InlineKeyboardButton(f"🌍 {country} (Current: {current_price} TK)", callback_data=f"setprice_{country}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="back_to_admin")])
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
        [InlineKeyboardButton(f"⏱ {remaining}s remaining", callback_data="refresh_2fa")],
        [InlineKeyboardButton("🏠 Back to Home", callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_2fa_initial_keyboard():
    keyboard = [
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_2fa")],
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

# ==================== BOT HANDLERS ====================
async def start(update, context):
    user = update.effective_user
    user_id = user.id
    is_admin = user_id == ADMIN_ID
    
    if user_id in banned_users:
        await update.message.reply_text("❌ You are banned!")
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
• Earn money per OTP
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
        secret = text.upper().replace(' ', '')
        if len(secret) >= 16 and re.match(r'^[A-Z2-7]+$', secret):
            totp_secrets[user_id] = secret
            save_data()
            context.user_data['awaiting_2fa'] = False
            
            code = TOTPGenerator.get_code(secret)
            remaining = TOTPGenerator.time_left()
            kb = get_2fa_display_keyboard(secret, code, remaining)
            
            await update.message.reply_text(
                f"🔐 *2FA Setup Complete!*\n\n"
                f"🔑 *Secret:* `{secret}`\n"
                f"🔢 *Code:* `{code}`\n"
                f"⏱ Changes in {remaining}s\n\n"
                f"📌 Click Refresh for new code",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
        else:
            await update.message.reply_text("❌ Invalid secret key! Send correct key or click Cancel.", reply_markup=get_2fa_initial_keyboard())
        return
    
    # Handle number addition from admin
    if context.user_data.get('awaiting_numbers') and is_admin:
        country = context.user_data.get('pending_country')
        if country and text and text != '/cancel':
            numbers = text.strip().split('\n')
            added = 0
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
            save_data()
            context.user_data['awaiting_numbers'] = False
            context.user_data['pending_country'] = None
            await update.message.reply_text(f"✅ {added} numbers added to {country}!")
            return
        elif text == '/cancel':
            context.user_data['awaiting_numbers'] = False
            context.user_data['pending_country'] = None
            await update.message.reply_text("❌ Cancelled.")
            return
    
    # Handle price setting from admin
    if context.user_data.get('awaiting_price') and is_admin:
        country = context.user_data.get('price_country')
        if country and text:
            try:
                price = float(text)
                country_prices[country] = price
                save_data()
                context.user_data['awaiting_price'] = False
                context.user_data['price_country'] = None
                await update.message.reply_text(f"✅ {country} price set to: {price} TK")
            except:
                await update.message.reply_text("❌ Invalid price! Send number like 0.30")
            return
    
    # ==================== MAIN MENU ====================
    if text == "📱 Get Number":
        if not available_numbers:
            await update.message.reply_text("❌ No countries available.")
            return
        
        countries = [c for c in available_numbers.keys() if available_numbers[c]]
        if not countries:
            await update.message.reply_text("❌ No numbers available.")
            return
        
        await update.message.reply_text(
            "🌍 *Select Country*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_country_selection_keyboard(countries)
        )
        return
    
    elif text == "📧 Temp Mail":
        email = temp_mail_service.generate_email(user_id)
        temp_mail_data[user_id] = {'email': email, 'created': time.time(), 'messages': []}
        save_data()
        
        if user_id in mail_check_tasks:
            mail_check_tasks[user_id].cancel()
        mail_check_tasks[user_id] = asyncio.create_task(auto_check_mail_and_send(context, user_id))
        
        await update.message.reply_text(
            f"📧 *Your Temp Email*\n\n📨 `{email}`\n\n💡 Click to copy",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_tempmail_keyboard(email)
        )
        return
    
    elif text == "🔐 2FA":
        await update.message.reply_text(
            "🔐 *2FA Authenticator*\n\n📝 *Send your Secret Key*\nExample: `JBSWY3DPEHPK3PXP`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_2fa_initial_keyboard()
        )
        context.user_data['awaiting_2fa'] = True
        return SECRET_KEY_STATE
    
    elif text == "💰 Balance":
        balance = user_balances.get(user_id, 0)
        stats = user_stats.get(user_id, {})
        await update.message.reply_text(
            f"💰 *Your Balance*\n\n💵 Available: `{balance:.2f} TK`\n🔑 Total OTPs: {stats.get('total_otps', 0)}\n💵 Total Earned: {stats.get('total_earned', 0):.2f} TK\n💸 Min Withdraw: {MIN_WITHDRAW} TK",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "💸 Withdraw":
        balance = user_balances.get(user_id, 0)
        if balance >= MIN_WITHDRAW:
            await update.message.reply_text(
                f"💸 *Withdraw*\n\nSend: `/withdraw METHOD NUMBER`\nExample: `/withdraw bKash 01XXXXXXXXX`",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(f"❌ Need {MIN_WITHDRAW} TK, you have {balance:.2f} TK")
    
    elif text == "📊 My Stats":
        stats = user_stats.get(user_id, {})
        balance = user_balances.get(user_id, 0)
        await update.message.reply_text(
            f"📊 *Your Stats*\n\n💰 Balance: {balance:.2f} TK\n🔑 OTPs: {stats.get('total_otps', 0)}\n💵 Earned: {stats.get('total_earned', 0):.2f} TK",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "📢 Support":
        await update.message.reply_text(f"📞 *Support*\n\n📢 Channel: {MAIN_CHANNEL}\n👥 Group: {OTP_GROUP}\n👨‍💻 Admin: {SUPPORT_ID}", parse_mode=ParseMode.MARKDOWN)
    
    elif text == "⚙️ Admin Panel" and is_admin:
        await update.message.reply_text("⚙️ *Admin Panel*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_admin_keyboard())
    
    elif text == "🔙 Back to Main" and is_admin:
        await update.message.reply_text("🏠 *Main Menu*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(True))
    
    # ==================== ADMIN COMMANDS ====================
    elif text == "➕ Add Number" and is_admin:
        if not available_numbers:
            await update.message.reply_text("❌ Add a country first using /addcountry")
            return
        await update.message.reply_text(
            "🌍 *Select Country*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_admin_country_keyboard(list(available_numbers.keys()))
        )
    
    elif text == "📋 List Numbers" and is_admin:
        if available_numbers:
            msg = "📋 *Numbers*\n\n"
            for country, nums in available_numbers.items():
                price = country_prices.get(country, 0.30)
                available_count = len([n for n in nums if number_usage_count.get(n, 0) < 1])
                msg += f"*{country}:* {len(nums)} total | ✅ {available_count} avail | 💰 {price} TK\n"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("No numbers")
    
    elif text == "🌍 Edit Country" and is_admin:
        await update.message.reply_text(
            "🌍 *Edit Country*\n\n/addcountry NAME - Add\n/removecountry NAME - Remove\n/editcountry OLD NEW - Rename",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "💰 Set Price" and is_admin:
        if not available_numbers:
            await update.message.reply_text("❌ No countries")
            return
        await update.message.reply_text(
            "💰 *Select Country*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_price_country_keyboard(list(available_numbers.keys()))
        )
    
    elif text == "💰 Add Balance" and is_admin:
        await update.message.reply_text("💰 *Add Balance*\n/addbal USER_ID AMOUNT", parse_mode=ParseMode.MARKDOWN)
    
    elif text == "💸 Process Withdrawals" and is_admin:
        if pending_withdrawals:
            msg = "💸 *Pending*\n\n"
            for uid, wd in pending_withdrawals.items():
                msg += f"User: `{uid}` | {wd['amount']:.2f} TK | {wd['method']}\n"
            msg += "\n/approvewd USER_ID or /rejectwd USER_ID"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("No pending withdrawals")
    
    elif text == "📊 Statistics" and is_admin:
        await update.message.reply_text(
            f"📊 *Stats*\n\n👥 Users: {len(user_balances)}\n💰 Balance: {sum(user_balances.values()):.2f} TK\n🔑 OTPs: {sum(s.get('total_otps',0) for s in user_stats.values())}\n📱 Numbers: {sum(len(n) for n in available_numbers.values())}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "📨 Broadcast" and is_admin:
        await update.message.reply_text("📨 *Broadcast*\n/broadcast MESSAGE", parse_mode=ParseMode.MARKDOWN)
    
    elif text == "👥 Users List" and is_admin:
        msg = "👥 *Users*\n\n"
        for uid, bal in sorted(user_balances.items(), key=lambda x: x[1], reverse=True)[:20]:
            msg += f"• `{uid}` - {bal:.2f} TK\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    
    elif text == "🚫 Ban/Unban User" and is_admin:
        await update.message.reply_text("🚫 *Ban/Unban*\n/ban USER_ID REASON\n/unban USER_ID", parse_mode=ParseMode.MARKDOWN)
    
    elif text == "📥 Export Data" and is_admin:
        await update.message.reply_text("📥 *Export*\n/export users\n/export numbers", parse_mode=ParseMode.MARKDOWN)
    
    # Withdraw command
    if text.startswith('/withdraw'):
        parts = text.split()
        if len(parts) >= 3:
            method, account = parts[1], parts[2]
            amount = user_balances.get(user_id, 0)
            if amount >= MIN_WITHDRAW:
                pending_withdrawals[user_id] = {'amount': amount, 'method': method, 'account': account, 'time': datetime.now().isoformat()}
                user_balances[user_id] = 0
                save_data()
                await update.message.reply_text(f"✅ Withdrawal request submitted!\nAmount: {amount:.2f} TK")
                await context.bot.send_message(ADMIN_ID, f"💰 Withdraw\nUser: {user_id}\nAmount: {amount:.2f} TK\nMethod: {method}\nAccount: {account}")
            else:
                await update.message.reply_text(f"❌ Need {MIN_WITHDRAW} TK")

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
    
    # Home button
    if data == "back_home":
        await query.edit_message_text("🏠 *Main Menu*", parse_mode=ParseMode.MARKDOWN)
        await query.message.reply_text("Main Menu", reply_markup=get_main_keyboard(is_admin))
        return
    
    # Admin back
    elif data == "back_to_admin":
        await query.edit_message_text("⚙️ *Admin Panel*", parse_mode=ParseMode.MARKDOWN)
        await query.message.reply_text("Admin Panel", reply_markup=get_admin_keyboard())
        return
    
    # Change number
    elif data == "change_number":
        countries = [c for c in available_numbers.keys() if available_numbers[c]]
        await query.edit_message_text(
            "🌍 *Select Country*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_country_selection_keyboard(countries)
        )
        return
    
    # Select country for user
    elif data.startswith("select_country_"):
        country = data.replace("select_country_", "")
        numbers = available_numbers.get(country, [])
        available_nums = [n for n in numbers if number_usage_count.get(n, 0) < 1]
        
        if not available_nums:
            await query.edit_message_text(f"❌ No numbers in {country}!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="change_number")]]))
            return
        
        selected = random.sample(available_nums, min(3, len(available_nums)))
        for num in selected:
            number_usage_count[num] = number_usage_count.get(num, 0) + 1
        save_data()
        
        user_active_numbers[user_id] = {'numbers': selected, 'country': country}
        
        text = get_number_display_text(selected, country)
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_number_action_keyboard())
        return
    
    # Admin add number
    elif data.startswith("admin_addnum_"):
        country = data.replace("admin_addnum_", "")
        context.user_data['pending_country'] = country
        context.user_data['awaiting_numbers'] = True
        await query.edit_message_text(
            f"➕ *Add numbers to {country}*\n\nSend numbers (one per line):\nExample:\n+491551329004\n+491551329005\n\nType /cancel to cancel",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Admin set price
    elif data.startswith("setprice_"):
        country = data.replace("setprice_", "")
        context.user_data['price_country'] = country
        context.user_data['awaiting_price'] = True
        await query.edit_message_text(f"💰 *Set price for {country}*\n\nSend price (e.g., 0.30):", parse_mode=ParseMode.MARKDOWN)
        return
    
    # 2FA refresh
    elif data == "refresh_2fa":
        if user_id in totp_secrets:
            secret = totp_secrets[user_id]
            code = TOTPGenerator.get_code(secret)
            remaining = TOTPGenerator.time_left()
            kb = get_2fa_display_keyboard(secret, code, remaining)
            await query.edit_message_text(
                f"🔐 *2FA*\n\n🔑 Secret: `{secret}`\n🔢 Code: `{code}`\n⏱ {remaining}s left",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
        return
    
    # 2FA cancel
    elif data == "cancel_2fa":
        context.user_data['awaiting_2fa'] = False
        await query.edit_message_text("❌ 2FA setup cancelled.")
        await query.message.reply_text("Main Menu", reply_markup=get_main_keyboard(is_admin))
        return
    
    # Temp mail refresh
    elif data == "refresh_inbox":
        if user_id in temp_mail_data:
            email = temp_mail_service.get_email(user_id)
            if email:
                messages = temp_mail_service.check_inbox(user_id)
                if messages:
                    msg = "📬 *Inbox*\n\n"
                    for m in messages[:3]:
                        msg += f"📧 From: {m.get('from')}\n📝 Subject: {m.get('subject')}\n💬 {m.get('body', '')[:200]}\n➖➖➖\n\n"
                    await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=get_tempmail_keyboard(email))
                else:
                    await query.edit_message_text("📭 No messages", parse_mode=ParseMode.MARKDOWN, reply_markup=get_tempmail_keyboard(email))
        return
    
    elif data == "new_tempmail":
        email = temp_mail_service.generate_email(user_id)
        temp_mail_data[user_id] = {'email': email, 'created': time.time(), 'messages': []}
        save_data()
        await query.edit_message_text(f"📧 *New Email*\n\n📨 `{email}`", parse_mode=ParseMode.MARKDOWN, reply_markup=get_tempmail_keyboard(email))
        return
    
    elif data.startswith("copy_email_"):
        email = data.replace("copy_email_", "")
        await query.answer(f"✅ Copied: {email}", show_alert=True)
        return

# ==================== GROUP LISTENER ====================
async def listen_to_group(app):
    global last_update_id
    print("🔄 Group listener started...")
    
    while True:
        try:
            updates = await app.bot.get_updates(offset=last_update_id + 1, timeout=30)
            for update in updates:
                last_update_id = update.update_id
                
                if update.channel_post or update.message:
                    msg = update.channel_post or update.message
                    text = msg.text or msg.caption or ""
                    
                    if not text:
                        continue
                    
                    # Extract OTP
                    otp_match = re.search(r'\b(\d{4,6})\b', text)
                    if otp_match:
                        otp = otp_match.group(1)
                        
                        # Extract masked number
                        num_match = re.search(r'`([+\d\*]+)`', text)
                        if num_match:
                            masked = num_match.group(1)
                            
                            # Find user
                            for uid, active in user_active_numbers.items():
                                for num in active.get('numbers', []):
                                    if num[-8:] == masked[-8:] or masked[-8:] == num[-8:]:
                                        price = country_prices.get(active.get('country', 'Unknown'), 0.30)
                                        
                                        user_balances[uid] = user_balances.get(uid, 0) + price
                                        if uid not in user_stats:
                                            user_stats[uid] = {'total_otps': 0, 'total_earned': 0}
                                        user_stats[uid]['total_otps'] = user_stats[uid].get('total_otps', 0) + 1
                                        user_stats[uid]['total_earned'] = user_stats[uid].get('total_earned', 0) + price
                                        save_data()
                                        
                                        await app.bot.send_message(uid, f"🔐 *OTP Received!*\n\n📱 Number: `{num}`\n🔑 OTP: `{otp}`\n💰 +{price} TK added!", parse_mode=ParseMode.MARKDOWN)
                                        
                                        if uid in user_active_numbers:
                                            if num in user_active_numbers[uid]['numbers']:
                                                user_active_numbers[uid]['numbers'].remove(num)
                                        print(f"✅ OTP sent to user {uid}")
                                        break
        except:
            await asyncio.sleep(5)

# ==================== BACKGROUND TASKS ====================
async def auto_check_mail_and_send(context, user_id):
    last_count = 0
    while user_id in temp_mail_data:
        await asyncio.sleep(3)
        messages = temp_mail_service.check_inbox(user_id)
        if messages and len(messages) > last_count:
            last_count = len(messages)
            for msg in messages:
                await context.bot.send_message(
                    user_id,
                    f"📬 *New Email!*\n\n📧 From: {msg.get('from')}\n📝 Subject: {msg.get('subject')}\n💬 {msg.get('body', '')[:500]}",
                    parse_mode=ParseMode.MARKDOWN
                )
        if time.time() - temp_mail_data[user_id]['created'] > 3600:
            del temp_mail_data[user_id]
            save_data()
            break

# ==================== ADMIN COMMANDS ====================
async def admin_commands(update, context):
    user_id = update.effective_user.id
    text = update.message.text
    if user_id != ADMIN_ID:
        return
    
    if text.startswith('/addcountry'):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            country = parts[1]
            if country not in available_numbers:
                available_numbers[country] = []
                country_prices[country] = 0.30
                save_data()
                await update.message.reply_text(f"✅ '{country}' added")
            else:
                await update.message.reply_text("❌ Already exists")
    
    elif text.startswith('/removecountry'):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            country = parts[1]
            if country in available_numbers:
                del available_numbers[country]
                save_data()
                await update.message.reply_text(f"✅ '{country}' removed")
    
    elif text.startswith('/editcountry'):
        parts = text.split(maxsplit=2)
        if len(parts) == 3:
            old, new = parts[1], parts[2]
            if old in available_numbers:
                available_numbers[new] = available_numbers.pop(old)
                if old in country_prices:
                    country_prices[new] = country_prices.pop(old)
                save_data()
                await update.message.reply_text(f"✅ '{old}' renamed to '{new}'")
    
    elif text.startswith('/addbal'):
        parts = text.split()
        if len(parts) == 3:
            try:
                target, amount = int(parts[1]), float(parts[2])
                user_balances[target] = user_balances.get(target, 0) + amount
                save_data()
                await update.message.reply_text(f"✅ Added {amount} TK to `{target}`")
                await context.bot.send_message(target, f"💰 +{amount} TK added!")
            except:
                await update.message.reply_text("❌ Invalid")
    
    elif text.startswith('/broadcast'):
        msg = text.replace('/broadcast', '', 1).strip()
        if msg:
            sent = 0
            for uid in user_balances:
                try:
                    await context.bot.send_message(uid, f"📢 *Announcement*\n\n{msg}", parse_mode=ParseMode.MARKDOWN)
                    sent += 1
                    await asyncio.sleep(0.05)
                except:
                    pass
            await update.message.reply_text(f"✅ Sent to {sent} users")
    
    elif text.startswith('/approvewd'):
        parts = text.split()
        if len(parts) == 2:
            target = int(parts[1])
            if target in pending_withdrawals:
                del pending_withdrawals[target]
                save_data()
                await update.message.reply_text(f"✅ Approved `{target}`")
                await context.bot.send_message(target, "✅ Withdrawal approved!")
    
    elif text.startswith('/rejectwd'):
        parts = text.split()
        if len(parts) == 2:
            target = int(parts[1])
            if target in pending_withdrawals:
                wd = pending_withdrawals[target]
                del pending_withdrawals[target]
                user_balances[target] = user_balances.get(target, 0) + wd['amount']
                save_data()
                await update.message.reply_text(f"❌ Rejected `{target}`")
                await context.bot.send_message(target, "❌ Withdrawal rejected. Amount refunded.")
    
    elif text.startswith('/ban'):
        parts = text.split(maxsplit=2)
        if len(parts) >= 2:
            target = int(parts[1])
            reason = parts[2] if len(parts) > 2 else "No reason"
            banned_users[target] = reason
            save_data()
            await update.message.reply_text(f"🚫 Banned `{target}`")
            await context.bot.send_message(target, f"🚫 Banned!\nReason: {reason}")
    
    elif text.startswith('/unban'):
        parts = text.split()
        if len(parts) == 2:
            target = int(parts[1])
            if target in banned_users:
                del banned_users[target]
                save_data()
                await update.message.reply_text(f"✅ Unbanned `{target}`")
                await context.bot.send_message(target, "✅ You have been unbanned!")
    
    elif text.startswith('/export'):
        parts = text.split()
        if len(parts) == 2:
            if parts[1] == 'users':
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(['User ID', 'Balance', 'OTPs', 'Earned'])
                for uid in user_balances:
                    stats = user_stats.get(uid, {})
                    writer.writerow([uid, user_balances[uid], stats.get('total_otps', 0), stats.get('total_earned', 0)])
                output.seek(0)
                await update.message.reply_document(InputFile(io.BytesIO(output.getvalue().encode()), filename='users.csv'))
            elif parts[1] == 'numbers':
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(['Country', 'Number', 'Status'])
                for country, nums in available_numbers.items():
                    for num in nums:
                        status = "Used" if number_usage_count.get(num, 0) >= 1 else "Available"
                        writer.writerow([country, num, status])
                output.seek(0)
                await update.message.reply_document(InputFile(io.BytesIO(output.getvalue().encode()), filename='numbers.csv'))

async def twofa_command(update, context):
    context.user_data['awaiting_2fa'] = True
    await update.message.reply_text(
        "🔐 *2FA*\n\nSend your secret key:\nExample: `JBSWY3DPEHPK3PXP`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_2fa_initial_keyboard()
    )
    return SECRET_KEY_STATE

# ==================== FLASK ====================
@flask_app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        application.update_queue.put_nowait(update)
        return 'ok', 200
    except:
        return 'error', 500

@flask_app.route('/health')
def health():
    return jsonify({'status': 'alive', 'users': len(user_balances)})

# ==================== MAIN ====================
if __name__ == '__main__':
    application = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("twofa", twofa_command)],
        states={SECRET_KEY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)]},
        fallbacks=[CallbackQueryHandler(callback_handler, pattern="^cancel_2fa$")]
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, admin_commands))
    application.add_handler(MessageHandler(filters.Document.ALL, admin_commands))
    
    async def post_init(app):
        asyncio.create_task(listen_to_group(app))
        print("✅ Bot started!")
    
    application.post_init = post_init
    
    if os.environ.get('PORT'):
        flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
    else:
        print("🤖 Bot running...")
        application.run_polling()
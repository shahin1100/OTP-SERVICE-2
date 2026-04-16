# getpaid_otp_bot.py
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
import threading
import random
import string
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from bs4 import BeautifulSoup

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8343363851:AAHmFXkTjrubOpW3VdsZAhebvzfNyjNpJ10"
ADMIN_ID = 7064572216
BOT_USERNAME = "GetPaidOTP2Bot"
MAIN_CHANNEL = "@OtpService2C"
OTP_GROUP = "@OtpService2G"
WEB_BASE_URL = "http://139.99.9.4/ints"
WEB_LOGIN_URL = f"{WEB_BASE_URL}/login"
WEB_API_URL = f"{WEB_BASE_URL}/agent/SMSCDRStats"
WEB_USER = "Nazim1"
WEB_PASS = "Nazim1"

# Pricing
OTP_EARN_AMOUNT = 0.30  # User earns 0.30 TK per OTP received
OTP_COST_AMOUNT = 0.40  # User pays 0.40 TK to get number
MIN_WITHDRAW = 500  # Minimum 500 TK for withdrawal

# File paths
DATA_FILE = "bot_data.json"
NUMBERS_FILE = "numbers.json"
SESSION_FILE = "session.json"

# Flask app
flask_app = Flask(__name__)

# Global data structures
user_balances = {}
user_numbers = {}
active_orders = {}
totp_secrets = {}
available_numbers = {}
pending_withdrawals = {}
user_transactions = {}
user_stats = {}
temp_emails = {}
web_session = None
captcha_cache = {}

# ==================== DATA PERSISTENCE ====================
def load_data():
    global user_balances, user_numbers, totp_secrets, available_numbers, pending_withdrawals, user_transactions, user_stats, temp_emails
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            user_balances = data.get('balances', {})
            user_numbers = data.get('numbers', {})
            totp_secrets = data.get('totp', {})
            pending_withdrawals = data.get('withdrawals', {})
            user_transactions = data.get('transactions', {})
            user_stats = data.get('stats', {})
            temp_emails = data.get('temp_emails', {})
    except FileNotFoundError:
        pass
    
    try:
        with open(NUMBERS_FILE, 'r') as f:
            available_numbers = json.load(f)
    except FileNotFoundError:
        available_numbers = {}

def save_data():
    data = {
        'balances': user_balances,
        'numbers': user_numbers,
        'totp': totp_secrets,
        'withdrawals': pending_withdrawals,
        'transactions': user_transactions,
        'stats': user_stats,
        'temp_emails': temp_emails
    }
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    
    with open(NUMBERS_FILE, 'w') as f:
        json.dump(available_numbers, f, indent=2)

load_data()

# ==================== WEB PANEL WITH CAPTCHA HANDLING ====================
class WebPanelClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.logged_in = False
        self.last_login = 0
    
    def solve_captcha(self, html):
        """Extract and solve captcha from login page"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for captcha patterns
        captcha_text = None
        captcha_input = None
        
        # Pattern 1: Simple math like "5+2="
        math_patterns = [
            r'(\d+)\s*\+\s*(\d+)\s*=',
            r'(\d+)\s*-\s*(\d+)\s*=',
            r'(\d+)\s*\*\s*(\d+)\s*=',
            r'(\d+)\s*/\s*(\d+)\s*='
        ]
        
        for pattern in math_patterns:
            match = re.search(pattern, html)
            if match:
                if '+' in pattern:
                    result = int(match.group(1)) + int(match.group(2))
                elif '-' in pattern:
                    result = int(match.group(1)) - int(match.group(2))
                elif '*' in pattern:
                    result = int(match.group(1)) * int(match.group(2))
                else:
                    result = int(match.group(1)) // int(match.group(2)) if int(match.group(2)) != 0 else 0
                return str(result)
        
        # Pattern 2: Direct number captcha
        num_match = re.search(r'(\d{2,4})', html)
        if num_match:
            return num_match.group(1)
        
        return None
    
    def login(self):
        """Login with captcha handling"""
        try:
            # Get login page first to extract captcha
            login_page = self.session.get(WEB_LOGIN_URL, timeout=10)
            if login_page.status_code != 200:
                return False
            
            # Solve captcha
            captcha_answer = self.solve_captcha(login_page.text)
            
            # Prepare login data
            login_data = {
                'username': WEB_USER,
                'password': WEB_PASS
            }
            
            # Add captcha if found
            if captcha_answer:
                login_data['captcha'] = captcha_answer
                # Try different field names
                for field in ['captcha_code', 'code', 'captcha_response', 'answer']:
                    login_data[field] = captcha_answer
            
            # Attempt login
            response = self.session.post(WEB_LOGIN_URL, data=login_data, timeout=10)
            
            # Check if login successful
            if response.status_code == 200:
                if 'dashboard' in response.text.lower() or 'welcome' in response.text.lower():
                    self.logged_in = True
                    self.last_login = time.time()
                    print("✅ Web panel login successful")
                    return True
                else:
                    # Try without captcha
                    response2 = self.session.post(WEB_LOGIN_URL, data={'username': WEB_USER, 'password': WEB_PASS}, timeout=10)
                    if response2.status_code == 200 and ('dashboard' in response2.text.lower() or 'welcome' in response2.text.lower()):
                        self.logged_in = True
                        self.last_login = time.time()
                        print("✅ Web panel login successful (no captcha)")
                        return True
            
            return False
            
        except Exception as e:
            print(f"Login error: {e}")
            return False
    
    def fetch_sms_data(self):
        """Fetch SMS/CDR data from panel"""
        try:
            if not self.logged_in or (time.time() - self.last_login) > 300:  # Re-login every 5 min
                self.login()
            
            response = self.session.get(WEB_API_URL, timeout=10)
            if response.status_code == 200:
                return response.text
            return None
        except Exception as e:
            print(f"Fetch error: {e}")
            return None
    
    def get_otp_for_number(self, number: str) -> Optional[Dict]:
        """Get OTP for specific number from panel data"""
        try:
            data = self.fetch_sms_data()
            if not data:
                return None
            
            # Parse the data - looking for number and OTP patterns
            lines = data.split('\n')
            
            for line in lines:
                if number in line:
                    # Extract OTP (4-6 digits)
                    otp_match = re.search(r'\b\d{4,6}\b', line)
                    if otp_match:
                        otp = otp_match.group()
                        
                        # Detect service
                        service = "Unknown"
                        services = {
                            'facebook': 'Facebook', 'fb': 'Facebook',
                            'whatsapp': 'WhatsApp', 'wa': 'WhatsApp',
                            'telegram': 'Telegram', 'tg': 'Telegram',
                            'imo': 'IMO', 'instagram': 'Instagram', 'ig': 'Instagram',
                            'tiktok': 'TikTok', 'google': 'Google', 'gmail': 'Google',
                            'twitter': 'Twitter', 'snapchat': 'Snapchat', 'linkedin': 'LinkedIn'
                        }
                        
                        for key, val in services.items():
                            if key in line.lower():
                                service = val
                                break
                        
                        return {
                            'otp': otp,
                            'service': service,
                            'full_message': line.strip()
                        }
            
            return None
            
        except Exception as e:
            print(f"OTP fetch error: {e}")
            return None

web_panel = WebPanelClient()

# ==================== TOTP 2FA GENERATOR ====================
class TOTPGenerator:
    @staticmethod
    def generate_secret() -> str:
        """Generate base32 secret key"""
        return base64.b32encode(secrets.token_bytes(20)).decode('utf-8')
    
    @staticmethod
    def get_code(secret: str) -> str:
        """Generate TOTP code"""
        try:
            # Clean secret
            secret = secret.upper().replace(' ', '')
            # Add padding
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
        except Exception as e:
            print(f"TOTP error: {e}")
            return "000000"
    
    @staticmethod
    def time_remaining() -> int:
        """Seconds remaining in current interval"""
        return 30 - (int(time.time()) % 30)

# ==================== KEYBOARDS ====================
def get_main_keyboard(is_admin: bool = False):
    kb = [
        [InlineKeyboardButton("📱 Get Number", callback_data="get_number")],
        [InlineKeyboardButton("🔐 2FA Authenticator", callback_data="twofa")],
        [InlineKeyboardButton("📧 Temp Mail", callback_data="tempmail")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("📊 My Stats", callback_data="mystats")],
        [InlineKeyboardButton("📢 Support", callback_data="support")]
    ]
    if is_admin:
        kb.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

def get_country_keyboard():
    kb = []
    for country, numbers in available_numbers.items():
        if numbers:
            flag = get_country_flag(country)
            kb.append([InlineKeyboardButton(f"{flag} {country} (0.40TK)", callback_data=f"country_{country}")])
    
    if not kb:
        kb.append([InlineKeyboardButton("❌ No Countries Available", callback_data="noop")])
    
    kb.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh_countries")])
    kb.append([InlineKeyboardButton("🏠 Main Menu", callback_data="back_main")])
    return InlineKeyboardMarkup(kb)

def get_number_keyboard(country: str, numbers: list):
    kb = []
    for num in numbers[:8]:  # Show first 8 numbers
        kb.append([InlineKeyboardButton(f"📱 {num}", callback_data=f"use_num_{country}_{num}")])
    kb.append([InlineKeyboardButton("🔄 Refresh Numbers", callback_data=f"refresh_numbers_{country}")])
    kb.append([InlineKeyboardButton("🔙 Back to Countries", callback_data="get_number")])
    kb.append([InlineKeyboardButton("🏠 Main Menu", callback_data="back_main")])
    return InlineKeyboardMarkup(kb)

def get_otp_action_keyboard(number: str, country: str):
    kb = [
        [InlineKeyboardButton("🔄 Check OTP", callback_data=f"check_otp_{number}")],
        [InlineKeyboardButton("📱 Change Number", callback_data="get_number")],
        [InlineKeyboardButton("🌍 Change Country", callback_data="get_number")],
        [InlineKeyboardButton("📢 OTP Group", url=f"https://t.me/{OTP_GROUP[1:]}")],
        [InlineKeyboardButton("📢 Main Channel", url=f"https://t.me/{MAIN_CHANNEL[1:]}")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(kb)

def get_admin_keyboard():
    kb = [
        [InlineKeyboardButton("➕ Add Number", callback_data="admin_add_number")],
        [InlineKeyboardButton("🗑 Remove Number", callback_data="admin_remove_number")],
        [InlineKeyboardButton("📋 List Numbers", callback_data="admin_list_numbers")],
        [InlineKeyboardButton("➕ Add Country", callback_data="admin_add_country")],
        [InlineKeyboardButton("💰 Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("💸 Process Withdrawals", callback_data="admin_process_withdraw")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("📨 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("👥 Users List", callback_data="admin_users")],
        [InlineKeyboardButton("📈 Transaction Log", callback_data="admin_transactions")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(kb)

def get_withdraw_keyboard():
    kb = [
        [InlineKeyboardButton("bKash", callback_data="withdraw_bkash")],
        [InlineKeyboardButton("Nagad", callback_data="withdraw_nagad")],
        [InlineKeyboardButton("Rocket", callback_data="withdraw_rocket")],
        [InlineKeyboardButton("🔙 Back", callback_data="balance")]
    ]
    return InlineKeyboardMarkup(kb)

def get_2fa_keyboard(secret: str):
    code = TOTPGenerator.get_code(secret)
    remaining = TOTPGenerator.time_remaining()
    kb = [
        [InlineKeyboardButton(f"🔄 Refresh ({remaining}s)", callback_data="2fa_refresh")],
        [InlineKeyboardButton("📋 Copy Code", callback_data=f"2fa_copy_{code}")],
        [InlineKeyboardButton("📋 Copy Secret", callback_data="2fa_copy_secret")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(kb), code, remaining

def get_country_flag(country: str) -> str:
    flags = {
        "Myanmar": "🇲🇲", "Germany": "🇩🇪", "Tanzania": "🇹🇿", "Syria": "🇸🇾",
        "Peru": "🇵🇪", "Bangladesh": "🇧🇩", "India": "🇮🇳", "Pakistan": "🇵🇰",
        "UAE": "🇦🇪", "Saudi Arabia": "🇸🇦", "USA": "🇺🇸", "UK": "🇬🇧",
        "Canada": "🇨🇦", "Australia": "🇦🇺", "France": "🇫🇷", "Spain": "🇪🇸",
        "Italy": "🇮🇹", "Turkey": "🇹🇷", "Egypt": "🇪🇬", "Nigeria": "🇳🇬"
    }
    return flags.get(country, "🌍")

# ==================== TEMP MAIL SERVICE ====================
def generate_temp_email(user_id: int) -> str:
    """Generate temporary email"""
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
    email = f"{username}@mailto.plus"
    temp_emails[user_id] = {
        'email': email,
        'created_at': datetime.now().isoformat(),
        'messages': []
    }
    save_data()
    return email

def check_temp_email(user_id: int) -> list:
    """Check for new emails"""
    # In production, integrate with actual temp mail API
    return temp_emails.get(user_id, {}).get('messages', [])

# ==================== BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user = update.effective_user
    is_admin = user.id == ADMIN_ID
    
    # Initialize user if new
    if user.id not in user_balances:
        user_balances[user.id] = 0
        user_stats[user.id] = {
            'joined': datetime.now().isoformat(),
            'total_orders': 0,
            'total_earned': 0,
            'total_spent': 0
        }
        save_data()
    
    welcome_text = f"""
🎉 *Welcome to GetPaid OTP 2.0 Bot* 🎉

👤 *User:* {user.first_name}
🆔 *ID:* `{user.id}`
📊 *Monthly Users:* 14,738
💰 *Balance:* {user_balances.get(user.id, 0):.2f} TK

⚡ *How it works:*
• Select a country and number (Cost: 0.40 TK)
• Receive OTP on that number
• Earn 0.30 TK per OTP received
• Minimum withdrawal: {MIN_WITHDRAW} TK

🔐 *Services:* 2FA | Temp Mail | OTP

👇 *Choose an option:*
"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard(is_admin)
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    is_admin = user_id == ADMIN_ID
    
    # ========== NAVIGATION ==========
    if data == "back_main":
        await query.edit_message_text(
            "🏠 *Main Menu*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_keyboard(is_admin)
        )
    
    elif data == "get_number":
        if not available_numbers:
            await query.edit_message_text(
                "❌ *No numbers available*\n\nPlease contact admin to add numbers.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Back", callback_data="back_main")]])
            )
        else:
            await query.edit_message_text(
                "🌍 *Select Country*\n\n💰 Price: 0.40 TK per number\n💎 You earn 0.30 TK per OTP received\n\nChoose a country:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_country_keyboard()
            )
    
    elif data == "refresh_countries":
        await query.edit_message_text(
            "🌍 *Select Country*\n\n💰 Price: 0.40 TK per number",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_country_keyboard()
        )
    
    elif data.startswith("country_"):
        country = data.replace("country_", "")
        context.user_data['selected_country'] = country
        numbers = available_numbers.get(country, [])
        
        if numbers:
            await query.edit_message_text(
                f"📱 *Available Numbers - {get_country_flag(country)} {country}*\n\n"
                f"💰 Price: 0.40 TK\n"
                f"📊 Available: {len(numbers)} numbers\n\n"
                f"Select a number:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_number_keyboard(country, numbers)
            )
        else:
            await query.edit_message_text(
                f"❌ *No numbers available for {country}*\n\nPlease check back later.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
                ])
            )
    
    elif data.startswith("refresh_numbers_"):
        country = data.replace("refresh_numbers_", "")
        numbers = available_numbers.get(country, [])
        await query.edit_message_text(
            f"📱 *Available Numbers - {get_country_flag(country)} {country}*\n\n"
            f"💰 Price: 0.40 TK\n"
            f"📊 Available: {len(numbers)} numbers\n\n"
            f"Select a number:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_number_keyboard(country, numbers)
        )
    
    elif data.startswith("use_num_"):
        parts = data.split("_")
        country = parts[2]
        number = parts[3]
        
        # Check balance
        if user_balances.get(user_id, 0) < OTP_COST_AMOUNT:
            await query.edit_message_text(
                f"❌ *Insufficient Balance!*\n\n"
                f"💰 Your Balance: {user_balances.get(user_id, 0):.2f} TK\n"
                f"💵 Required: {OTP_COST_AMOUNT} TK\n\n"
                f"Contact admin to add balance or earn by receiving OTPs.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
                ])
            )
            return
        
        # Deduct balance
        user_balances[user_id] = user_balances.get(user_id, 0) - OTP_COST_AMOUNT
        
        # Record transaction
        if user_id not in user_transactions:
            user_transactions[user_id] = []
        user_transactions[user_id].append({
            'type': 'spent',
            'amount': OTP_COST_AMOUNT,
            'number': number,
            'country': country,
            'time': datetime.now().isoformat()
        })
        
        # Update stats
        if user_id not in user_stats:
            user_stats[user_id] = {'total_orders': 0, 'total_earned': 0, 'total_spent': 0}
        user_stats[user_id]['total_spent'] = user_stats[user_id].get('total_spent', 0) + OTP_COST_AMOUNT
        user_stats[user_id]['total_orders'] = user_stats[user_id].get('total_orders', 0) + 1
        
        save_data()
        
        # Store order
        active_orders[user_id] = {
            'number': number,
            'country': country,
            'start_time': time.time(),
            'status': 'waiting',
            'otp': None,
            'service': None
        }
        
        # Show success message
        await query.edit_message_text(
            f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
            f"🇧🇩 *নাজার যাচাই সম্পন্ন*\n"
            f"🌍 *দেশ ও দাম:* {country} ({OTP_COST_AMOUNT}TK)\n\n"
            f"📱 *Number:* `{number}`\n\n"
            f"🔑 *OTP কোড:* `Waiting...` ⏳\n\n"
            f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
            f"📢 *OTP GROUP:* {OTP_GROUP}\n\n"
            f"⏳ Waiting for OTP... This may take 1-3 minutes.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_otp_action_keyboard(number, country)
        )
        
        # Start background OTP checker
        asyncio.create_task(check_otp_background(
            context, user_id, number, country, 
            query.message.chat_id, query.message.message_id
        ))
    
    elif data.startswith("check_otp_"):
        number = data.replace("check_otp_", "")
        
        # Find user's order
        for uid, order in active_orders.items():
            if order.get('number') == number and order.get('otp'):
                await query.edit_message_text(
                    f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
                    f"🇧🇩 *নাজার যাচাই সম্পন্ন*\n"
                    f"🌍 *দেশ ও দাম:* {order['country']} ({OTP_COST_AMOUNT}TK)\n\n"
                    f"📱 *Number:* `{number}`\n"
                    f"🔧 *Service:* {order.get('service', 'Unknown')}\n\n"
                    f"🔑 *OTP কোড:* `{order['otp']}` ✅\n\n"
                    f"💰 *Earned:* +{OTP_EARN_AMOUNT} TK\n"
                    f"💵 *New Balance:* {user_balances.get(uid, 0):.2f} TK\n\n"
                    f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
                    f"📢 *OTP GROUP:* {OTP_GROUP}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_otp_action_keyboard(number, order['country'])
                )
                return
        
        await query.answer("Still waiting for OTP. Please wait...", show_alert=True)
    
    # ========== 2FA HANDLERS ==========
    elif data == "twofa":
        if user_id not in totp_secrets:
            totp_secrets[user_id] = TOTPGenerator.generate_secret()
            save_data()
        
        kb, code, remaining = get_2fa_keyboard(totp_secrets[user_id])
        
        await query.edit_message_text(
            f"🔐 *2FA Authenticator*\n\n"
            f"🔑 *Secret Key:*\n`{totp_secrets[user_id]}`\n\n"
            f"🔢 *Current Code:* `{code}`\n"
            f"⏱ *Valid for:* {remaining} seconds\n\n"
            f"📝 *Format:* A-Z and 2-7 only\n"
            f"⚠️ *Save your secret key!*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        
        # Start auto-refresh
        if '2fa_task' not in context.chat_data:
            context.chat_data['2fa_task'] = asyncio.create_task(
                auto_refresh_2fa(context, query.message.chat_id, user_id)
            )
    
    elif data == "2fa_refresh":
        if user_id in totp_secrets:
            code = TOTPGenerator.get_code(totp_secrets[user_id])
            remaining = TOTPGenerator.time_remaining()
            kb, _, _ = get_2fa_keyboard(totp_secrets[user_id])
            
            await query.edit_message_text(
                f"🔐 *2FA Authenticator*\n\n"
                f"🔑 *Secret Key:*\n`{totp_secrets[user_id]}`\n\n"
                f"🔢 *Current Code:* `{code}`\n"
                f"⏱ *Valid for:* {remaining} seconds\n\n"
                f"📝 *Format:* A-Z and 2-7 only",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
    
    elif data.startswith("2fa_copy_"):
        code = data.replace("2fa_copy_", "")
        await query.answer(f"✅ Code copied: {code}", show_alert=True)
    
    elif data == "2fa_copy_secret":
        if user_id in totp_secrets:
            await query.answer(f"✅ Secret copied!", show_alert=True)
    
    # ========== TEMP MAIL ==========
    elif data == "tempmail":
        email = generate_temp_email(user_id)
        await query.edit_message_text(
            f"📧 *Temporary Email Generated*\n\n"
            f"📨 `{email}`\n\n"
            f"⚡ Use this email to receive messages\n"
            f"📬 Use /checkmail to see incoming emails\n\n"
            f"💡 *Tip:* Messages appear within 1-2 minutes",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Check Mail", callback_data="check_tempmail")],
                [InlineKeyboardButton("🆕 New Email", callback_data="tempmail")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_main")]
            ])
        )
    
    elif data == "check_tempmail":
        messages = check_temp_email(user_id)
        if messages:
            msg = "📬 *Your Messages:*\n\n"
            for m in messages[-5:]:
                msg += f"📧 From: {m.get('from', 'Unknown')}\n"
                msg += f"📝 Subject: {m.get('subject', 'No subject')}\n"
                msg += f"💬 {m.get('body', '')[:150]}...\n\n"
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await query.edit_message_text(
                "📭 *No messages yet*\n\nCheck again in a few seconds!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data="check_tempmail")],
                    [InlineKeyboardButton("🏠 Back", callback_data="back_main")]
                ])
            )
    
    # ========== BALANCE & WITHDRAW ==========
    elif data == "balance":
        balance = user_balances.get(user_id, 0)
        stats = user_stats.get(user_id, {})
        
        await query.edit_message_text(
            f"💰 *Your Balance*\n\n"
            f"💵 *Available:* `{balance:.2f} TK`\n\n"
            f"📊 *Statistics:*\n"
            f"• Total Orders: {stats.get('total_orders', 0)}\n"
            f"• Total Earned: {stats.get('total_earned', 0):.2f} TK\n"
            f"• Total Spent: {stats.get('total_spent', 0):.2f} TK\n\n"
            f"💸 *Minimum Withdrawal:* {MIN_WITHDRAW} TK\n\n"
            f"👇 *Withdraw your earnings:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💸 Withdraw Now", callback_data="withdraw")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
            ])
        )
    
    elif data == "withdraw":
        balance = user_balances.get(user_id, 0)
        if balance >= MIN_WITHDRAW:
            await query.edit_message_text(
                f"💸 *Withdrawal Request*\n\n"
                f"💰 Your Balance: {balance:.2f} TK\n"
                f"💵 Withdrawable: {balance:.2f} TK\n\n"
                f"Select your withdrawal method:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_withdraw_keyboard()
            )
        else:
            await query.edit_message_text(
                f"❌ *Insufficient Balance for Withdrawal*\n\n"
                f"💰 Your Balance: {balance:.2f} TK\n"
                f"💵 Minimum Required: {MIN_WITHDRAW} TK\n\n"
                f"📱 Get more numbers and receive OTPs to earn!\n"
                f"💰 You earn {OTP_EARN_AMOUNT} TK per OTP received.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📱 Get Number", callback_data="get_number")],
                    [InlineKeyboardButton("🔙 Back", callback_data="balance")]
                ])
            )
    
    elif data.startswith("withdraw_"):
        method = data.replace("withdraw_", "").upper()
        context.user_data['withdraw_method'] = method
        
        await query.edit_message_text(
            f"💸 *Withdrawal Request - {method}*\n\n"
            f"💰 Amount: {user_balances.get(user_id, 0):.2f} TK\n"
            f"💵 Minimum: {MIN_WITHDRAW} TK\n\n"
            f"📝 Send your {method} account number:\n"
            f"Example: `01XXXXXXXXX`\n\n"
            f"Send as: `/wd ACCOUNT_NUMBER`\n\n"
            f"Type /cancel to cancel",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data['awaiting_withdraw'] = True
    
    elif data == "mystats":
        stats = user_stats.get(user_id, {})
        balance = user_balances.get(user_id, 0)
        
        await query.edit_message_text(
            f"📊 *Your Statistics*\n\n"
            f"💰 *Balance:* {balance:.2f} TK\n"
            f"📦 *Total Orders:* {stats.get('total_orders', 0)}\n"
            f"💵 *Total Earned:* {stats.get('total_earned', 0):.2f} TK\n"
            f"💸 *Total Spent:* {stats.get('total_spent', 0):.2f} TK\n"
            f"📈 *Profit:* {(stats.get('total_earned', 0) - stats.get('total_spent', 0)):.2f} TK\n"
            f"📅 *Member Since:* {stats.get('joined', 'N/A')[:10]}\n\n"
            f"📱 *Active Orders:* {len([o for o in active_orders.keys() if o == user_id])}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
            ])
        )
    
    elif data == "support":
        await query.edit_message_text(
            f"📞 *Support Center*\n\n"
            f"📢 *Main Channel:* {MAIN_CHANNEL}\n"
            f"👥 *OTP Group:* {OTP_GROUP}\n\n"
            f"❓ *FAQ:*\n"
            f"• Q: How to earn?\n"
            f"  A: Get number → Receive OTP → Earn {OTP_EARN_AMOUNT} TK\n\n"
            f"• Q: Minimum withdrawal?\n"
            f"  A: {MIN_WITHDRAW} TK\n\n"
            f"• Q: How long does OTP take?\n"
            f"  A: Usually 1-3 minutes\n\n"
            f"👨‍💻 *Admin:* @GetPaidAdmin\n\n"
            f"For issues, contact admin.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{MAIN_CHANNEL[1:]}")],
                [InlineKeyboardButton("👥 Join Group", url=f"https://t.me/{OTP_GROUP[1:]}")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
            ]),
            disable_web_page_preview=True
        )
    
    # ========== ADMIN PANEL ==========
    elif data == "admin_panel" and is_admin:
        await query.edit_message_text(
            "⚙️ *Admin Control Panel*\n\n"
            "Manage bot settings, numbers, and users:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_admin_keyboard()
        )
    
    elif data == "admin_add_number" and is_admin:
        await query.edit_message_text(
            "➕ *Add Number*\n\n"
            "Send number in format:\n"
            "`/addnum COUNTRY +1234567890`\n\n"
            "Example: `/addnum Germany +491551329004`\n\n"
            "Available countries: " + ", ".join(list(available_numbers.keys())) if available_numbers else "None",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "admin_remove_number" and is_admin:
        await query.edit_message_text(
            "🗑 *Remove Number*\n\n"
            "Send: `/remnum COUNTRY +1234567890`\n\n"
            "Example: `/remnum Germany +491551329004`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "admin_list_numbers" and is_admin:
        msg = "📋 *Available Numbers*\n\n"
        for country, nums in available_numbers.items():
            if nums:
                msg += f"*{country}:* {len(nums)} numbers\n"
                for num in nums[:5]:
                    msg += f"  • `{num}`\n"
                msg += "\n"
        
        if msg == "📋 *Available Numbers*\n\n":
            msg += "No numbers available.\n"
        
        await query.edit_message_text(
            msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
            ])
        )
    
    elif data == "admin_add_country" and is_admin:
        await query.edit_message_text(
            "➕ *Add Country*\n\n"
            "Send: `/addcountry COUNTRY_NAME`\n\n"
            "Example: `/addcountry Canada`\n\n"
            "Price will be set to 0.40 TK automatically.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "admin_add_balance" and is_admin:
        await query.edit_message_text(
            "💰 *Add Balance*\n\n"
            "Send: `/addbal USER_ID AMOUNT`\n\n"
            "Example: `/addbal 7064572216 100`\n\n"
            "User ID can be found in /users list",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "admin_process_withdraw" and is_admin:
        if pending_withdrawals:
            msg = "💸 *Pending Withdrawals*\n\n"
            for uid, wd in pending_withdrawals.items():
                msg += f"👤 User: `{uid}`\n"
                msg += f"💰 Amount: {wd['amount']:.2f} TK\n"
                msg += f"💳 Method: {wd['method']}\n"
                msg += f"📱 Account: {wd['account']}\n"
                msg += f"⏰ Time: {wd['time'][:19]}\n"
                msg += f"➖➖➖➖➖➖➖➖\n\n"
            
            msg += "Send `/approvewd USER_ID` to approve\n"
            msg += "Send `/rejectwd USER_ID` to reject"
            
            await query.edit_message_text(
                msg,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
                ])
            )
        else:
            await query.edit_message_text(
                "✅ No pending withdrawals",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
                ])
            )
    
    elif data == "admin_stats" and is_admin:
        total_users = len(user_balances)
        total_balance = sum(user_balances.values())
        total_earned = sum(s.get('total_earned', 0) for s in user_stats.values())
        total_spent = sum(s.get('total_spent', 0) for s in user_stats.values())
        active_sessions = len(active_orders)
        pending_wd = len(pending_withdrawals)
        total_numbers = sum(len(nums) for nums in available_numbers.values())
        
        stats_msg = f"""
📊 *Bot Statistics*

👥 *Total Users:* {total_users}
💰 *Total Balance:* {total_balance:.2f} TK
💵 *Total Earned:* {total_earned:.2f} TK
💸 *Total Spent:* {total_spent:.2f} TK
📈 *Platform Profit:* {(total_spent - total_earned):.2f} TK

🔄 *Active OTP Sessions:* {active_sessions}
💸 *Pending Withdrawals:* {pending_wd}
📱 *Available Numbers:* {total_numbers}
🌍 *Countries:* {len(available_numbers)}

🔐 *2FA Users:* {len(totp_secrets)}
📧 *Temp Mail Users:* {len(temp_emails)}

⏰ *Last Login:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        await query.edit_message_text(
            stats_msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
            ])
        )
    
    elif data == "admin_broadcast" and is_admin:
        await query.edit_message_text(
            "📨 *Broadcast Message*\n\n"
            "Send: `/broadcast Your message here`\n\n"
            "Message will be sent to ALL users.\n"
            "HTML formatting supported.\n\n"
            "Example: `/broadcast <b>Maintenance</b> at 2AM`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "admin_users" and is_admin:
        users_list = "👥 *Users List*\n\n"
        for uid, bal in sorted(user_balances.items(), key=lambda x: x[1], reverse=True)[:20]:
            stats = user_stats.get(uid, {})
            users_list += f"• `{uid}` - {bal:.2f} TK (Orders: {stats.get('total_orders', 0)})\n"
        
        users_list += f"\nTotal: {len(user_balances)} users"
        
        await query.edit_message_text(
            users_list,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
            ])
        )
    
    elif data == "admin_transactions" and is_admin:
        await query.edit_message_text(
            "📈 *Recent Transactions*\n\n"
            "Use `/transactions USER_ID` to view user transactions",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
            ])
        )

async def auto_refresh_2fa(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    """Auto refresh 2FA code every second"""
    while True:
        await asyncio.sleep(1)
        if user_id in totp_secrets:
            remaining = TOTPGenerator.time_remaining()
            if remaining == 30 or remaining == 1:
                try:
                    code = TOTPGenerator.get_code(totp_secrets[user_id])
                    kb, _, _ = get_2fa_keyboard(totp_secrets[user_id])
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=context.chat_data.get('2fa_msg_id'),
                        text=f"🔐 *2FA Authenticator*\n\n"
                             f"🔑 *Secret Key:*\n`{totp_secrets[user_id]}`\n\n"
                             f"🔢 *Current Code:* `{code}`\n"
                             f"⏱ *Valid for:* {remaining} seconds\n\n"
                             f"📝 *Format:* A-Z and 2-7 only",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=kb
                    )
                except:
                    pass

async def check_otp_background(context: ContextTypes.DEFAULT_TYPE, user_id: int, number: str, country: str, chat_id: int, msg_id: int):
    """Background task to check for OTP"""
    for attempt in range(60):  # Check for 4 minutes (60 * 4 = 240 seconds)
        await asyncio.sleep(4)
        
        if user_id not in active_orders:
            return
        
        result = web_panel.get_otp_for_number(number)
        
        if result and result.get('otp'):
            otp = result['otp']
            service = result.get('service', 'Unknown')
            
            # Add earnings
            user_balances[user_id] = user_balances.get(user_id, 0) + OTP_EARN_AMOUNT
            
            # Record transaction
            if user_id not in user_transactions:
                user_transactions[user_id] = []
            user_transactions[user_id].append({
                'type': 'earned',
                'amount': OTP_EARN_AMOUNT,
                'number': number,
                'otp': otp,
                'service': service,
                'time': datetime.now().isoformat()
            })
            
            # Update stats
            if user_id not in user_stats:
                user_stats[user_id] = {'total_orders': 0, 'total_earned': 0, 'total_spent': 0}
            user_stats[user_id]['total_earned'] = user_stats[user_id].get('total_earned', 0) + OTP_EARN_AMOUNT
            
            save_data()
            
            # Update order
            active_orders[user_id]['otp'] = otp
            active_orders[user_id]['service'] = service
            active_orders[user_id]['status'] = 'completed'
            
            # Update message
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
                         f"🇧🇩 *নাজার যাচাই সম্পন্ন*\n"
                         f"🌍 *দেশ ও দাম:* {country} ({OTP_COST_AMOUNT}TK)\n\n"
                         f"📱 *Number:* `{number}`\n"
                         f"🔧 *Service:* {service}\n\n"
                         f"🔑 *OTP কোড:* `{otp}` ✅\n\n"
                         f"💰 *Earned:* +{OTP_EARN_AMOUNT} TK\n"
                         f"💵 *New Balance:* {user_balances[user_id]:.2f} TK\n\n"
                         f"✅ *NUMBER VERIFIED SUCCESSFULLY*\n\n"
                         f"📢 *OTP GROUP:* {OTP_GROUP}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_otp_action_keyboard(number, country)
                )
            except Exception as e:
                print(f"Edit message error: {e}")
            
            # Forward to OTP Group
            await forward_otp_to_group(context, number, country, otp, service)
            
            # Send DM to user
            await context.bot.send_message(
                user_id,
                f"🔐 *OTP Received for Your Number*\n\n"
                f"📱 *Number:* `{number[-10:]}`\n"
                f"🌍 *Country:* {country}\n"
                f"🔧 *Service:* {service}\n"
                f"🔑 *OTP:* `{otp}`\n\n"
                f"💰 *+{OTP_EARN_AMOUNT} TK added to balance!*\n"
                f"💵 *New Balance:* {user_balances[user_id]:.2f} TK",
                parse_mode=ParseMode.MARKDOWN
            )
            
            return

async def forward_otp_to_group(context: ContextTypes.DEFAULT_TYPE, number: str, country: str, otp: str, service: str):
    """Forward OTP to group in formatted style"""
    # Mask number (show first 4 and last 4 digits)
    if len(number) > 8:
        masked = number[:4] + "****" + number[-4:]
    else:
        masked = number
    
    message = f"""🔐 *GetPaid OTP 2.0 | OTP RCV*

📱 *Number:* `{masked}`
🌍 *Country:* {country}
🔧 *Service:* {service}

✅ *Status:* CLAIMED

🔑 *OTP Code:* `{otp}`

`#{otp} is your {service} verification code`

🔗 @{BOT_USERNAME} | {MAIN_CHANNEL}"""
    
    try:
        await context.bot.send_message(
            OTP_GROUP,
            message,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        print(f"Group forward error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    user_id = update.effective_user.id
    text = update.message.text
    is_admin = user_id == ADMIN_ID
    
    # Handle withdrawal input
    if context.user_data.get('awaiting_withdraw'):
        if text == '/cancel':
            context.user_data['awaiting_withdraw'] = False
            await update.message.reply_text("❌ Withdrawal cancelled", reply_markup=get_main_keyboard(is_admin))
            return
        
        method = context.user_data.get('withdraw_method', 'Unknown')
        account = text.strip()
        amount = user_balances.get(user_id, 0)
        
        if amount >= MIN_WITHDRAW:
            pending_withdrawals[user_id] = {
                'amount': amount,
                'method': method,
                'account': account,
                'time': datetime.now().isoformat()
            }
            save_data()
            
            await update.message.reply_text(
                f"✅ *Withdrawal Request Submitted*\n\n"
                f"💰 Amount: {amount:.2f} TK\n"
                f"💳 Method: {method}\n"
                f"📱 Account: {account}\n\n"
                f"⏳ Will be processed within 24 hours.\n"
                f"📢 Contact admin if not processed.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_keyboard(is_admin)
            )
            
            # Notify admin
            await context.bot.send_message(
                ADMIN_ID,
                f"💰 *New Withdrawal Request*\n\n"
                f"👤 User: `{user_id}`\n"
                f"💰 Amount: {amount:.2f} TK\n"
                f"💳 Method: {method}\n"
                f"📱 Account: {account}\n"
                f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"❌ Insufficient balance! Minimum {MIN_WITHDRAW} TK required.",
                reply_markup=get_main_keyboard(is_admin)
            )
        
        context.user_data['awaiting_withdraw'] = False
        return
    
    # Handle /cancel
    if text == '/cancel':
        context.user_data['awaiting_withdraw'] = False
        context.user_data['awaiting_2fa'] = False
        await update.message.reply_text("❌ Cancelled", reply_markup=get_main_keyboard(is_admin))
        return
    
    # Handle withdrawal command
    if text.startswith('/wd'):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            account = parts[1]
            amount = user_balances.get(user_id, 0)
            
            if amount >= MIN_WITHDRAW:
                method = context.user_data.get('withdraw_method', 'Unknown')
                pending_withdrawals[user_id] = {
                    'amount': amount,
                    'method': method,
                    'account': account,
                    'time': datetime.now().isoformat()
                }
                save_data()
                
                await update.message.reply_text(
                    f"✅ Withdrawal request submitted!\nAmount: {amount:.2f} TK\nMethod: {method}",
                    reply_markup=get_main_keyboard(is_admin)
                )
                
                await context.bot.send_message(
                    ADMIN_ID,
                    f"💰 Withdrawal\nUser: {user_id}\nAmount: {amount:.2f} TK\nMethod: {method}\nAccount: {account}"
                )
            else:
                await update.message.reply_text(f"❌ Minimum withdrawal: {MIN_WITHDRAW} TK")
        else:
            await update.message.reply_text("❌ Send: /wd ACCOUNT_NUMBER")
        return
    
    # Check mail command
    if text == '/checkmail':
        messages = check_temp_email(user_id)
        if messages:
            msg = "📬 *Your Messages:*\n\n"
            for m in messages[-5:]:
                msg += f"📧 From: {m.get('from', 'Unknown')}\n📝 {m.get('body', '')[:150]}\n\n"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("📭 No messages yet!")
        return
    
    # ========== ADMIN COMMANDS ==========
    if not is_admin:
        return
    
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
                save_data()
                await update.message.reply_text(f"✅ Added {amount} TK to `{target}`", parse_mode=ParseMode.MARKDOWN)
                try:
                    await context.bot.send_message(target, f"💰 +{amount} TK added to your balance!")
                except:
                    pass
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
    
    elif text.startswith('/broadcast'):
        msg = text.replace('/broadcast', '', 1).strip()
        if msg:
            sent = 0
            failed = 0
            for uid in user_balances.keys():
                try:
                    await context.bot.send_message(
                        uid,
                        f"📢 *Announcement*\n\n{msg}",
                        parse_mode=ParseMode.HTML
                    )
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
                    await context.bot.send_message(
                        target,
                        f"✅ *Withdrawal Approved!*\n\n💰 Amount: {wd['amount']:.2f} TK\n💳 Method: {wd['method']}\n\nFunds have been sent to your {wd['method']} account.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass
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
                # Refund balance
                user_balances[target] = user_balances.get(target, 0) + wd['amount']
                save_data()
                await update.message.reply_text(f"❌ Withdrawal rejected for `{target}`\nAmount refunded.", parse_mode=ParseMode.MARKDOWN)
                try:
                    await context.bot.send_message(
                        target,
                        f"❌ *Withdrawal Rejected*\n\n💰 Amount: {wd['amount']:.2f} TK\nReason: Please contact support.\n\nAmount has been refunded to your balance.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass
            else:
                await update.message.reply_text("❌ Withdrawal not found")
        else:
            await update.message.reply_text("❌ Use: /rejectwd USER_ID")
    
    elif text == '/users':
        msg = "👥 *Users*\n\n"
        for uid, bal in sorted(user_balances.items(), key=lambda x: x[1], reverse=True)[:30]:
            stats = user_stats.get(uid, {})
            msg += f"• `{uid}` - {bal:.2f} TK (Orders: {stats.get('total_orders', 0)})\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    
    elif text.startswith('/transactions'):
        parts = text.split()
        if len(parts) == 2:
            target = int(parts[1])
            trans = user_transactions.get(target, [])[-10:]
            if trans:
                msg = f"📈 *Transactions for `{target}`*\n\n"
                for t in trans[::-1]:
                    msg += f"• {t['type'].upper()}: {t['amount']:.2f} TK"
                    if t.get('service'):
                        msg += f" ({t['service']})"
                    msg += f"\n  {t['time'][:19]}\n\n"
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text("No transactions found")
        else:
            await update.message.reply_text("❌ Use: /transactions USER_ID")
    
    elif text == '/stats':
        total_users = len(user_balances)
        total_bal = sum(user_balances.values())
        total_earned = sum(s.get('total_earned', 0) for s in user_stats.values())
        total_spent = sum(s.get('total_spent', 0) for s in user_stats.values())
        await update.message.reply_text(
            f"📊 *Bot Stats*\n\n👥 Users: {total_users}\n💰 Balance: {total_bal:.2f} TK\n💵 Earned: {total_earned:.2f} TK\n💸 Spent: {total_spent:.2f} TK\n📈 Profit: {(total_spent - total_earned):.2f} TK",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == '/login' or text == '/refresh_login':
        web_panel.logged_in = False
        if web_panel.login():
            await update.message.reply_text("✅ Web panel login successful!")
        else:
            await update.message.reply_text("❌ Web panel login failed! Check credentials.")

async def checkmail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checkmail command handler"""
    user_id = update.effective_user.id
    messages = check_temp_email(user_id)
    if messages:
        msg = "📬 *Your Messages:*\n\n"
        for m in messages[-5:]:
            msg += f"📧 From: {m.get('from', 'Unknown')}\n📝 {m.get('body', '')[:150]}\n\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("📭 No messages yet!")

# ==================== FLASK WEBHOOK ====================
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
        'available_numbers': sum(len(nums) for nums in available_numbers.values()),
        'timestamp': datetime.now().isoformat()
    }), 200

@flask_app.route('/stats', methods=['GET'])
def stats():
    if request.remote_addr != '127.0.0.1':
        return 'Unauthorized', 401
    return jsonify({
        'users': len(user_balances),
        'total_balance': sum(user_balances.values()),
        'pending_withdrawals': len(pending_withdrawals),
        'active_sessions': len(active_orders)
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    # Build application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CommandHandler("checkmail", checkmail_command))
    application.add_handler(CommandHandler("wd", handle_message))
    application.add_handler(CommandHandler("cancel", handle_message))
    
    # Admin commands
    application.add_handler(CommandHandler("addnum", handle_message))
    application.add_handler(CommandHandler("remnum", handle_message))
    application.add_handler(CommandHandler("addbal", handle_message))
    application.add_handler(CommandHandler("addcountry", handle_message))
    application.add_handler(CommandHandler("broadcast", handle_message))
    application.add_handler(CommandHandler("approvewd", handle_message))
    application.add_handler(CommandHandler("rejectwd", handle_message))
    application.add_handler(CommandHandler("users", handle_message))
    application.add_handler(CommandHandler("transactions", handle_message))
    application.add_handler(CommandHandler("stats", handle_message))
    application.add_handler(CommandHandler("login", handle_message))
    application.add_handler(CommandHandler("refresh_login", handle_message))
    
    # Login to web panel
    print("🔄 Logging into web panel...")
    web_panel.login()
    
    # Start bot
    if os.environ.get('PORT'):
        # Webhook mode for Railway
        port = int(os.environ.get('PORT', 8080))
        webhook_url = os.environ.get('WEBHOOK_URL', '')
        if webhook_url:
            application.bot.set_webhook(webhook_url)
            print(f"✅ Webhook set to {webhook_url}")
        print(f"🚀 Starting Flask server on port {port}")
        flask_app.run(host='0.0.0.0', port=port)
    else:
        # Polling mode for local testing
        print("🤖 Starting bot in polling mode...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
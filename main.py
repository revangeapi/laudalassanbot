import logging
import asyncio
import requests
import sqlite3
import uuid
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
import html
import json
from flask import Flask, request, jsonify
import threading
import time

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask app setup
app = Flask(__name__)

# Bot Configuration
BOT_TOKEN = "7312642236:AAHlMXH8xBwg83uMkmzk43c6Ou6tmN2Sc5E"
CHANNELS = ["@anshapi", "@revangeosint"]
ADMIN_IDS = [6258915779]  # Replace with your Telegram ID

# Database setup
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  username TEXT,
                  first_name TEXT,
                  credits INTEGER DEFAULT 0,
                  referred_by INTEGER DEFAULT NULL,
                  is_banned INTEGER DEFAULT 0,
                  join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Referrals table
    c.execute('''CREATE TABLE IF NOT EXISTS referrals
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  referrer_id INTEGER,
                  referred_id INTEGER,
                  reward_claimed INTEGER DEFAULT 0,
                  date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Credit history table
    c.execute('''CREATE TABLE IF NOT EXISTS credit_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  credits_change INTEGER,
                  reason TEXT,
                  admin_id INTEGER,
                  date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    conn.close()

init_db()

class DatabaseManager:
    @staticmethod
    def get_user(user_id):
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        conn.close()
        return user

    @staticmethod
    def create_user(user_id, username, first_name, referred_by=None):
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        try:
            c.execute('''INSERT OR IGNORE INTO users 
                        (user_id, username, first_name, referred_by) 
                        VALUES (?, ?, ?, ?)''',
                     (user_id, username, first_name, referred_by))
            
            if referred_by:
                c.execute('''INSERT INTO referrals 
                            (referrer_id, referred_id) 
                            VALUES (?, ?)''',
                         (referred_by, user_id))
                
                # Give credit to referrer
                c.execute('''UPDATE users SET credits = credits + 1 
                            WHERE user_id = ?''', (referred_by,))
                
                # Log credit history
                c.execute('''INSERT INTO credit_history 
                            (user_id, credits_change, reason, admin_id) 
                            VALUES (?, ?, ?, ?)''',
                         (referred_by, 1, 'Referral Reward', 0))
            
            conn.commit()
        except Exception as e:
            logger.error(f"Error creating user: {e}")
        finally:
            conn.close()

    @staticmethod
    def update_credits(user_id, credits_change, reason, admin_id=0):
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        try:
            c.execute('''UPDATE users SET credits = credits + ? 
                        WHERE user_id = ?''', (credits_change, user_id))
            
            c.execute('''INSERT INTO credit_history 
                        (user_id, credits_change, reason, admin_id) 
                        VALUES (?, ?, ?, ?)''',
                     (user_id, credits_change, reason, admin_id))
            
            conn.commit()
        except Exception as e:
            logger.error(f"Error updating credits: {e}")
        finally:
            conn.close()

    @staticmethod
    def get_user_credits(user_id):
        user = DatabaseManager.get_user(user_id)
        return user[3] if user else 0

    @staticmethod
    def is_user_banned(user_id):
        user = DatabaseManager.get_user(user_id)
        return user[5] if user else False

    @staticmethod
    def ban_user(user_id, admin_id):
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    @staticmethod
    def unban_user(user_id, admin_id):
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    @staticmethod
    def get_all_users():
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users")
        users = c.fetchall()
        conn.close()
        return users

    @staticmethod
    def get_referral_stats(user_id):
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
        total_refs = c.fetchone()[0]
        conn.close()
        return total_refs

class APIServices:
    @staticmethod
    async def phone_lookup(number):
        try:
            url = f"https://numapi.anshapi.workers.dev/?num={number}"
            response = requests.get(url, timeout=10)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Phone lookup error: {e}")
            return None

    @staticmethod
    async def upi_lookup(upi_id):
        try:
            url = f"https://upi-info.vercel.app/api/upi?upi_id={upi_id}&key=456"
            response = requests.get(url, timeout=10)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"UPI lookup error: {e}")
            return None

    @staticmethod
    async def aadhaar_family(aadhaar):
        try:
            url = f"https://addartofamily.vercel.app/fetch?aadhaar={aadhaar}&key=fxt"
            response = requests.get(url, timeout=10)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Aadhaar lookup error: {e}")
            return None

    @staticmethod
    async def vehicle_lookup(rc_number):
        try:
            url = f"https://vecnum.anshapi.workers.dev/looklike?rc={rc_number}"
            response = requests.get(url, timeout=10)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Vehicle lookup error: {e}")
            return None

# Flask Routes
@app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>OSINT Bot Server</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #333; border-bottom: 2px solid #007cba; padding-bottom: 10px; }
            .status { background: #28a745; color: white; padding: 10px; border-radius: 5px; text-align: center; }
            .info { background: #17a2b8; color: white; padding: 15px; border-radius: 5px; margin: 20px 0; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 OSINT Investigation Bot Server</h1>
            <div class="status">
                <h2>🟢 SERVER IS RUNNING</h2>
            </div>
            <div class="info">
                <h3>📊 Server Information</h3>
                <p><strong>Status:</strong> Active & Running</p>
                <p><strong>Services:</strong> Phone Lookup, UPI Info, Aadhaar Family, Vehicle RC</p>
                <p><strong>Start Time:</strong> {}</p>
                <p><strong>Port:</strong> 5000</p>
            </div>
            <h3>🔗 Available Endpoints:</h3>
            <ul>
                <li><code>GET /</code> - This status page</li>
                <li><code>GET /health</code> - Health check</li>
                <li><code>GET /stats</code> - Bot statistics</li>
                <li><code>GET /users</code> - User list (Admin)</li>
                <li><code>POST /admin/add_credits</code> - Add credits to user</li>
            </ul>
        </div>
    </body>
    </html>
    """.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "osint-bot-server",
        "version": "1.0.0"
    })

@app.route('/stats')
def get_stats():
    users = DatabaseManager.get_all_users()
    total_users = len(users)
    total_credits = sum(user[3] for user in users)
    active_users = len([u for u in users if not u[5]])
    
    return jsonify({
        "total_users": total_users,
        "active_users": active_users,
        "banned_users": total_users - active_users,
        "total_credits": total_credits,
        "services_available": 4,
        "server_status": "running",
        "last_updated": datetime.now().isoformat()
    })

@app.route('/users')
def get_users():
    # Simple authentication (you might want to enhance this)
    admin_key = request.args.get('admin_key')
    if not admin_key or admin_key != "your_secret_admin_key_here":  # Change this
        return jsonify({"error": "Unauthorized"}), 401
    
    users = DatabaseManager.get_all_users()
    user_list = []
    
    for user in users:
        user_list.append({
            "user_id": user[0],
            "username": user[1],
            "first_name": user[2],
            "credits": user[3],
            "is_banned": bool(user[5]),
            "join_date": user[6]
        })
    
    return jsonify({
        "total_users": len(users),
        "users": user_list
    })

@app.route('/admin/add_credits', methods=['POST'])
def admin_add_credits():
    data = request.get_json()
    
    # Authentication
    admin_key = data.get('admin_key')
    if not admin_key or admin_key != "your_secret_admin_key_here":  # Change this
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = data.get('user_id')
    amount = data.get('amount')
    reason = data.get('reason', 'Admin API')
    
    if not user_id or not amount:
        return jsonify({"error": "Missing user_id or amount"}), 400
    
    try:
        DatabaseManager.update_credits(int(user_id), int(amount), reason, 0)
        return jsonify({
            "success": True,
            "message": f"Added {amount} credits to user {user_id}",
            "new_balance": DatabaseManager.get_user_credits(int(user_id))
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    not_joined = []
    
    for channel in CHANNELS:
        try:
            chat_member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if chat_member.status in ['left', 'kicked']:
                not_joined.append(channel)
        except Exception as e:
            logger.error(f"Error checking channel membership: {e}")
            not_joined.append(channel)
    
    return not_joined

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Check if user is banned
    if DatabaseManager.is_user_banned(user_id):
        await update.message.reply_text("🚫 <b>You are banned from using this bot.</b>", parse_mode=ParseMode.HTML)
        return
    
    # Handle referral
    referred_by = None
    if context.args:
        try:
            referred_by = int(context.args[0])
            if referred_by == user_id:
                referred_by = None
        except:
            referred_by = None
    
    # Create user in database
    DatabaseManager.create_user(user_id, username, first_name, referred_by)
    
    not_joined = await check_channel_membership(update, context)
    
    if not_joined:
        keyboard = []
        for channel in not_joined:
            keyboard.append([InlineKeyboardButton(f"Join {channel}", url=f"https://t.me/{channel[1:]}")])
        keyboard.append([InlineKeyboardButton("✅ I've Joined", callback_data="check_membership")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🔒 <b>ACCESS REQUIRED</b>\n\n"
            "📢 To unlock all features, please join our official channels:\n\n"
            f"• {CHANNELS[0]} - OSINT Updates\n"
            f"• {CHANNELS[1]} - Security Research\n\n"
            "Join both channels and click <b>✅ I've Joined</b> to continue.",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        return
    
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    credits = DatabaseManager.get_user_credits(user_id)
    
    keyboard = [
        [InlineKeyboardButton("📱 Phone Number Lookup", callback_data="service_phone")],
        [InlineKeyboardButton("💳 UPI Information", callback_data="service_upi")],
        [InlineKeyboardButton("🆔 Aadhaar Family Details", callback_data="service_aadhaar")],
        [InlineKeyboardButton("🚗 Vehicle RC Details", callback_data="service_vehicle")],
        [InlineKeyboardButton("💰 My Credits", callback_data="my_credits"), 
         InlineKeyboardButton("📊 Refer & Earn", callback_data="refer_earn")],
        [InlineKeyboardButton("📈 Statistics", callback_data="stats"), 
         InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    
    # Add admin panel for admins
    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
🔍 <b>OSINT INVESTIGATION SUITE</b>
━━━━━━━━━━━━━━━━━━━━

<b>Available Services:</b>

• <b>📱 Phone Lookup</b> - Mobile number verification & details
• <b>💳 UPI Info</b> - Bank account & UPI verification  
• <b>🆔 Aadhaar Family</b> - Family member identification
• <b>🚗 Vehicle RC</b> - Vehicle registration verification

💎 <b>Your Credits:</b> {credits}
🎯 <i>Select a service to begin investigation</i>
🔓 <i>All services - Unlimited & Free</i>
    """
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # Check if user is banned
    if DatabaseManager.is_user_banned(user_id):
        await query.message.edit_text("🚫 <b>You are banned from using this bot.</b>", parse_mode=ParseMode.HTML)
        return
    
    if query.data == "check_membership":
        not_joined = await check_channel_membership(update, context)
        if not_joined:
            await query.message.edit_text(
                "❌ <b>VERIFICATION FAILED</b>\n\nYou haven't joined all required channels. Please complete the membership and try again.",
                parse_mode=ParseMode.HTML
            )
            return
        await show_main_menu(update, context)
    
    elif query.data == "service_phone":
        await query.message.edit_text(
            "📱 <b>PHONE NUMBER LOOKUP</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔍 Enter the 10-digit mobile number (without country code):\n\n"
            "<code>Example: 9889662072</code>",
            parse_mode=ParseMode.HTML
        )
        context.user_data['awaiting_input'] = 'phone'
    
    elif query.data == "service_upi":
        await query.message.edit_text(
            "💳 <b>UPI INFORMATION LOOKUP</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔍 Enter the UPI ID (username@bank):\n\n"
            "<code>Example: ansh735@ptyes</code>",
            parse_mode=ParseMode.HTML
        )
        context.user_data['awaiting_input'] = 'upi'
    
    elif query.data == "service_aadhaar":
        await query.message.edit_text(
            "🆔 <b>AADHAAR FAMILY DETAILS</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔍 Enter the 12-digit Aadhaar number:\n\n"
            "<code>Example: 658014451208</code>",
            parse_mode=ParseMode.HTML
        )
        context.user_data['awaiting_input'] = 'aadhaar'
    
    elif query.data == "service_vehicle":
        await query.message.edit_text(
            "🚗 <b>VEHICLE RC LOOKUP</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔍 Enter the vehicle registration number:\n\n"
            "<code>Example: UP53DY4138</code>",
            parse_mode=ParseMode.HTML
        )
        context.user_data['awaiting_input'] = 'vehicle'
    
    elif query.data == "my_credits":
        await show_my_credits(update, context)
    
    elif query.data == "refer_earn":
        await show_refer_earn(update, context)
    
    elif query.data == "stats":
        await show_stats(update, context)
    
    elif query.data == "help":
        await show_help(update, context)
    
    elif query.data == "admin_panel":
        if user_id in ADMIN_IDS:
            await show_admin_panel(update, context)
        else:
            await query.answer("❌ Access Denied", show_alert=True)
    
    elif query.data == "back_to_menu":
        await show_main_menu(update, context)

async def show_my_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id
    credits = DatabaseManager.get_user_credits(user_id)
    total_refs = DatabaseManager.get_referral_stats(user_id)
    
    keyboard = [
        [InlineKeyboardButton("📊 Refer & Earn", callback_data="refer_earn")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
💰 <b>CREDIT WALLET</b>
━━━━━━━━━━━━━━━━━━━━

💎 <b>Available Credits:</b> {credits}
👥 <b>Total Referrals:</b> {total_refs}
🎁 <b>Referral Bonus:</b> 1 credit per referral

<b>How to Earn Credits:</b>
• Refer friends and get 1 credit each
• Admin rewards for active users
• Special promotions and events

💡 <i>Credits can be used for premium features (coming soon)</i>
    """
    
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def show_refer_earn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    total_refs = DatabaseManager.get_referral_stats(user_id)
    
    keyboard = [
        [InlineKeyboardButton("📤 Share Referral Link", url=f"https://t.me/share/url?url={referral_link}&text=Join%20this%20amazing%20OSINT%20bot%20for%20free%20investigations!")],
        [InlineKeyboardButton("💰 My Credits", callback_data="my_credits")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
📊 <b>REFER & EARN PROGRAM</b>
━━━━━━━━━━━━━━━━━━━━

🎯 <b>Your Referral Stats:</b>
┣ <b>Total Referrals:</b> {total_refs}
┣ <b>Credits Earned:</b> {total_refs}
┗ <b>Pending Credits:</b> 0

💰 <b>Reward System:</b>
• 1 Credit for every successful referral
• Unlimited earning potential
• Instant credit allocation

🔗 <b>Your Referral Link:</b>
<code>{referral_link}</code>

📢 <b>How to Refer:</b>
1. Share your referral link above
2. Ask friends to click and start bot
3. Get 1 credit when they join
4. No limit on referrals!

🎁 <i>Start referring and earn unlimited credits!</i>
    """
    
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
        [InlineKeyboardButton("💰 Credit Management", callback_data="admin_credits")],
        [InlineKeyboardButton("📊 Bot Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = """
👑 <b>ADMIN CONTROL PANEL</b>
━━━━━━━━━━━━━━━━━━━━

<b>Available Actions:</b>

• <b>👥 User Management</b> - View, ban, unban users
• <b>💰 Credit Management</b> - Add/remove user credits
• <b>📊 Bot Statistics</b> - View bot usage stats

⚡ <i>Select an option to manage the bot</i>
    """
    
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = DatabaseManager.get_all_users()
    total_users = len(users)
    banned_users = len([u for u in users if u[5]])
    
    keyboard = [
        [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban_user")],
        [InlineKeyboardButton("✅ Unban User", callback_data="admin_unban_user")],
        [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
👥 <b>USER MANAGEMENT</b>
━━━━━━━━━━━━━━━━━━━━

📊 <b>User Statistics:</b>
┣ <b>Total Users:</b> {total_users}
┣ <b>Active Users:</b> {total_users - banned_users}
┣ <b>Banned Users:</b> {banned_users}
┗ <b>Growth Rate:</b> Active

🛠️ <b>User Actions:</b>
• Ban/Unban users by ID
• View user details
• Manage user permissions

💡 <i>Use commands for user management:</i>
<code>/ban user_id</code> - Ban a user
<code>/unban user_id</code> - Unban a user
    """
    
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def admin_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Add Credits", callback_data="admin_add_credits")],
        [InlineKeyboardButton("➖ Remove Credits", callback_data="admin_remove_credits")],
        [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = """
💰 <b>CREDIT MANAGEMENT</b>
━━━━━━━━━━━━━━━━━━━━

🛠️ <b>Credit Actions:</b>
• Add credits to any user
• Remove credits from users
• Set custom credit amounts

💡 <i>Use commands for credit management:</i>
<code>/addcredits user_id amount</code> - Add credits
<code>/removecredits user_id amount</code> - Remove credits

⚠️ <i>All credit changes are logged</i>
    """
    
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = DatabaseManager.get_all_users()
    total_users = len(users)
    total_credits = sum(user[3] for user in users)
    total_refs = sum(DatabaseManager.get_referral_stats(user[0]) for user in users)
    
    keyboard = [[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
📊 <b>BOT STATISTICS</b>
━━━━━━━━━━━━━━━━━━━━

📈 <b>Overall Statistics:</b>
┣ <b>Total Users:</b> {total_users}
┣ <b>Total Credits Distributed:</b> {total_credits}
┣ <b>Total Referrals:</b> {total_refs}
┣ <b>Active Services:</b> 4
┗ <b>Database Size:</b> Optimized

🎯 <b>Performance Metrics:</b>
• Uptime: 100%
• Response Time: Excellent
• Service Availability: All Active

📅 <b>Last Updated:</b> {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}
    """
    
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

# Admin command handlers
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Access Denied")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /ban user_id")
        return
    
    try:
        target_user = int(context.args[0])
        DatabaseManager.ban_user(target_user, user_id)
        await update.message.reply_text(f"✅ User {target_user} has been banned.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Access Denied")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /unban user_id")
        return
    
    try:
        target_user = int(context.args[0])
        DatabaseManager.unban_user(target_user, user_id)
        await update.message.reply_text(f"✅ User {target_user} has been unbanned.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def add_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Access Denied")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /addcredits user_id amount")
        return
    
    try:
        target_user = int(context.args[0])
        amount = int(context.args[1])
        DatabaseManager.update_credits(target_user, amount, "Admin Added", user_id)
        await update.message.reply_text(f"✅ Added {amount} credits to user {target_user}.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def remove_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Access Denied")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /removecredits user_id amount")
        return
    
    try:
        target_user = int(context.args[0])
        amount = int(context.args[1])
        DatabaseManager.update_credits(target_user, -amount, "Admin Removed", user_id)
        await update.message.reply_text(f"✅ Removed {amount} credits from user {target_user}.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = DatabaseManager.get_all_users()
    total_users = len(users)
    total_credits = sum(user[3] for user in users)
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
📊 <b>BOT STATISTICS</b>
━━━━━━━━━━━━━━━━━━━━

<b>Services Available:</b> 4
<b>Total Users:</b> {total_users}
<b>Total Credits Distributed:</b> {total_credits}
<b>Search Limit:</b> Unlimited
<b>Cost:</b> Free Forever

<b>Supported Services:</b>
✅ Phone Number Verification
✅ UPI/Bank Account Details  
✅ Aadhaar Family Database
✅ Vehicle RC Information

<b>Data Sources:</b>
• Government Databases
• Telecom Operators
• Banking Systems
• RTO Records

🛡️ <i>Verified & Authenticated Data</i>
    """
    
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = """
ℹ️ <b>USER GUIDE</b>
━━━━━━━━━━━━━━━━━━━━

<b>How to Use:</b>

1. <b>Phone Lookup</b>
   - Format: 10-digit number
   - Example: <code>9889662072</code>
   - Returns: Name, Address, Operator

2. <b>UPI Info</b>  
   - Format: username@bank
   - Example: <code>ansh735@ptyes</code>
   - Returns: Bank, Branch, IFSC

3. <b>Aadhaar Family</b>
   - Format: 12-digit number
   - Example: <code>658014451208</code>
   - Returns: Family members, Address

4. <b>Vehicle RC</b>
   - Format: RC Number
   - Example: <code>UP53DY4138</code>
   - Returns: Owner, Model, Registration

🔒 <b>Privacy & Security:</b>
• No data storage
• Encrypted connections
• Professional use only

⚠️ <i>Use responsibly and comply with local laws</i>
    """
    
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    message_text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Check if user is banned
    if DatabaseManager.is_user_banned(user_id):
        await update.message.reply_text("🚫 <b>You are banned from using this bot.</b>", parse_mode=ParseMode.HTML)
        return
    
    # Check channel membership first
    not_joined = await check_channel_membership(update, context)
    if not_joined:
        await update.message.reply_text("❌ Please join the required channels first using /start")
        return
    
    if 'awaiting_input' not in user_data:
        await show_main_menu(update, context)
        return
    
    service_type = user_data['awaiting_input']
    user_data.pop('awaiting_input', None)
    
    # Send processing message
    processing_msg = await update.message.reply_text("🔄 <b>Processing Request...</b>\n\n⏳ Please wait while we fetch the data...", parse_mode=ParseMode.HTML)
    
    try:
        result = None
        
        if service_type == 'phone':
            if not message_text.isdigit() or len(message_text) != 10:
                await processing_msg.edit_text("❌ <b>Invalid Format</b>\n\nPlease enter a valid 10-digit mobile number.")
                return
            result = await APIServices.phone_lookup(message_text)
            response_text = format_phone_result(result, message_text)
        
        elif service_type == 'upi':
            if '@' not in message_text:
                await processing_msg.edit_text("❌ <b>Invalid Format</b>\n\nPlease enter a valid UPI ID (username@bank).")
                return
            result = await APIServices.upi_lookup(message_text)
            response_text = format_upi_result(result, message_text)
        
        elif service_type == 'aadhaar':
            if not message_text.isdigit() or len(message_text) != 12:
                await processing_msg.edit_text("❌ <b>Invalid Format</b>\n\nPlease enter a valid 12-digit Aadhaar number.")
                return
            result = await APIServices.aadhaar_family(message_text)
            response_text = format_aadhaar_result(result, message_text)
        
        elif service_type == 'vehicle':
            if len(message_text) < 5:
                await processing_msg.edit_text("❌ <b>Invalid Format</b>\n\nPlease enter a valid vehicle registration number.")
                return
            result = await APIServices.vehicle_lookup(message_text.upper())
            response_text = format_vehicle_result(result, message_text)
        
        # Auto-delete processing message and send result
        await processing_msg.delete()
        
        if result and response_text:
            keyboard = [[InlineKeyboardButton("🔄 New Search", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Split long messages if needed
            if len(response_text) > 4096:
                for i in range(0, len(response_text), 4096):
                    chunk = response_text[i:i + 4096]
                    await update.message.reply_text(chunk, parse_mode=ParseMode.HTML, reply_markup=reply_markup if i + 4096 >= len(response_text) else None)
            else:
                await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        else:
            await update.message.reply_text("❌ <b>No Data Found</b>\n\nThe requested information is not available in our database.")
    
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        await processing_msg.edit_text("❌ <b>Service Error</b>\n\nAn error occurred while processing your request. Please try again.")

def format_phone_result(data, phone_number):
    if not data or not data.get('success'):
        return "❌ <b>DATA NOT FOUND</b>\n\nThe phone number is not available in our database."
    
    result = data.get('result', [{}])[0]
    
    text = f"""
📱 <b>PHONE NUMBER REPORT</b>
━━━━━━━━━━━━━━━━━━━━

<b>📞 Phone Number:</b> <code>{html.escape(result.get('mobile', phone_number))}</code>
<b>👤 Registered Name:</b> {html.escape(result.get('name', 'Not Available'))}
<b>👨‍👩‍👧‍👦 Father's Name:</b> {html.escape(result.get('father_name', 'Not Available'))}

<b>📍 Location Details:</b>
┣ <b>Operator:</b> {html.escape(result.get('circle', 'Not Available'))}
┣ <b>ID Number:</b> {html.escape(result.get('id_number', 'Not Available'))}
┗ <b>Alt Mobile:</b> {html.escape(result.get('alt_mobile', 'Not Available') or 'Not Available')}

<b>🏠 Complete Address:</b>
<code>{html.escape(result.get('address', 'Not Available'))}</code>

<b>📧 Email:</b> {html.escape(result.get('email', 'Not Available') or 'Not Available')}

⏰ <i>Report Generated: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}</i>
🔒 <i>Official Database Query</i>
    """
    return text

def format_upi_result(data, upi_id):
    if not data:
        return "❌ <b>DATA NOT FOUND</b>\n\nThe UPI ID is not available in our database."
    
    vpa_details = data.get('vpa_details', {})
    bank_details = data.get('bank_details_raw', {})
    
    text = f"""
💳 <b>UPI & BANK DETAILS REPORT</b>
━━━━━━━━━━━━━━━━━━━━

<b>🔗 UPI ID:</b> <code>{html.escape(upi_id)}</code>
<b>👤 Account Holder:</b> {html.escape(vpa_details.get('name', 'Not Available'))}

<b>🏦 Bank Information:</b>
┣ <b>Bank Name:</b> {html.escape(bank_details.get('BANK', 'Not Available'))}
┣ <b>Branch:</b> {html.escape(bank_details.get('BRANCH', 'Not Available'))}
┣ <b>IFSC Code:</b> <code>{html.escape(bank_details.get('IFSC', 'Not Available'))}</code>
┣ <b>Bank Code:</b> {html.escape(bank_details.get('BANKCODE', 'Not Available'))}
┗ <b>Services:</b> {'UPI, IMPS, NEFT, RTGS' if bank_details.get('UPI') else 'Not Available'}

<b>📍 Branch Details:</b>
┣ <b>City:</b> {html.escape(bank_details.get('CITY', 'Not Available'))}
┣ <b>District:</b> {html.escape(bank_details.get('DISTRICT', 'Not Available'))}
┣ <b>State:</b> {html.escape(bank_details.get('STATE', 'Not Available'))}
┗ <b>Centre:</b> {html.escape(bank_details.get('CENTRE', 'Not Available'))}

<b>🏠 Bank Address:</b>
<code>{html.escape(bank_details.get('ADDRESS', 'Not Available'))}</code>

<b>📞 Contact:</b> {html.escape(bank_details.get('CONTACT', 'Not Available') or 'Not Available')}

⏰ <i>Report Generated: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}</i>
🔒 <i>Banking System Query</i>
    """
    return text

def format_aadhaar_result(data, aadhaar):
    if not data:
        return "❌ <b>DATA NOT FOUND</b>\n\nThe Aadhaar number is not available in our database."
    
    members = data.get('memberDetailsList', [])
    
    text = f"""
🆔 <b>AADHAAR FAMILY REPORT</b>
━━━━━━━━━━━━━━━━━━━━

<b>🔢 Reference Aadhaar:</b> <code>{html.escape(aadhaar)}</code>
<b>🏠 Family Card ID:</b> <code>{html.escape(data.get('rcId', 'Not Available'))}</code>
<b>📋 Scheme:</b> {html.escape(data.get('schemeName', 'Not Available'))}

<b>📍 Family Address:</b>
<code>{html.escape(data.get('address', 'Not Available'))}</code>

<b>🗺️ Location Details:</b>
┣ <b>District:</b> {html.escape(data.get('homeDistName', 'Not Available'))}
┣ <b>State:</b> {html.escape(data.get('homeStateName', 'Not Available'))}
┗ <b>Status:</b> {'✅ Verified' if data.get('allowed_onorc') == 'Yes' else '❌ Not Verified'}

<b>👨‍👩‍👧‍👦 FAMILY MEMBERS ({len(members)})</b>
"""
    
    for i, member in enumerate(members, 1):
        relation_emoji = "👤" if member.get('relationship_code') == '1' else "👨" if member.get('relationship_code') == '8' else "👩" if member.get('relationship_code') == '9' else "💑" if member.get('relationship_code') == '6' else "👪"
        text += f"""
{relation_emoji} <b>Member {i}:</b>
┣ <b>Name:</b> {html.escape(member.get('memberName', 'Not Available'))}
┣ <b>Relation:</b> {html.escape(member.get('releationship_name', 'Not Available'))}
┣ <b>Member ID:</b> <code>{html.escape(member.get('memberId', 'Not Available'))}</code>
┗ <b>Aadhaar Status:</b> {'✅ Linked' if member.get('uid') == 'Yes' else '❌ Not Linked'}
"""
    
    text += f"""
⏰ <i>Report Generated: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}</i>
🔒 <i>Government Database Query</i>
    """
    return text

def format_vehicle_result(data, rc_number):
    if not data or not data.get('api_response', {}).get('success'):
        return "❌ <b>DATA NOT FOUND</b>\n\nThe vehicle number is not available in our database."
    
    vehicle_data = data['api_response']['result']['vehicle_response']
    challan_data = data['api_response']['result']['challan_response']
    
    text = f"""
🚗 <b>VEHICLE RC REPORT</b>
━━━━━━━━━━━━━━━━━━━━

<b>🔢 Registration No:</b> <code>{html.escape(vehicle_data.get('asset_number', rc_number))}</code>
<b>👤 Registered Owner:</b> {html.escape(vehicle_data.get('owner_name', 'Not Available'))}

<b>🚙 Vehicle Details:</b>
┣ <b>Make & Model:</b> {html.escape(vehicle_data.get('make_model', 'Not Available'))}
┣ <b>Manufacturer:</b> {html.escape(vehicle_data.get('make_name', 'Not Available'))}
┣ <b>Model Name:</b> {html.escape(vehicle_data.get('model_name', 'Not Available'))}
┣ <b>Fuel Type:</b> ⛽ {html.escape(vehicle_data.get('fuel_type', 'Not Available'))}
┣ <b>Vehicle Type:</b> {html.escape(vehicle_data.get('vehicle_type', 'Not Available'))}
┗ <b>Commercial:</b> {'✅ Yes' if vehicle_data.get('is_commercial') else '❌ No'}

<b>📅 Registration Info:</b>
┣ <b>Registration Date:</b> {html.escape(vehicle_data.get('registration_date', 'Not Available'))}
┣ <b>Registration Year:</b> {html.escape(vehicle_data.get('registration_year', 'Not Available'))}
┣ <b>RTO Office:</b> {html.escape(vehicle_data.get('registration_address', 'Not Available'))}
┗ <b>Previous Insurer:</b> {html.escape(vehicle_data.get('previous_insurer', 'Not Available') or 'Not Available')}

<b>📍 Owner Address:</b>
<code>{html.escape(vehicle_data.get('permanent_address', 'Not Available'))}</code>

<b>⚖️ Legal Status:</b>
┣ <b>Total Challans:</b> {len(challan_data.get('data', []))}
┣ <b>Challan Free Since:</b> {html.escape(challan_data.get('challan_free_since_date', 'Not Available').split('T')[0])}
┗ <b>Policy Status:</b> {'✅ Active' if not vehicle_data.get('previous_policy_expired') else '❌ Expired'}

⏰ <i>Report Generated: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}</i>
🔒 <i>RTO Database Query</i>
    """
    return text

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("addcredits", add_credits))
    application.add_handler(CommandHandler("removecredits", remove_credits))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("🤖 OSINT Bot is running...")
    print("🔍 Professional OSINT Investigation Suite")
    print("💰 Credit & Referral System: ACTIVE")
    print("👑 Admin Panel: ENABLED")
    print("🌐 Flask Server: RUNNING on port 5000")
    application.run_polling()

def main():
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Give Flask a moment to start
    time.sleep(2)
    
    # Start the Telegram bot
    run_bot()

if __name__ == '__main__':
    main()

import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
from datetime import datetime, timedelta

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Database connections
conn = sqlite3.connect('telegram_bot.db', check_same_thread=False)
sudo_conn = sqlite3.connect('sudo_users.db', check_same_thread=False)
report_conn = sqlite3.connect('reports.db', check_same_thread=False)

# Create tables if they do not exist in 'telegram_bot.db'
with conn:
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chat_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER NOT NULL,
            user2_id INTEGER NOT NULL,
            connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            disconnected_at TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            message TEXT,
            media_type TEXT,
            media_id TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pair_id) REFERENCES chat_pairs(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            banned_until TIMESTAMP
        )
    ''')

# Create tables if they do not exist in 'sudo_users.db'
with sudo_conn:
    sudo_conn.execute('''
        CREATE TABLE IF NOT EXISTS sudo_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    ''')

# Create tables if they do not exist in 'reports.db'
with report_conn:
    report_conn.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER,
            reported_id INTEGER,
            reason TEXT,
            media_id TEXT,
            status TEXT DEFAULT 'pending'
        )
    ''')

# Bot owner ID
BOT_OWNER_ID = 123456789  # Replace with the actual bot owner's Telegram user ID
ADMIN_GROUP_ID = -1001234567890  # Replace with the actual admin group chat ID

# Dictionary to store the user pairs in memory
user_pairs = {}

# List to store waiting users
waiting_users = []

async def is_sudo_user(user_id):
    with sudo_conn:
        cursor = sudo_conn.execute(
            "SELECT user_id FROM sudo_users WHERE user_id = ?", (user_id,)
        )
        return cursor.fetchone() is not None

async def start(update: Update, context: CallbackContext) -> None:
    """Send a description of the bot when the command /start is issued."""
    await update.message.reply_text(
        "Welcome to the anonymous chat bot! This bot allows you to connect with random users and chat anonymously. "
        "You can use /connect to find a chat partner, /disconnect to end the chat, /report to report a user, "
        "and /appeal to appeal a ban. Use /rules to see the rules of this bot."
    )

async def help_command(update: Update, context: CallbackContext) -> None:
    """Send a list of available commands when the command /help is issued."""
    await update.message.reply_text(
        "/start - Show the bot description\n"
        "/connect - Find a chat partner\n"
        "/disconnect - End the chat\n"
        "/report <reason> - Report a user\n"
        "/appeal - Appeal a ban\n"
        "/rules - Show the rules\n"
        "/ban <user_id> <reason> - Ban a user (admin only)\n"
        "/unban <user_id> - Unban a user (admin only)"
    )

async def rules(update: Update, context: CallbackContext) -> None:
    """Send the rules of the bot when the command /rules is issued."""
    await update.message.reply_text(
        "Rules of the bot:\n"
        "1. Be respectful to others.\n"
        "2. Do not share personal information.\n"
        "3. Do not engage in illegal activities.\n"
        "4. Follow Telegram's terms of service.\n"
        "Violating these rules may result in a ban."
    )

async def add_sudo(update: Update, context: CallbackContext) -> None:
    """Add a sudo user."""
    user_id = update.message.chat_id
    if user_id != BOT_OWNER_ID:
        await update.message.reply_text('You do not have permission to use this command.')
        return

    try:
        target_id = int(update.message.text.split()[1])
        username = update.message.text.split()[2]
    except (IndexError, ValueError):
        await update.message.reply_text('Usage: /addsudo <user_id> <username>')
        return

    with sudo_conn:
        sudo_conn.execute(
            "INSERT INTO sudo_users (user_id, username) VALUES (?, ?)",
            (target_id, username)
        )
    await update.message.reply_text(f'User {username} has been added as a sudo user.')

async def del_sudo(update: Update, context: CallbackContext) -> None:
    """Delete a sudo user."""
    user_id = update.message.chat_id
    if user_id != BOT_OWNER_ID:
        await update.message.reply_text('You do not have permission to use this command.')
        return

    try:
        target_id = int(update.message.text.split()[1])
    except (IndexError, ValueError):
        await update.message.reply_text('Usage: /delsudo <user_id>')
        return

    with sudo_conn:
        sudo_conn.execute(
            "DELETE FROM sudo_users WHERE user_id = ?",
            (target_id,)
        )
    await update.message.reply_text(f'User {target_id} has been removed as a sudo user.')

async def ban_user(update: Update, context: CallbackContext) -> None:
    """Ban a user."""
    user_id = update.message.chat_id
    if not (await is_sudo_user(user_id)) and user_id != BOT_OWNER_ID:
        await update.message.reply_text('You do not have permission to use this command.')
        return

    try:
        target_id = int(update.message.text.split()[1])
        reason = ' '.join(update.message.text.split()[2:])
    except (IndexError, ValueError):
        await update.message.reply_text('Usage: /ban <user_id> <reason>')
        return

    if target_id == BOT_OWNER_ID or await is_sudo_user(target_id):
        await update.message.reply_text('You cannot ban this user because they are an admin.')
        return

    with conn:
        conn.execute(
            "INSERT INTO banned_users (user_id, reason, banned_until) VALUES (?, ?, ?)",
            (target_id, reason, None)
        )
    await update.message.reply_text(f'User {target_id} has been banned for: {reason}')

async def unban_user(update: Update, context: CallbackContext) -> None:
    """Unban a user."""
    user_id = update.message.chat_id
    if not (await is_sudo_user(user_id)) and user_id != BOT_OWNER_ID:
        await update.message.reply_text('You do not have permission to use this command.')
        return

    try:
        target_id = int(update.message.text.split()[1])
    except (IndexError, ValueError):
        await update.message.reply_text('Usage: /unban <user_id>')
        return

    with conn:
        conn.execute(
            "DELETE FROM banned_users WHERE user_id = ?",
            (target_id,)
        )
    await update.message.reply_text(f'User {target_id} has been unbanned.')

async def connect(update: Update, context: CallbackContext) -> None:
    """Connect the user to a random chat partner."""
    user_id = update.message.chat_id

    cursor = conn.execute("SELECT reason, banned_until FROM banned_users WHERE user_id = ?", (user_id,))
    banned_user = cursor.fetchone()
    if banned_user:
        reason, banned_until = banned_user
        await update.message.reply_text(f'You are banned from using this bot until {banned_until}. Reason: {reason}')
        return

    if user_id in user_pairs:
        await update.message.reply_text('You are already connected to a chat partner.')
        return

    if waiting_users:
        partner_id = waiting_users.pop()
        user_pairs[user_id] = partner_id
        user_pairs[partner_id] = user_id

        # Save chat pair to the database
        with conn:
            conn.execute(
                "INSERT INTO chat_pairs (user1_id, user2_id) VALUES (?, ?)",
                (user_id, partner_id)
            )

        await update.message.reply_text('You are now connected to a chat partner. Type /disconnect to end the chat.')
        await context.bot.send_message(partner_id, 'You are now connected to a chat partner. Type /disconnect to end the chat.')
    else:
        waiting_users.append(user_id)
        await update.message.reply_text('Waiting for a chat partner...')

async def disconnect(update: Update, context: CallbackContext) -> None:
    """Disconnect the user from the chat partner."""
    user_id = update.message.chat_id

    if user_id not in user_pairs:
        await update.message.reply_text('You are not connected to any chat partner.')
        return

    partner_id = user_pairs.pop(user_id)
    user_pairs.pop(partner_id)

    # Update disconnect time in the database
    with conn:
        conn.execute(
            "UPDATE chat_pairs SET disconnected_at = CURRENT_TIMESTAMP WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)",
            (user_id, partner_id, partner_id, user_id)
        )

    await update.message.reply_text('You have been disconnected.')
    await context.bot.send_message(partner_id, 'Your chat partner has disconnected.')

async def message_handler(update: Update, context: CallbackContext) -> None:
    """Forward messages and media between connected users."""
    user_id = update.message.chat_id

    if user_id not in user_pairs:
        await update.message.reply_text('You are not connected to any chat partner. Type /connect to find a chat partner.')
        return

    partner_id = user_pairs[user_id]

    if update.message.text:
        message = update.message.text
        media_type = None
        media_id = None

        # Save message to the database
        with conn:
            cursor = conn.execute(
                "SELECT id FROM chat_pairs WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)",
                (user_id, partner_id, partner_id, user_id)
            )
            pair_id = cursor.fetchone()[0]
            conn.execute(
                "INSERT INTO messages (pair_id, sender_id, message, media_type, media_id) VALUES (?, ?, ?, ?, ?)",
                (pair_id, user_id, message, media_type, media_id)
            )

        await context.bot.send_message(partner_id, f"User: {message}")

    elif update.message.photo:
        media_id = update.message.photo[-1].file_id
        media_type = 'photo'
        message = None

        # Save photo to the database
        with conn:
            cursor = conn.execute(
                "SELECT id FROM chat_pairs WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)",
                (user_id, partner_id, partner_id, user_id)
            )
            pair_id = cursor.fetchone()[0]
            conn.execute(
                "INSERT INTO messages (pair_id, sender_id, message, media_type, media_id) VALUES (?, ?, ?, ?, ?)",
                (pair_id, user_id, message, media_type, media_id)
            )

        await context.bot.send_photo(partner_id, media_id)

    elif update.message.video:
        media_id = update.message.video.file_id
        media_type = 'video'
        message = None

        # Save video to the database
        with conn:
            cursor = conn.execute(
                "SELECT id FROM chat_pairs WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)",
                (user_id, partner_id, partner_id, user_id)
            )
            pair_id = cursor.fetchone()[0]
            conn.execute(
                "INSERT INTO messages (pair_id, sender_id, message, media_type, media_id) VALUES (?, ?, ?, ?, ?)",
                (pair_id, user_id, message, media_type, media_id)
            )

        await context.bot.send_video(partner_id, media_id)

    elif update.message.animation:
        media_id = update.message.animation.file_id
        media_type = 'animation'
        message = None

        # Save animation (GIF) to the database
        with conn:
            cursor = conn.execute(
                "SELECT id FROM chat_pairs WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)",
                (user_id, partner_id, partner_id, user_id)
            )
            pair_id = cursor.fetchone()[0]
            conn.execute(
                "INSERT INTO messages (pair_id, sender_id, message, media_type, media_id) VALUES (?, ?, ?, ?, ?)",
                (pair_id, user_id, message, media_type, media_id)
            )

        await context.bot.send_animation(partner_id, media_id)

async def report(update: Update, context: CallbackContext) -> None:
    """Report a user."""
    user_id = update.message.chat_id
    partner_id = user_pairs.get(user_id)
    
    if partner_id is None:
        await update.message.reply_text('You are not connected to any chat partner.')
        return
    
    reason = ' '.join(update.message.text.split()[1:])
    media_id = update.message.photo[-1].file_id if update.message.photo else None

    # Save report to the database
    with report_conn:
        cursor = report_conn.execute(
            "INSERT INTO reports (reporter_id, reported_id, reason, media_id) VALUES (?, ?, ?, ?) RETURNING id",
            (user_id, partner_id, reason, media_id)
        )
        report_id = cursor.fetchone()[0]
    
    # Send report to admin group
    keyboard = [
        [InlineKeyboardButton("Accept", callback_data=f"accept_{report_id}"),
         InlineKeyboardButton("Reject", callback_data=f"reject_{report_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    report_message = f"New report received!\n\nReport ID: {report_id}\nReporter ID: {user_id}\nReported ID: {partner_id}\nReason: {reason}"
    if media_id:
        await context.bot.send_photo(ADMIN_GROUP_ID, media_id, caption=report_message, reply_markup=reply_markup)
    else:
        await context.bot.send_message(ADMIN_GROUP_ID, report_message, reply_markup=reply_markup)

    await update.message.reply_text(f'Report submitted successfully! Report ID: {report_id}')

async def appeal(update: Update, context: CallbackContext) -> None:
    """Appeal a ban."""
    user_id = update.message.chat_id
    reason = ' '.join(update.message.text.split()[1:]) if len(update.message.text.split()) > 1 else 'No reason provided'

    # Save appeal to the database
    with report_conn:
        cursor = report_conn.execute(
            "INSERT INTO reports (reporter_id, reported_id, reason) VALUES (?, ?, ?) RETURNING id",
            (user_id, user_id, reason)
        )
        appeal_id = cursor.fetchone()[0]
    
    # Send appeal to admin group
    keyboard = [
        [InlineKeyboardButton("Accept", callback_data=f"accept_{appeal_id}"),
         InlineKeyboardButton("Reject", callback_data=f"reject_{appeal_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    appeal_message = f"New appeal received!\n\nAppeal ID: {appeal_id}\nUser ID: {user_id}\nReason: {reason}"
    await context.bot.send_message(ADMIN_GROUP_ID, appeal_message, reply_markup=reply_markup)

    await update.message.reply_text(f'Appeal submitted successfully! Appeal ID: {appeal_id}')

async def handle_callback(update: Update, context: CallbackContext) -> None:
    """Handle button callbacks for accepting/rejecting reports and appeals."""
    query = update.callback_query
    await query.answer()

    callback_data = query.data.split('_')
    action = callback_data[0]
    item_id = int(callback_data[1])

    with report_conn:
        cursor = report_conn.execute(
            "SELECT reporter_id, reported_id FROM reports WHERE id = ?",
            (item_id,)
        )
        report = cursor.fetchone()

    if not report:
        await query.edit_message_text(text="Report/Appeal not found.")
        return

    reporter_id, reported_id = report

    if action == 'accept':
        if 'appeal' in callback_data:
            # Unban the user
            with conn:
                conn.execute(
                    "DELETE FROM banned_users WHERE user_id = ?",
                    (reported_id,)
                )
            await query.edit_message_text(text=f"Appeal {item_id} has been accepted. User {reported_id} is unbanned.")
            await context.bot.send_message(reported_id, f'Your appeal (ID: {item_id}) has been accepted. You have been unbanned.')
            await context.bot.send_message(reporter_id, f'The appeal for user {reported_id} (ID: {item_id}) has been accepted.')
        else:
            # Ban the user
            with conn:
                cursor = conn.execute(
                    "SELECT user_id FROM banned_users WHERE user_id = ?",
                    (reported_id,)
                )
                if cursor.fetchone() is None:
                    conn.execute(
                        "INSERT INTO banned_users (user_id, reason, banned_until) VALUES (?, ?, ?)",
                        (reported_id, f"Report ID: {item_id}", None)
                    )
                    await query.edit_message_text(text=f"Report {item_id} has been accepted. User {reported_id} is banned.")
                    await context.bot.send_message(reporter_id, f'Your report (ID: {item_id}) has been accepted.')
                else:
                    await query.edit_message_text(text=f"User {reported_id} is already banned.")
                    await context.bot.send_message(reporter_id, f'Your report (ID: {item_id}) has been accepted, but user {reported_id} was already banned.')

    elif action == 'reject':
        if 'appeal' in callback_data:
            await query.edit_message_text(text=f"Appeal {item_id} has been rejected.")
            await context.bot.send_message(reported_id, f'Your appeal (ID: {item_id}) has been rejected. The ban remains in effect.')
            await context.bot.send_message(reporter_id, f'The appeal for user {reported_id} (ID: {item_id}) has been rejected.')
        else:
            await query.edit_message_text(text=f"Report {item_id} has been rejected.")
            await context.bot.send_message(reporter_id, f'Your report (ID: {item_id}) has been rejected.')
            
def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token("YOUR_TOKEN_HERE").build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("rules", rules))
    application.add_handler(CommandHandler("addsudo", add_sudo))
    application.add_handler(CommandHandler("delsudo", del_sudo))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("connect", connect))
    application.add_handler(CommandHandler("disconnect", disconnect))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("appeal", appeal))
    application.add_handler(CallbackQueryHandler(handle_callback))

    # on non command i.e message - forward the message or media to the chat partner
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, message_handler))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, message_handler))
    application.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, message_handler))
    application.add_handler(MessageHandler(filters.ANIMATION & filters.ChatType.PRIVATE, message_handler))

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()

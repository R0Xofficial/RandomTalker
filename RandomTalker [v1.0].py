import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# Create or connect to SQLite databases
conn_users = sqlite3.connect('bot_users.db')
conn_sudo = sqlite3.connect('bot_sudo.db')
cursor_users = conn_users.cursor()
cursor_sudo = conn_sudo.cursor()

# Create tables for users, pairs, banned users, and sudo users
cursor_users.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)''')
cursor_users.execute('''CREATE TABLE IF NOT EXISTS pairs (user1 INTEGER, user2 INTEGER)''')
cursor_users.execute('''CREATE TABLE IF NOT EXISTS banned_users (id INTEGER PRIMARY KEY)''')
cursor_sudo.execute('''CREATE TABLE IF NOT EXISTS sudo_users (id INTEGER PRIMARY KEY)''')
conn_users.commit()
conn_sudo.commit()

# Add user to the database
def add_user(user_id):
    cursor_users.execute("INSERT INTO users (id) VALUES (?)", (user_id,))
    conn_users.commit()

# Remove user from the database
def remove_user(user_id):
    cursor_users.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn_users.commit()

# Check if a user is banned
def is_banned(user_id):
    cursor_users.execute("SELECT id FROM banned_users WHERE id=?", (user_id,))
    return cursor_users.fetchone() is not None

# Ban a user
def ban_user(user_id):
    cursor_users.execute("INSERT OR IGNORE INTO banned_users (id) VALUES (?)", (user_id,))
    conn_users.commit()

# Unban a user
def unban_user(user_id):
    cursor_users.execute("DELETE FROM banned_users WHERE id=?", (user_id,))
    conn_users.commit()

# Check if a user is sudo
def is_sudo(user_id):
    cursor_sudo.execute("SELECT id FROM sudo_users WHERE id=?", (user_id,))
    return cursor_sudo.fetchone() is not None

# Add sudo user
def add_sudo_user(user_id):
    cursor_sudo.execute("INSERT OR IGNORE INTO sudo_users (id) VALUES (?)", (user_id,))
    conn_sudo.commit()

# Remove sudo user
def remove_sudo_user(user_id):
    cursor_sudo.execute("DELETE FROM sudo_users WHERE id=?", (user_id,))
    conn_sudo.commit()

# Find a pair of users
def find_pair():
    cursor_users.execute("SELECT id FROM users")
    users = [row[0] for row in cursor_users.fetchall()]
    if len(users) >= 2:
        user1, user2 = users[0], users[1]
        cursor_users.execute("INSERT INTO pairs (user1, user2) VALUES (?, ?)", (user1, user2))
        remove_user(user1)
        remove_user(user2)
        conn_users.commit()
        return user1, user2
    return None, None

# Get partner
def get_partner(user_id):
    cursor_users.execute("SELECT user2 FROM pairs WHERE user1=?", (user_id,))
    partner = cursor_users.fetchone()
    if not partner:
        cursor_users.execute("SELECT user1 FROM pairs WHERE user2=?", (user_id,))
        partner = cursor_users.fetchone()
    return partner[0] if partner else None

# Disconnect a pair
def disconnect_pair(user_id):
    cursor_users.execute("DELETE FROM pairs WHERE user1=? OR user2=?", (user_id, user_id))
    conn_users.commit()

# Command /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if update.effective_chat.type != "private":
        return

    if is_banned(user_id):
        await update.message.reply_text("You are banned from using this bot.")
        return

    cursor_users.execute("SELECT id FROM users WHERE id=?", (user_id,))
    if not cursor_users.fetchone():
        add_user(user_id)
        await update.message.reply_text("Welcome! Please wait while I find a partner for you...")

    user1, user2 = find_pair()
    if user1 and user2:
        await context.bot.send_message(chat_id=user1, text="You are now connected to a partner. Start chatting!")
        await context.bot.send_message(chat_id=user2, text="You are now connected to a partner. Start chatting!")

# Command /stop
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = get_partner(user_id)

    if partner_id:
        disconnect_pair(user_id)
        await context.bot.send_message(chat_id=partner_id, text="Your partner has ended the chat.")
        await update.message.reply_text("You have ended the chat.")
    else:
        await update.message.reply_text("You are not currently in a chat.")

# Handle messages
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ensure bot reacts only to private messages
    if update.message.chat.type != "private":
        return

    user_id = update.effective_user.id
    partner_id = get_partner(user_id)

    if partner_id:
        if update.message.text:  # Forward text messages
            await context.bot.send_message(chat_id=partner_id, text=f"User: {update.message.text}")
        elif update.message.photo:  # Forward photo messages
            photo_file = await update.message.photo[-1].get_file()
            await context.bot.send_photo(chat_id=partner_id, photo=photo_file.file_id)
        elif update.message.animation:  # Forward GIFs
            animation_file = await update.message.animation.get_file()
            await context.bot.send_animation(chat_id=partner_id, animation=animation_file.file_id)
        elif update.message.video:  # Forward videos
            video_file = await update.message.video.get_file()
            await context.bot.send_video(chat_id=partner_id, video=video_file.file_id)
    else:
        await update.message.reply_text("You are not currently connected to a partner. Use /start to find someone!")

# Ban command
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_sudo(update.effective_user.id):
        await update.message.reply_text("You are banned. Contact here for appeal: @R0Xofficial")
        return

    if context.args:
        user_id = int(context.args[0])
        ban_user(user_id)
        await update.message.reply_text(f"User {user_id} has been banned.")
    else:
        await update.message.reply_text("Please provide a user ID to ban.")

# Unban command
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_sudo(update.effective_user.id):
        await update.message.reply_text("You do not have permission to use this command.")
        return

    if context.args:
        user_id = int(context.args[0])
        unban_user(user_id)
        await update.message.reply_text(f"User {user_id} has been unbanned.")
    else:
        await update.message.reply_text("Please provide a user ID to unban.")

# Main bot function
if __name__ == "__main__":
    app = ApplicationBuilder().token("7842288516:AAEOA0Yy5OHMPJ_1w7OOYagJca_1U9Ii6OU").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(MessageHandler(filters.PHOTO, message_handler))  # Handle photos
    app.add_handler(MessageHandler(filters.ANIMATION, message_handler))  # Handle GIFs
    app.add_handler(MessageHandler(filters.VIDEO, message_handler))  # Handle videos

    print("Bot is running!")
    app.run_polling()

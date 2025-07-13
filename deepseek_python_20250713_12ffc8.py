import os
import logging
import time
import schedule
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext,
    MessageHandler,
    Filters
)
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS').split(',')]
CHECK_INTERVAL = 3  # minutes

# Database simulation (in production, use a real database)
DOMAINS_DB = {
    'main': set(),
    'alternative': set(),
    'blocked': set()
}

# Trustpositif DNS IPs
TRUSTPOSITIF_DNS = [
    '180.131.144.144',
    '180.131.145.145'
]

def is_domain_blocked(domain: str) -> bool:
    """Check if domain is blocked by Trustpositif/IPOS/Kominfo"""
    try:
        for dns_ip in TRUSTPOSITIF_DNS:
            # Check against each Trustpositif DNS server
            response = requests.get(
                f'http://{dns_ip}/api/check?domain={domain}',
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('blocked', False):
                    return True
    except Exception as e:
        logger.error(f"Error checking domain {domain}: {e}")
    return False

def check_domains(context: CallbackContext):
    """Periodic domain checking job"""
    logger.info("Running domain check...")
    newly_blocked = set()
    
    # Check main domains
    for domain in DOMAINS_DB['main']:
        if domain in DOMAINS_DB['blocked']:
            continue
        if is_domain_blocked(domain):
            DOMAINS_DB['blocked'].add(domain)
            newly_blocked.add(domain)
    
    # Check alternative domains
    for domain in DOMAINS_DB['alternative']:
        if domain in DOMAINS_DB['blocked']:
            continue
        if is_domain_blocked(domain):
            DOMAINS_DB['blocked'].add(domain)
            newly_blocked.add(domain)
    
    # Send notifications for newly blocked domains
    if newly_blocked:
        message = "🚨 Domain Blocked Alert 🚨\n\n"
        message += "The following domains are now blocked:\n"
        message += "\n".join(f"- {domain}" for domain in newly_blocked)
        
        for admin_id in ADMIN_IDS:
            context.bot.send_message(
                chat_id=admin_id,
                text=message,
                parse_mode='Markdown'
            )

def start(update: Update, context: CallbackContext):
    """Send welcome message"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Main Domain", callback_data='add_main')],
        [InlineKeyboardButton("➕ Add Alternative Domain", callback_data='add_alt')],
        [InlineKeyboardButton("📋 List Domains", callback_data='list_domains')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        "Welcome to Nawala Domain Monitor Bot!\n\n"
        "This bot will monitor your domains 24/7 and alert you if any get blocked.\n"
        "Check interval: every 3 minutes.",
        reply_markup=reply_markup
    )

def button_handler(update: Update, context: CallbackContext):
    """Handle inline button presses"""
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        query.edit_message_text(text="❌ You are not authorized to use this bot.")
        return
    
    if query.data == 'add_main':
        query.edit_message_text(text="Please send the main domain to add (e.g., example.com):")
        context.user_data['awaiting_domain'] = 'main'
    elif query.data == 'add_alt':
        query.edit_message_text(text="Please send the alternative domain to add (e.g., example.net):")
        context.user_data['awaiting_domain'] = 'alternative'
    elif query.data == 'list_domains':
        list_domains(query, context)

def handle_domain_input(update: Update, context: CallbackContext):
    """Handle domain input from user"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    
    if 'awaiting_domain' not in context.user_data:
        return
    
    domain_type = context.user_data['awaiting_domain']
    domain = update.message.text.strip().lower()
    
    # Simple domain validation
    if not (domain.startswith('http://') or domain.startswith('https://')):
        domain = f'http://{domain}'
    
    try:
        # Extract domain name
        from urllib.parse import urlparse
        parsed = urlparse(domain)
        domain_name = parsed.netloc or parsed.path.split('/')[0]
        
        if not domain_name:
            raise ValueError("Invalid domain format")
        
        # Remove www. if present
        domain_name = domain_name.replace('www.', '')
        
        # Add to database
        DOMAINS_DB[domain_type].add(domain_name)
        
        update.message.reply_text(f"✅ Domain {domain_name} added to {domain_type} list!")
        
        # Check immediately
        if is_domain_blocked(domain_name):
            DOMAINS_DB['blocked'].add(domain_name)
            update.message.reply_text(f"⚠️ Warning: Domain {domain_name} is currently blocked!")
        
    except Exception as e:
        update.message.reply_text(f"❌ Error: {str(e)}\nPlease send a valid domain (e.g., example.com)")
    
    del context.user_data['awaiting_domain']

def list_domains(query, context: CallbackContext):
    """List all monitored domains"""
    message = "📋 Monitored Domains\n\n"
    
    if DOMAINS_DB['main']:
        message += "🔹 Main Domains:\n"
        message += "\n".join(
            f"- {domain} {'🚫' if domain in DOMAINS_DB['blocked'] else '✅'}"
            for domain in DOMAINS_DB['main']
        )
        message += "\n\n"
    else:
        message += "No main domains added yet.\n\n"
    
    if DOMAINS_DB['alternative']:
        message += "🔸 Alternative Domains:\n"
        message += "\n".join(
            f"- {domain} {'🚫' if domain in DOMAINS_DB['blocked'] else '✅'}"
            for domain in DOMAINS_DB['alternative']
        )
    else:
        message += "No alternative domains added yet."
    
    query.edit_message_text(text=message)

def error_handler(update: Update, context: CallbackContext):
    """Log errors"""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

def main():
    """Start the bot"""
    # Create the Updater and pass it your bot's token.
    updater = Updater(TOKEN, use_context=True)
    
    # Get the dispatcher to register handlers
    dp = updater.dispatcher
    
    # Add command handlers
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_domain_input))
    
    # Log all errors
    dp.add_error_handler(error_handler)
    
    # Schedule domain checking
    job_queue = updater.job_queue
    job_queue.run_repeating(
        callback=check_domains,
        interval=CHECK_INTERVAL * 60,
        first=10
    )
    
    # Start the Bot
    updater.start_polling()
    
    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()

if __name__ == '__main__':
    main()
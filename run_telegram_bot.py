import os
import sys

# Ensure parent directory is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

from dotenv import load_dotenv

# Load configurations
load_dotenv()
load_dotenv(dotenv_path='.env.local', override=True)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    print("⚠️ Warning: TELEGRAM_BOT_TOKEN is not set in .env.local.")
    print("Please create a bot via @BotFather in Telegram, add the token to .env.local, and rerun this script.")
    sys.exit(0)

try:
    import telebot
except ImportError:
    print("❌ Error: The 'pyTelegramBotAPI' package is not installed. Run 'pip install pyTelegramBotAPI' to run the Telegram bot.")
    sys.exit(1)

from agents.telegram_bot import setup_bot_handlers

def main():
    print("🤖 Starting Telegram Bot daemon...")
    bot = telebot.TeleBot(TOKEN)
    setup_bot_handlers(bot)
    
    print("✅ Bot is online. Listening for messages...")
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
    except Exception as e:
        print(f"❌ Bot crashed with exception: {e}")

if __name__ == "__main__":
    main()

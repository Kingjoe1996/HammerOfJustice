import os
import time
from bot import bot
from config import BOT_TOKEN

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Please create a .env file with your bot token:")
        print("DISCORD_BOT_TOKEN=your_token_here")
        exit(1)
    
    # Create data directory if it doesn't exist
    os.makedirs("data", exist_ok=True)
    
    # Add a small delay to ensure filesystem is ready
    time.sleep(1)
    
    try:
        print("Starting Discord Strike Bot...")
        print("Note: Initial database setup might take a few seconds")
        bot.run(BOT_TOKEN)
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Error running bot: {e}")
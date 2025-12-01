import os
import time
import asyncio
from bot import bot
from config import BOT_TOKEN
import aiohttp
from aiohttp import web

async def health_check(request):
    """Simple health check endpoint"""
    return web.Response(text="OK")

async def start_web_server():
    """Start a simple web server for health checks"""
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="HammerOfJustice Bot is running"))
    app.router.add_get('/health', health_check)
    app.router.add_get('/ping', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Use PORT environment variable (Render provides this)
    port = int(os.getenv('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print(f"Health check server started on port {port}")
    return runner

async def keep_alive_ping():
    """Periodically ping external services to keep the bot awake"""
    # List of services to ping (prevents Render from spinning down)
    ping_urls = [
        "https://hammerofjustice.omender.com/health",
        "https://httpstat.us/200"
    ]
    
    while True:
        for url in ping_urls:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as response:
                        if response.status == 200:
                            print(f"Pinged {url} successfully at {time.ctime()}")
            except Exception as e:
                print(f"Error pinging {url}: {e}")
        
        # Wait 10 minutes between pings
        await asyncio.sleep(600)  # 600 seconds = 10 minutes

async def main():
    """Main async function to run everything"""
    if not BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        exit(1)
    
    # Create data directory if it doesn't exist
    os.makedirs("data", exist_ok=True)
    time.sleep(1)
    
    print("Starting Discord Strike Bot with keep-alive system...")
    
    # Start the health check web server
    web_runner = await start_web_server()
    
    # Start the keep-alive ping task
    ping_task = asyncio.create_task(keep_alive_ping())
    
    # Start the Discord bot
    try:
        print("Starting Discord bot...")
        await bot.start(BOT_TOKEN)
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Error running bot: {e}")
    finally:
        # Cleanup
        await bot.close()
        await web_runner.cleanup()
        ping_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())

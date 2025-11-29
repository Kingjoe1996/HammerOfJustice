import discord
from datetime import datetime
import asyncio
import logging
from strike_manager import StrikeManager
from config import DASHBOARD_CHANNEL_NAME

logger = logging.getLogger(__name__)

class StrikeDashboard:
    def __init__(self, bot, strike_manager):
        self.bot = bot
        self.strike_manager = strike_manager
        self.update_task = None
    
    def format_time_remaining(self, reset_time):
        """Format time remaining until strike reset"""
        if not reset_time:
            return "No active strikes"
        
        now = datetime.now()
        if reset_time <= now:
            return "Resetting soon..."
        
        delta = reset_time - now
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        
        if days > 0:
            return f"{days}d {hours}h"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
    async def create_dashboard_embed(self):
        """Create the dashboard embed"""
        embed = discord.Embed(
            title="🚨 Active Strikes Dashboard",
            description="Real-time monitoring of active strikes",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        
        try:
            active_strikes = self.strike_manager.get_all_active_strikes()
            
            if not active_strikes:
                embed.add_field(
                    name="No Active Strikes",
                    value="There are currently no active strikes.",
                    inline=False
                )
                return embed
            
            # Group strikes by user
            user_strikes = {}
            for strike in active_strikes:
                user_id = strike[1]
                if user_id not in user_strikes:
                    user_strikes[user_id] = []
                user_strikes[user_id].append(strike)
            
            for user_id, strikes in user_strikes.items():
                try:
                    user = await self.bot.fetch_user(user_id)
                    user_display = f"{user.name}#{user.discriminator}"
                except:
                    user_display = f"Unknown User ({user_id})"
                
                strike_count = len(strikes)
                latest_strike = strikes[0]  # Most recent strike
                
                # Get violation count from the database
                violation_count = self.strike_manager.db.get_violation_count(user_id)
                
                # Get moderator info for latest strike
                try:
                    moderator = await self.bot.fetch_user(latest_strike[2])
                    mod_display = f"{moderator.name}#{moderator.discriminator}"
                except:
                    mod_display = f"Unknown ({latest_strike[2]})"
                
                # Calculate next reset (earliest reset time among active strikes)
                try:
                    reset_times = [datetime.fromisoformat(strike[5]) for strike in strikes]
                    next_reset = min(reset_times)
                    reset_text = self.format_time_remaining(next_reset)
                except Exception as e:
                    logger.error(f"Error calculating reset time: {e}")
                    reset_text = "Error"
                
                # Truncate reason if too long
                reason = latest_strike[3]
                if len(reason) > 50:
                    reason = reason[:47] + "..."
                
                embed.add_field(
                    name=f"👤 {user_display}",
                    value=(
                        f"**Strikes:** {strike_count}/3\n"
                        f"**Violations:** {violation_count}\n"
                        f"**Reset In:** {reset_text}\n"
                        f"**Last Mod:** {mod_display}\n"
                        f"**Last Reason:** {reason}"
                    ),
                    inline=True
                )
            
        except Exception as e:
            logger.error(f"Error creating dashboard embed: {e}")
            embed.add_field(
                name="Error",
                value="Unable to load strike data. Please check bot logs.",
                inline=False
            )
        
        embed.set_footer(text="Updated")
        return embed
    
    async def update_dashboard(self):
        """Update the dashboard message"""
        try:
            channel_id, message_id = self.strike_manager.db.get_dashboard_message()
            
            if not channel_id or not message_id:
                logger.info("No dashboard message found, creating new one")
                await self.create_new_dashboard()
                return
            
            channel = self.bot.get_channel(channel_id)
            if not channel:
                logger.error(f"Dashboard channel {channel_id} not found")
                return
            
            try:
                message = await channel.fetch_message(message_id)
                embed = await self.create_dashboard_embed()
                await message.edit(embed=embed)
                logger.debug("Dashboard updated successfully")
            except discord.NotFound:
                logger.info("Dashboard message not found, creating new one")
                await self.create_new_dashboard()
            except Exception as e:
                logger.error(f"Error updating dashboard: {e}")
                
        except Exception as e:
            logger.error(f"Error in update_dashboard: {e}")
    
    async def create_new_dashboard(self):
        """Create a new dashboard message"""
        try:
            # Find dashboard channel
            dashboard_channel = None
            for guild in self.bot.guilds:
                for channel in guild.text_channels:
                    if channel.name == DASHBOARD_CHANNEL_NAME:
                        dashboard_channel = channel
                        break
                if dashboard_channel:
                    break
            
            if not dashboard_channel:
                # Create the dashboard channel if it doesn't exist
                try:
                    guild = self.bot.guilds[0]  # Use first guild
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(read_messages=True),
                        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
                    }
                    
                    dashboard_channel = await guild.create_text_channel(
                        DASHBOARD_CHANNEL_NAME,
                        overwrites=overwrites,
                        reason="Strike system dashboard"
                    )
                    logger.info(f"Created dashboard channel: {DASHBOARD_CHANNEL_NAME}")
                except Exception as e:
                    logger.error(f"Error creating dashboard channel: {e}")
                    return
            
            embed = await self.create_dashboard_embed()
            message = await dashboard_channel.send(embed=embed)
            
            # Save message ID
            await self.strike_manager.db.save_dashboard_message(dashboard_channel.id, message.id)
            logger.info("New dashboard message created")
            
        except Exception as e:
            logger.error(f"Error creating new dashboard: {e}")
    
    async def start_auto_updates(self, interval=30):
        """Start automatic dashboard updates"""
        # Wait for bot to be fully ready
        await asyncio.sleep(10)
        self.update_task = self.bot.loop.create_task(self._update_loop(interval))
        logger.info("Dashboard auto-updates started")
    
    async def _update_loop(self, interval):
        """Background task to update dashboard periodically"""
        await self.bot.wait_until_ready()
        
        # Initial delay
        await asyncio.sleep(15)
        
        while not self.bot.is_closed():
            try:
                # Reset expired strikes
                reset_count = await self.strike_manager.reset_expired_strikes()
                if reset_count > 0:
                    logger.info(f"Reset {reset_count} expired strikes")
                
                # Update dashboard
                await self.update_dashboard()
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Error in dashboard update loop: {e}")
                await asyncio.sleep(interval)
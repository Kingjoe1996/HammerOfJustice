import discord
from discord import app_commands
import logging
from strike_manager import StrikeManager
from dashboard import StrikeDashboard
from config import MODERATOR_ROLES, MOD_LOG_CHANNEL_NAME, PUNISHMENT_ESCALATION
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StrikeBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.strike_manager = None
        self.dashboard = None
    
    async def setup_hook(self):
        """Called when the bot is starting up"""
        logger.info("Starting bot setup...")
        
        # Initialize managers
        self.strike_manager = StrikeManager(self)
        self.dashboard = StrikeDashboard(self, self.strike_manager)
        
        # Sync context menus
        await self.tree.sync()
        logger.info("Context menus synced")
        
        # Start dashboard updates
        await self.dashboard.start_auto_updates(interval=30)
        logger.info("Dashboard auto-updates started")
    
    async def on_ready(self):
        logger.info(f'{self.user} has logged in!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        
        # Create dashboard if it doesn't exist
        await self.dashboard.create_new_dashboard()
    
    async def log_strike_action(self, user, moderator, reason, strike_count, violation_count, action_type="strike"):
        """Log strike actions to mod log channel"""
        for guild in self.guilds:
            if user in guild.members:
                mod_log_channel = await find_mod_log_channel(guild)
                if mod_log_channel:
                    if action_type == "strike":
                        title = "🔨 Strike Issued"
                        color = discord.Color.orange()
                    elif action_type == "remove_strike":
                        title = "🔧 Strike Removed"
                        color = discord.Color.blue()
                    elif action_type == "reset_strikes":
                        title = "🔄 Strikes Reset"
                        color = discord.Color.green()
                    else:
                        title = "📊 Strike Checked"
                        color = discord.Color.light_grey()
                    
                    embed = discord.Embed(
                        title=title,
                        color=color,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=True)
                    embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=True)
                    
                    if action_type != "check":
                        embed.add_field(name="Current Strikes", value=f"{strike_count}/3", inline=True)
                        embed.add_field(name="Total Violations", value=violation_count, inline=True)
                    
                    if action_type == "strike":
                        embed.add_field(name="Reason", value=reason, inline=False)
                        embed.add_field(name="Reset In", value="3 days", inline=True)
                        
                        if strike_count >= 3:
                            timeout_duration = PUNISHMENT_ESCALATION.get(violation_count, 1440)
                            embed.add_field(
                                name="⏰ Timeout Applied", 
                                value=f"{timeout_duration} minutes", 
                                inline=True
                            )
                    
                    await mod_log_channel.send(embed=embed)
                break

# Create bot instance
bot = StrikeBot()

def has_mod_permissions(interaction: discord.Interaction) -> bool:
    """Check if user has moderator permissions"""
    has_role = any(role.name in MODERATOR_ROLES for role in interaction.user.roles)
    return has_role or interaction.user.guild_permissions.administrator

@bot.tree.context_menu(name="Give Strike")
async def give_strike_context(interaction: discord.Interaction, member: discord.Member):
    """Context menu command to give a strike"""
    
    if not has_mod_permissions(interaction):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True
        )
        return
    
    if member.id == interaction.user.id:
        await interaction.response.send_message(
            "❌ You cannot give strikes to yourself.",
            ephemeral=True
        )
        return
    
    if member.bot:
        await interaction.response.send_message(
            "❌ You cannot give strikes to bots.",
            ephemeral=True
        )
        return
    
    # Create modal for strike reason
    class StrikeReasonModal(discord.ui.Modal, title='Issue Strike'):
        reason = discord.ui.TextInput(
            label='Reason for strike',
            placeholder='Enter the reason for this strike...',
            max_length=500,
            style=discord.TextStyle.paragraph
        )
        
        async def on_submit(self, modal_interaction: discord.Interaction):
            # Give the strike immediately
            result = await bot.strike_manager.give_strike(
                member, 
                modal_interaction.user, 
                self.reason.value
            )
            
            # Send immediate confirmation
            embed = discord.Embed(
                title="✅ Strike Issued",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="User", value=f"{member.mention}", inline=True)
            embed.add_field(name="Strikes", value=f"{result['strike_count']}/3", inline=True)
            embed.add_field(name="Violations", value=result['violation_count'], inline=True)
            embed.add_field(name="Reason", value=self.reason.value, inline=False)
            embed.add_field(name="Reset In", value="3 days", inline=True)
            
            await modal_interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Log the strike
            await bot.log_strike_action(
                member,
                modal_interaction.user,
                self.reason.value,
                result['strike_count'],
                result['violation_count'],
                "strike"
            )
    
    modal = StrikeReasonModal()
    await interaction.response.send_modal(modal)

@bot.tree.context_menu(name="Check Strikes")
async def check_strikes_context(interaction: discord.Interaction, member: discord.Member):
    """Context menu command to check strikes for a user"""
    
    # Get strike info
    strike_info = bot.strike_manager.get_user_strike_info(member.id)
    
    embed = discord.Embed(
        title=f"🔍 Strike Info for {member.display_name}",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    
    embed.add_field(name="Active Strikes", value=f"{strike_info['active_strikes']}/3", inline=True)
    embed.add_field(name="Total Violations", value=strike_info['violation_count'], inline=True)
    
    if strike_info['next_reset']:
        time_remaining = strike_info['next_reset'] - datetime.now()
        hours = int(time_remaining.total_seconds() // 3600)
        minutes = int((time_remaining.total_seconds() % 3600) // 60)
        reset_text = f"{hours}h {minutes}m"
    else:
        reset_text = "No active strikes"
    
    embed.add_field(name="Reset In", value=reset_text, inline=True)
    
    # Add warning if close to punishment
    if strike_info['active_strikes'] >= 2:
        embed.add_field(
            name="⚠️ Warning", 
            value=f"Next strike will result in a timeout!", 
            inline=False
        )
    
    embed.set_thumbnail(url=member.display_avatar.url)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Log the check (only if moderator)
    if has_mod_permissions(interaction):
        await bot.log_strike_action(
            member,
            interaction.user,
            "Strike check",
            strike_info['active_strikes'],
            strike_info['violation_count'],
            "check"
        )

@bot.tree.context_menu(name="Remove 1 Strike")
async def remove_strike_context(interaction: discord.Interaction, member: discord.Member):
    """Context menu command to remove one strike from a user"""
    
    if not has_mod_permissions(interaction):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True
        )
        return
    
    if member.bot:
        await interaction.response.send_message(
            "❌ You cannot remove strikes from bots.",
            ephemeral=True
        )
        return
    
    # Check current strikes
    strike_info = bot.strike_manager.get_user_strike_info(member.id)
    
    if strike_info['active_strikes'] == 0:
        await interaction.response.send_message(
            f"❌ {member.mention} has no active strikes to remove.",
            ephemeral=True
        )
        return
    
    # Remove strike immediately
    result = await bot.strike_manager.remove_strike(member.id)
    
    if result['removed']:
        embed = discord.Embed(
            title="✅ Strike Removed",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="User", value=f"{member.mention}", inline=True)
        embed.add_field(name="Remaining Strikes", value=f"{result['strike_count']}/3", inline=True)
        embed.add_field(name="Violations", value=result['violation_count'], inline=True)
    else:
        embed = discord.Embed(
            title="❌ No Strikes to Remove",
            color=discord.Color.red(),
            description=f"{member.mention} has no active strikes to remove."
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Log the action
    if result['removed']:
        await bot.log_strike_action(
            member,
            interaction.user,
            "Strike manually removed",
            result['strike_count'],
            result['violation_count'],
            "remove_strike"
        )

@bot.tree.context_menu(name="Reset Strikes")
async def reset_strikes_context(interaction: discord.Interaction, member: discord.Member):
    """Context menu command to reset all strikes for a user"""
    
    if not has_mod_permissions(interaction):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True
        )
        return
    
    if member.bot:
        await interaction.response.send_message(
            "❌ You cannot reset strikes for bots.",
            ephemeral=True
        )
        return
    
    # Check current strikes
    strike_info = bot.strike_manager.get_user_strike_info(member.id)
    
    if strike_info['active_strikes'] == 0:
        await interaction.response.send_message(
            f"❌ {member.mention} has no active strikes to reset.",
            ephemeral=True
        )
        return
    
    # Reset strikes immediately
    result = await bot.strike_manager.reset_all_strikes(member.id)
    
    embed = discord.Embed(
        title="✅ Strikes Reset",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="User", value=f"{member.mention}", inline=True)
    embed.add_field(name="Strikes Removed", value=result['strikes_removed'], inline=True)
    embed.add_field(name="Violations", value=result['violation_count'], inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Log the action
    await bot.log_strike_action(
        member,
        interaction.user,
        "All strikes manually reset",
        0,  # Strikes are now 0
        result['violation_count'],
        "reset_strikes"
    )

async def find_mod_log_channel(guild):
    """Find or create mod log channel"""
    # Look for existing channel
    for channel in guild.text_channels:
        if channel.name == MOD_LOG_CHANNEL_NAME:
            return channel
    
    # Create new channel if has permissions
    try:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # Add moderator roles
        for role in guild.roles:
            if role.name in MODERATOR_ROLES:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        channel = await guild.create_text_channel(
            MOD_LOG_CHANNEL_NAME,
            overwrites=overwrites,
            reason="Mod log channel for strike system"
        )
        return channel
    except Exception as e:
        logger.error(f"Error creating mod log channel: {e}")
        return None

@bot.event
async def on_guild_join(guild):
    """Create necessary channels when bot joins a guild"""
    await find_mod_log_channel(guild)
    
    # Look for or create dashboard channel
    dashboard_channel = None
    for channel in guild.text_channels:
        if channel.name == "👮‍♂️warnings-monitor":
            dashboard_channel = channel
            break
    
    if not dashboard_channel:
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            
            dashboard_channel = await guild.create_text_channel(
                "👮‍♂️warnings-monitor",
                overwrites=overwrites,
                reason="Strike system dashboard"
            )
        except Exception as e:
            logger.error(f"Error creating dashboard channel: {e}")
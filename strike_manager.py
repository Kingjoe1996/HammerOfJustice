import discord
from datetime import datetime, timedelta
import logging
from database import StrikeDatabase
from config import PUNISHMENT_ESCALATION, STRIKE_RESET_HOURS

logger = logging.getLogger(__name__)

class StrikeManager:
    def __init__(self, bot):
        self.bot = bot
        self.db = StrikeDatabase()
    
    async def give_strike(self, user, moderator, reason):
        """Give a strike to a user and handle punishments"""
        try:
            strike_id, strike_count = await self.db.add_strike(user.id, moderator.id, reason, STRIKE_RESET_HOURS)
            
            logger.info(f"Strike #{strike_id} given to {user} by {moderator}. Reason: {reason}")
            
            # Check if punishment should be applied
            violation_count = await self.check_punishment(user, strike_count)
            
            return {
                'strike_id': strike_id,
                'strike_count': strike_count,
                'violation_count': violation_count,
                'next_reset': datetime.now() + timedelta(hours=STRIKE_RESET_HOURS)
            }
        except Exception as e:
            logger.error(f"Error giving strike: {e}")
            # Return default values on error
            return {
                'strike_id': 0,
                'strike_count': 0,
                'violation_count': 0,
                'next_reset': datetime.now()
            }
    
    async def check_punishment(self, user, strike_count):
        """Check and apply punishment if user has 3+ strikes"""
        if strike_count >= 3:
            try:
                violation_count = await self.db.increment_violation_count(user.id)
                timeout_duration = PUNISHMENT_ESCALATION.get(violation_count, 1440)  # Default 24h
                
                # Convert minutes to timedelta
                timeout_delta = timedelta(minutes=timeout_duration)
                await user.timeout(timeout_delta, reason=f"Reached {strike_count} strikes (Violation #{violation_count})")
                logger.info(f"Timed out {user} for {timeout_duration} minutes (Violation #{violation_count})")
                return violation_count
            except discord.Forbidden:
                logger.error(f"Missing permissions to timeout {user}")
                return self.db.get_violation_count(user.id)
            except Exception as e:
                logger.error(f"Error timing out {user}: {e}")
                return self.db.get_violation_count(user.id)
        
        return self.db.get_violation_count(user.id)
    
    async def remove_strike(self, user_id):
        """Remove the most recent strike from a user"""
        try:
            # Get active strikes
            active_strikes = self.db.get_active_strikes(user_id)
            
            if not active_strikes:
                return {'removed': False, 'strike_count': 0, 'violation_count': self.db.get_violation_count(user_id)}
            
            # Remove the most recent strike (first in the list)
            strike_to_remove = active_strikes[0]
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE strikes SET active = 0 WHERE id = ?
            ''', (strike_to_remove[0],))
            
            conn.commit()
            conn.close()
            
            # Get updated strike count
            strike_info = self.db.get_user_strike_info(user_id)
            
            logger.info(f"Removed strike #{strike_to_remove[0]} from user {user_id}")
            
            return {
                'removed': True,
                'strike_count': strike_info['active_strikes'],
                'violation_count': strike_info['violation_count']
            }
            
        except Exception as e:
            logger.error(f"Error removing strike: {e}")
            return {'removed': False, 'strike_count': 0, 'violation_count': 0}
    
    async def reset_all_strikes(self, user_id):
        """Reset all strikes for a user"""
        try:
            # Get current active strikes count
            strike_info = self.db.get_user_strike_info(user_id)
            active_strikes_count = strike_info['active_strikes']
            
            if active_strikes_count == 0:
                return {'strikes_removed': 0, 'violation_count': strike_info['violation_count']}
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE strikes SET active = 0 WHERE user_id = ? AND active = 1
            ''', (user_id,))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Reset all {active_strikes_count} strikes for user {user_id}")
            
            return {
                'strikes_removed': active_strikes_count,
                'violation_count': strike_info['violation_count']  # Violations remain, only strikes reset
            }
            
        except Exception as e:
            logger.error(f"Error resetting strikes: {e}")
            return {'strikes_removed': 0, 'violation_count': 0}
    
    def get_user_strike_info(self, user_id):
        """Get strike information for a user"""
        return self.db.get_user_strike_info(user_id)
    
    def get_all_active_strikes(self):
        """Get all active strikes"""
        return self.db.get_all_active_strikes()
    
    async def reset_expired_strikes(self):
        """Reset expired strikes"""
        try:
            return await self.db.reset_expired_strikes()
        except Exception as e:
            logger.error(f"Error resetting expired strikes: {e}")
            return 0
import sqlite3
import json
from datetime import datetime, timedelta
import logging
import time
import os
import asyncio

logger = logging.getLogger(__name__)

class StrikeDatabase:
    def __init__(self, db_path="data/strikes.db"):
        self.db_path = db_path
        self._db_lock = asyncio.Lock()
        self.init_db()
    
    def get_connection(self):
        """Get a database connection"""
        try:
            # Ensure data directory exists
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            
            conn = sqlite3.connect(
                self.db_path, 
                timeout=30.0,
                check_same_thread=False
            )
            
            # Enable WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")
            conn.execute("PRAGMA busy_timeout=10000")
            
            return conn
        except sqlite3.OperationalError as e:
            logger.error(f"Failed to get database connection: {e}")
            # Retry once after a short delay
            time.sleep(0.1)
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            return conn
    
    def init_db(self):
        """Initialize database tables"""
        logger.info("Initializing database...")
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Strikes table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strikes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    reset_time DATETIME NOT NULL,
                    active BOOLEAN DEFAULT 1
                )
            ''')
            
            # Violations table (cumulative count)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS violations (
                    user_id INTEGER PRIMARY KEY,
                    violation_count INTEGER DEFAULT 0,
                    last_timeout DATETIME
                )
            ''')
            
            # Dashboard message ID
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            conn.commit()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    async def add_strike(self, user_id, moderator_id, reason, reset_hours=72):
        """Add a new strike for a user"""
        async with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            try:
                now = datetime.now()
                reset_time = now + timedelta(hours=reset_hours)
                
                cursor.execute('''
                    INSERT INTO strikes (user_id, moderator_id, reason, timestamp, reset_time, active)
                    VALUES (?, ?, ?, ?, ?, 1)
                ''', (user_id, moderator_id, reason, now, reset_time))
                
                strike_id = cursor.lastrowid
                
                # Get current active strike count
                cursor.execute('''
                    SELECT COUNT(*) FROM strikes 
                    WHERE user_id = ? AND active = 1
                ''', (user_id,))
                strike_count = cursor.fetchone()[0]
                
                conn.commit()
                return strike_id, strike_count
            except Exception as e:
                logger.error(f"Error adding strike: {e}")
                conn.rollback()
                raise e
            finally:
                conn.close()
    
    def get_active_strikes(self, user_id):
        """Get all active strikes for a user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT * FROM strikes 
                WHERE user_id = ? AND active = 1 
                ORDER BY timestamp DESC
            ''', (user_id,))
            
            strikes = cursor.fetchall()
            return strikes
        finally:
            conn.close()
    
    def get_user_strike_info(self, user_id):
        """Get comprehensive strike info for a user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Get active strikes
            cursor.execute('''
                SELECT COUNT(*) FROM strikes 
                WHERE user_id = ? AND active = 1
            ''', (user_id,))
            active_strikes = cursor.fetchone()[0]
            
            # Get next reset time
            cursor.execute('''
                SELECT MIN(reset_time) FROM strikes 
                WHERE user_id = ? AND active = 1
            ''', (user_id,))
            reset_result = cursor.fetchone()[0]
            
            # Get violation count
            cursor.execute('''
                SELECT violation_count FROM violations 
                WHERE user_id = ?
            ''', (user_id,))
            violation_result = cursor.fetchone()
            violation_count = violation_result[0] if violation_result else 0
            
            conn.close()
            
            return {
                'active_strikes': active_strikes,
                'next_reset': datetime.fromisoformat(reset_result) if reset_result else None,
                'violation_count': violation_count
            }
        except Exception as e:
            logger.error(f"Error getting user strike info: {e}")
            conn.close()
            return {'active_strikes': 0, 'next_reset': None, 'violation_count': 0}
    
    def get_all_active_strikes(self):
        """Get all active strikes across all users"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT s.*, 
                       COALESCE((SELECT violation_count FROM violations WHERE user_id = s.user_id), 0) as violation_count
                FROM strikes s
                WHERE s.active = 1
                ORDER BY s.user_id, s.timestamp DESC
            ''')
            
            strikes = cursor.fetchall()
            return strikes
        except Exception as e:
            logger.error(f"Error getting all active strikes: {e}")
            return []
        finally:
            conn.close()
    
    async def reset_expired_strikes(self):
        """Reset strikes that have passed their reset time"""
        async with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            try:
                now = datetime.now()
                cursor.execute('''
                    UPDATE strikes 
                    SET active = 0 
                    WHERE reset_time < ? AND active = 1
                ''', (now,))
                
                # Use rowcount instead of changes
                reset_count = cursor.rowcount
                conn.commit()
                return reset_count
            except Exception as e:
                logger.error(f"Error resetting expired strikes: {e}")
                conn.rollback()
                return 0
            finally:
                conn.close()
    
    async def increment_violation_count(self, user_id):
        """Increment violation count for a user"""
        async with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO violations (user_id, violation_count, last_timeout)
                    VALUES (?, COALESCE((SELECT violation_count FROM violations WHERE user_id = ?), 0) + 1, ?)
                ''', (user_id, user_id, datetime.now()))
                
                cursor.execute('SELECT violation_count FROM violations WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
                violation_count = result[0] if result else 1
                
                conn.commit()
                return violation_count
            except Exception as e:
                logger.error(f"Error incrementing violation count: {e}")
                conn.rollback()
                return 1
            finally:
                conn.close()
    
    def get_violation_count(self, user_id):
        """Get violation count for a user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT violation_count FROM violations WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            violation_count = result[0] if result else 0
            return violation_count
        finally:
            conn.close()
    
    async def save_dashboard_message(self, channel_id, message_id):
        """Save dashboard message ID"""
        async with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO bot_state (key, value)
                    VALUES ('dashboard_message', ?)
                ''', (f"{channel_id}:{message_id}",))
                
                conn.commit()
            except Exception as e:
                logger.error(f"Error saving dashboard message: {e}")
                conn.rollback()
            finally:
                conn.close()
    
    def get_dashboard_message(self):
        """Get dashboard message ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT value FROM bot_state WHERE key = "dashboard_message"')
            result = cursor.fetchone()
            
            if result:
                try:
                    channel_id, message_id = result[0].split(':')
                    return int(channel_id), int(message_id)
                except (ValueError, IndexError):
                    return None, None
            return None, None
        except Exception as e:
            logger.error(f"Error getting dashboard message: {e}")
            return None, None
        finally:
            conn.close()
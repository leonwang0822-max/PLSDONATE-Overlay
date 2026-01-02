import asyncio
import logging
from twitchio.ext import commands
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from functools import partial

logger = logging.getLogger(__name__)

class TwitchBot(commands.Bot):
    def __init__(self, token, channel):
        # Clean token if it includes "oauth:"
        if token.startswith("oauth:"):
            token = token.replace("oauth:", "")
        super().__init__(token=token, prefix='!', initial_channels=[channel])
        self.target_channel = channel

    async def event_ready(self):
        logger.info(f'Twitch Bot connected as {self.nick}')

    async def send_to_channel(self, message):
        # Get channel from cache or wait for it
        channel = self.get_channel(self.target_channel)
        if channel:
            await channel.send(message)
        else:
            logger.warning(f"Twitch channel {self.target_channel} not found in cache yet.")

class ChatManager:
    def __init__(self):
        self.config = {}
        self.twitch_bot = None
        self.twitch_task = None
    
    async def update_config(self, config):
        self.config = config
        
        # Handle Twitch Reconnect
        if self.twitch_bot:
            try:
                await self.twitch_bot.close()
            except:
                pass
            self.twitch_bot = None
            
        if config.get('twitch_enabled') and config.get('twitch_token') and config.get('twitch_channel'):
            try:
                self.twitch_bot = TwitchBot(config['twitch_token'], config['twitch_channel'])
                # Start bot in background
                self.twitch_task = asyncio.create_task(self.twitch_bot.start())
            except Exception as e:
                logger.error(f"Failed to start Twitch bot: {e}")

    async def send_message(self, donation_data):
        template = self.config.get('chat_template')
        if not template:
            template = 'Thanks for the {amount}R$ donation by @{username}'
            
        message = template.format(
            amount=donation_data.get('amount'),
            username=donation_data.get('sender_user'),
            message=donation_data.get('message', '')
        )
        
        # Twitch
        if self.twitch_bot and self.config.get('twitch_enabled'):
            try:
                await self.twitch_bot.send_to_channel(message)
            except Exception as e:
                logger.error(f"Twitch send error: {e}")
                
        # YouTube
        if self.config.get('youtube_enabled') and self.config.get('youtube_token'):
            # Run blocking YouTube API in executor
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, partial(self.send_youtube_sync, message))

    def send_youtube_sync(self, message):
        token = self.config.get('youtube_token')
        chat_id = self.config.get('youtube_chat_id')
        
        if not chat_id:
            logger.warning("YouTube Chat ID not set. Please enter it in the dashboard.")
            return

        try:
            creds = Credentials(token)
            youtube = build('youtube', 'v3', credentials=creds)
            
            # 2. Insert message directly using provided ID
            youtube.liveChatMessages().insert(
                part="snippet",
                body={
                    "snippet": {
                        "liveChatId": chat_id,
                        "type": "textMessageEvent",
                        "textMessageDetails": {
                            "messageText": message
                        }
                    }
                }
            ).execute()
            logger.info("Sent YouTube message")
        except HttpError as e:
            if e.resp.status == 403 and "quotaExceeded" in str(e):
                logger.warning("YouTube daily quota exceeded! Disabling YouTube integration for this session.")
                logger.warning("It will reset automatically tomorrow (Pacific Time).")
                self.config['youtube_enabled'] = False
            else:
                logger.error(f"YouTube API error: {e}")
        except Exception as e:
            error_msg = str(e)
            if "refresh the access token" in error_msg or "401" in error_msg:
                 logger.warning("YouTube Access Token expired. Please generate a new one in the dashboard.")
                 self.config['youtube_enabled'] = False
            else:
                logger.error(f"YouTube send error: {e}")

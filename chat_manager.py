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
        self.youtube_chat_id = None
    
    async def update_config(self, config):
        self.config = config
        # Reset cached chat ID when config changes (e.g. new token)
        self.youtube_chat_id = None
        
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
        try:
            creds = Credentials(token)
            youtube = build('youtube', 'v3', credentials=creds)
            
            # 1. Get live broadcast ID (only if not cached)
            if not self.youtube_chat_id:
                try:
                    request = youtube.liveBroadcasts().list(
                        part="snippet",
                        broadcastStatus="active",
                        broadcastType="all"
                    )
                    response = request.execute()
                    
                    if not response.get('items'):
                        logger.warning("No active YouTube broadcast found.")
                        return

                    self.youtube_chat_id = response['items'][0]['snippet']['liveChatId']
                    logger.info(f"Cached YouTube LiveChat ID: {self.youtube_chat_id}")
                except Exception as e:
                     # Reset cache on error to force retry next time
                    self.youtube_chat_id = None
                    raise e
            
            # 2. Insert message
            youtube.liveChatMessages().insert(
                part="snippet",
                body={
                    "snippet": {
                        "liveChatId": self.youtube_chat_id,
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
                self.youtube_chat_id = None
            else:
                logger.error(f"YouTube API error: {e}")
                self.youtube_chat_id = None
        except Exception as e:
            logger.error(f"YouTube send error: {e}")
            # If we get a 403 or 404, it might mean the stream ended or chat ID changed.
            # Reset cache so we try to find the new stream ID next time.
            self.youtube_chat_id = None

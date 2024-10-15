import datetime
import asyncio
import aiofiles
import json
import re

class Tell:
    def __init__(self):
        self.message_queue = {}
        self.load_message_queue()

    def strip_irc_formatting(self, text):
        # Regular expression to match IRC color and formatting codes
        irc_formatting_pattern = re.compile(r'(\x03\d{0,2}(,\d{1,2})?)|(\x02)|(\x1F)|(\x16)|(\x0F)')
        return irc_formatting_pattern.sub('', text)

    async def handle_tell_command(self, channel, sender, content):
        self.message_queue = {}
        self.load_message_queue()
        try:
            # Parse the command: !tell username message
            _, username, message = content.split(' ', 2)

            # Strip IRC colors and formatting from the message
            username = self.strip_irc_formatting(username)
            message = self.strip_irc_formatting(message)

            # Convert the recipient's nickname to lowercase
            username_lower = username.lower()

            # Create a tuple key with the channel and recipient's lowercase nickname
            key = (channel, username_lower)

            # Check if the key exists in the message_queue
            if key not in self.message_queue:
                self.message_queue[key] = []

            # Get the current time in UTC without pytz
            utc_now = datetime.datetime.utcnow()

            # Save the message for the user in the specific channel with a timestamp
            timestamp = utc_now.strftime("%Y-%m-%d %H:%M:%S UTC")
            self.message_queue[key].append((username, sender, message, timestamp))

            # Notify the user that the message is saved
            response = f"{sender}, I'll tell {username} that when they return."
            await self.save_message_queue()
            print(self.message_queue)
            return response
        except ValueError:
            response = f"Invalid .tell command format. Use: .tell username message"
            return response

    async def save_message_queue(self, filename="message_queue.json"):
        try:
            # Convert tuple keys to strings for serialization
            serialized_message_queue = {str(key): value for key, value in self.message_queue.items()}
            
            # Save the primary file
            async with aiofiles.open(filename, "w") as file:
                await file.write(json.dumps(serialized_message_queue, indent=2))
        
        except Exception as e:
            print(f"Error saving message queue: {e}")

    def load_message_queue(self, filename="message_queue.json"):
        try:
            with open(filename, "r") as file:
                serialized_message_queue = json.load(file)

                # Convert string keys back to tuples for deserialization
                self.message_queue = {tuple(eval(key)): value for key, value in serialized_message_queue.items()}
                print("Successfully Loaded message_queue.json")
        except FileNotFoundError:
            print("Message queue file not found.")

    def format_timedelta(self, delta):
        days, seconds = delta.days, delta.seconds
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m {seconds}s"

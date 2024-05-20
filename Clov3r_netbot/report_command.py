import datetime
import asyncio
import aiofiles
import json

class ReportIn:
    def __init__(self):
        self.message_queue = {}
        self.load_message_queue()

    def load_message_queue(self, filename="message_queue.json"):
        try:
            with open(filename, "r") as file:
                serialized_message_queue = json.load(file)

                # Convert string keys back to tuples for deserialization
                self.message_queue = {tuple(eval(key)): value for key, value in serialized_message_queue.items()}
        except FileNotFoundError:
            print("Message queue file not found.")

    async def save_message_queue(self, filename="message_queue.json"):
        try:
            # Convert tuple keys to strings for serialization
            serialized_message_queue = {str(key): value for key, value in self.message_queue.items()}
            
            # Save the primary file
            async with aiofiles.open(filename, "w") as file:
                await file.write(json.dumps(serialized_message_queue, indent=2))
        
        except Exception as e:
            print(f"Error saving message queue: {e}")

    def format_timedelta(self, delta):
        days, seconds = delta.days, delta.seconds
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m {seconds}s"

    async def send_saved_messages(self, sender, channel):
        self.message_queue = {}
        self.load_message_queue()
        # Convert the sender nickname to lowercase for case-insensitive comparison
        sender_lower = sender.lower()

        # Iterate over keys in the message_queue and find matching recipients
        for key, messages in list(self.message_queue.items()):
            try:
                (saved_channel, saved_recipient) = key
            except ValueError:
                print(f"Error unpacking key: {key}")
                continue

            # Convert the recipient nickname to lowercase for case-insensitive comparison
            recipient_lower = saved_recipient.lower()

            # Check if the lowercase nicknames match and the channels are the same
            if sender_lower == recipient_lower and channel == saved_channel:
                # Get the current time as offset-aware
                current_time = datetime.datetime.now(datetime.timezone.utc)

                for (username, recipient, saved_message, timestamp) in messages:
                    # Convert the timestamp to a datetime object and make it offset-aware
                    timestamp = timestamp.rstrip(" UTC")  # Remove ' UTC' suffix
                    message_time_naive = datetime.datetime.fromisoformat(timestamp)
                    # Make it offset-aware by specifying UTC timezone
                    message_time = message_time_naive.replace(tzinfo=datetime.timezone.utc)

                    # Calculate the time difference
                    time_difference = current_time - message_time

                    # Format the time difference as a human-readable string
                    formatted_time_difference = self.format_timedelta(time_difference)

                    response = f"{sender}, {formatted_time_difference} ago <{recipient}> {saved_message} \r\n"

                    # Yield the response for each message
                    yield response

                # Delete the key from the message_queue after processing all messages
                del self.message_queue[key]
                await self.save_message_queue()
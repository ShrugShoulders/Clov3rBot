import asyncio
import aiofiles
import json
import datetime

class Seenme:
    def __init__(self):
        self.last_seen = {}
        self.load_last_seen()

    async def save_last_seen(self, filename="last_seen.json"):
        try:
            async with aiofiles.open(filename, "w") as file:
                await file.write(json.dumps(self.last_seen, indent=2))
        except Exception as e:
            print(f"Error saving last_seen dictionary: {e}")

    def load_last_seen(self, filename="last_seen.json"):
        try:
            with open(filename, "r") as file:
                self.last_seen = json.load(file)
                print("Successfully Loaded last_seen.json")
        except FileNotFoundError:
            print("Last_seen file not found.")
        except Exception as e:
            print(f"Error loading last_seen dictionary: {e}")

    def format_timedelta(self, delta):
        days, seconds = delta.days, delta.seconds
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds:
            parts.append(f"{seconds}s")
        
        return ' '.join(parts)
        
    async def seen_command(self, channel, sender, content):
        try:
            self.last_seen = {}
            self.load_last_seen()
            # Parse the command: !seen username
            _, username = content.split(' ', 1)

            # Convert the username to lowercase for case-insensitive comparison
            username_lower = username.lower()

            # Check if the user has been seen in the specific channel
            if username_lower in self.last_seen and channel in self.last_seen[username_lower]:
                last_seen_info = self.last_seen[username_lower][channel]

                # Convert the timestamp to a datetime object
                timestamp = datetime.datetime.strptime(last_seen_info['timestamp'], "%Y-%m-%d %H:%M:%S")

                # Calculate the time difference
                time_difference = datetime.datetime.now() - timestamp

                # Format the time difference as a human-readable string
                formatted_time = self.format_timedelta(time_difference)

                response = f"{sender}, {formatted_time} ago <{username}> {last_seen_info['message']}\r\n"
            else:
                response = f"{sender}, I haven't seen {username} recently in {channel}.\r\n"

            print(f"Sent: {response} to {channel}")
            return response

        except ValueError:
            response = f"PRIVMSG {channel} :Invalid .seen command format. Use: .seen username\r\n"
            return response

    async def record_last_seen(self, sender, channel, content):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Update or create the last_seen dictionary for the user and channel
        user = sender.lower()

        if user not in self.last_seen:
            self.last_seen[user] = {}

        if channel not in self.last_seen[user]:
            self.last_seen[user][channel] = {}

        self.last_seen[user][channel] = {
            "timestamp": timestamp,
            "message": content,
            "chat_count": self.last_seen[user][channel].get('chat_count', 0) + 1
        }

    async def stats_command(self, channel, sender, content):
        # Extract the target user from the command
        self.last_seen = {}
        self.load_last_seen()
        target_user = content.split()[1].strip() if len(content.split()) > 1 else None

        if target_user:
            # Convert the target user to lowercase for case-insensitive matching
            target_user = target_user.lower()

            # Check if the target user has chat count information
            if target_user in self.last_seen and channel in self.last_seen[target_user]:
                chat_count = self.last_seen[target_user][channel].get('chat_count', 0)
                response = f"{sender}, I've seen {target_user} send {chat_count} messages"
                return response
            else:
                response = f"{sender}, no stats found for {target_user}"
                return response
        else:
            response = f"{sender}, please provide a target user for the .stats command"
            return response

    async def top_stats_command(self, channel, sender, content):
        # Ensure last_seen is loaded
        self.last_seen = {}
        self.load_last_seen()

        user_message_counts = []

        # Iterate over users and collect message counts for the given channel
        for user, channels in self.last_seen.items():
            if channel in channels:
                chat_count = channels[channel].get('chat_count', 0)
                user_message_counts.append((user, chat_count))

        # Sort the users by message count in descending order
        user_message_counts.sort(key=lambda x: x[1], reverse=True)

        # Get the top 3 users (or fewer if there are less than 3)
        top_users = user_message_counts[:3]

        # Build the response
        if top_users:
            users_str = " - ".join([f"{user}, {count}" for user, count in top_users])
            response = f"These are the top users in the channel: {users_str}"
        else:
            response = f"{sender}, no stats found for {channel}."

        return response

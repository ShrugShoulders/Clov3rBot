import asyncio
import bleach
import configparser
import datetime
import html
import ipaddress
import json
import pytz
import random
import re
import requests
import ssl
import threading
import time
from bs4 import BeautifulSoup
from collections import deque
from html import escape
from typing import Optional

class IRCBot:
    def __init__(self, nickname, channels, server, port=6697, use_ssl=True, admin_list=None, nickserv_password=None):
        self.nickname = nickname
        self.channels = channels if isinstance(channels, list) else [channels]
        self.nickserv_password = nickserv_password
        self.server = server
        self.port = port
        self.use_ssl = use_ssl
        self.admin_list = set(admin_list) if admin_list else set()
        self.last_messages = deque(maxlen=200)
        self.mushroom_facts = []
        self.message_queue = {}
        self.last_seen = {}
        self.reader = None
        self.writer = None
        self.lock = asyncio.Lock()
        self.url_regex = re.compile(r'https?://\S+')

    @classmethod
    def from_config_file(cls, config_file):
        config = configparser.ConfigParser()
        config.read(config_file)
        bot_config = config['BotConfig']
        admin_list = config.get('AdminConfig', 'admin_list', fallback='').split(',')
        channels = bot_config.get('channels').split(',')
        nickserv_password = bot_config.get('nickserv_password', fallback=None)

        return cls(
            nickname=bot_config.get('nickname'),
            channels=channels,
            server=bot_config.get('server'),
            port=int(bot_config.get('port', 6697)),
            use_ssl=bot_config.getboolean('use_ssl', True),
            admin_list=admin_list,
            nickserv_password=nickserv_password
        )

    def save_last_seen(self, filename="last_seen.json"):
        try:
            with open(filename, "w") as file:
                json.dump(self.last_seen, file)
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

    def load_mushroom_facts(self):
        try:
            with open("mushroom_facts.txt", "r") as file:
                self.mushroom_facts = [line.strip() for line in file.readlines()]
                print("Successfully Loaded Mushroom Facts")
        except FileNotFoundError:
            print("Mushroom facts file not found.")

    def save_mushroom_facts(self):
        with open("mushroom_facts.txt", "w") as file:
            for fact in self.mushroom_facts:
                file.write(f"{fact}\n")

    def save_message_queue(self, filename="message_queue.json", backup_filename="message_queue_backup.json"):
        try:
            # Convert tuple keys to strings for serialization
            serialized_message_queue = {str(key): value for key, value in self.message_queue.items()}
            
            # Save the primary file
            with open(filename, "w") as file:
                json.dump(serialized_message_queue, file)
            
            # Save the backup file
            with open(backup_filename, "w") as backup_file:
                json.dump(serialized_message_queue, backup_file)
        
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

    async def connect(self):
        if self.use_ssl:
            ssl_context = ssl.create_default_context()
            self.reader, self.writer = await asyncio.open_connection(self.server, self.port, ssl=ssl_context)
        else:
            self.reader, self.writer = await asyncio.open_connection(self.server, self.port)

        self.send(f"USER {self.nickname} 0 * :{self.nickname}")
        self.send(f"NICK {self.nickname}")

    async def identify_with_nickserv(self):
        motd_received = False
        while True:
            data = await self.reader.read(2048)
            message = data.decode("UTF-8")
            print(message)

            if "376" in message:  # End of MOTD
                self.send(f'PRIVMSG NickServ :IDENTIFY {self.nickname} {self.nickserv_password}\r\n')
                print("Sent NickServ authentication.")  # End of MOTD
                motd_received = True

            if motd_received and "396" in message:  # NickServ authentication successful
                for channel in self.channels:
                    await self.join_channel(channel)
                print("Joined channels after NickServ authentication.")
                break

    def send(self, message):
        self.writer.write((message + '\r\n').encode())

    async def join_channel(self, channel):
        self.send(f"JOIN {channel}")
        await asyncio.sleep(0.3)

    async def keep_alive(self):
        while True:
            async with self.lock:
                self.send("PING :keepalive")
                print(f"Sent: PING to Server: {self.server}")
            await asyncio.sleep(195)

    async def save_message(self, message, channel):
        sender_match = re.match(r":(\S+)!\S+@\S+", message)
        sender = sender_match.group(1) if sender_match else "Unknown Sender"
        content = message.split('PRIVMSG')[1].split(':', 1)[1].strip()

        # Get the current time in UTC
        utc_now = datetime.datetime.now(pytz.utc)

        formatted_message = {
            "timestamp": utc_now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "channel": channel,
            "sender": sender,
            "content": content
        }
        self.last_messages.append(formatted_message)

    async def handle_messages(self):
        global disconnect_requested
        disconnect_requested = False
        while not disconnect_requested:
            data = await self.reader.read(1000)
            message = data.decode()
            print(message)

            if "PING" in message:
                self.send("PONG " + message.split()[1])
            elif "PRIVMSG" in message:
                # Extract sender, channel, and content information
                sender_match = re.match(r":(\S+)!\S+@\S+", message)
                sender = sender_match.group(1) if sender_match else "Unknown Sender"
                channel = message.split('PRIVMSG')[1].split(':')[0].strip()
                content = message.split('PRIVMSG')[1].split(':', 1)[1].strip()

                # Record the last seen information for the user
                self.record_last_seen(sender, channel, content)
                self.save_last_seen()

                await self.user_commands(message)
                await self.detect_and_parse_urls(message)
                await self.save_message(message, channel)
                await self.send_saved_messages(message)

        print("Disconnecting...")
        await self.disconnect()

    def record_last_seen(self, sender, channel, content):
        # Existing code for recording last seen information
        utc_now = datetime.datetime.now(pytz.utc)
        timestamp = utc_now.strftime("%Y-%m-%d %H:%M:%S UTC")

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

    async def get_channel_topic(self, channel: str) -> Optional[str]:
        self.send(f"TOPIC {channel}")
        data = await self.reader.read(2048)
        message = data.decode("UTF-8")

        if "332" in message:  # TOPIC message
            topic = message.split(":", 2)[2].strip()
            return topic
        else:
            return None

    async def sanitize_input(self, malicious_input):
        decoded_input = html.unescape(malicious_input)
        safe_output = ''.join(char for char in decoded_input if 32 <= ord(char) <= 126)
        title_match = re.search(r'<title>(.+?)</title>', safe_output)
        if title_match:
            safe_output = title_match.group(1)
        return safe_output

    async def is_raw_text_paste(self, url):
        # Patterns for raw text pastes
        raw_text_patterns = [
            "pastebin.com/raw/",
            "bpa.st/raw/",
            "@raw",
        ]
        return any(pattern in url for pattern in raw_text_patterns)

    def filter_private_ip(self, url):
        # Extract the hostname from the URL
        hostname = re.findall(r'https?://([^/:]+)', url)
        if hostname:
            hostname = hostname[0]
            try:
                ip = ipaddress.ip_address(hostname)
                return ip.is_private  # Return True for private IP addresses
            except ValueError:
                pass  # Not an IP address

        return False

    async def extract_webpage_title(self, url):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            response = requests.get(url, headers=headers)
            response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)

            # Check if the content type is an image
            content_type = response.headers.get('Content-Type', '').lower()
            if content_type.startswith('image/'):
                return "Image URL, no title available"

            soup = BeautifulSoup(response.text, 'lxml')

            # Look for the first <title> tag
            title_tag = soup.find('title')
            if title_tag:
                # Sanitize the title using bleach and filter out specific characters
                sanitized_title = bleach.clean(str(title_tag.string), tags=[], attributes={})
                return sanitized_title.strip()

            # Function to get a list of sanitized titles from meta tags
            def get_meta_content(meta_tags):
                titles = [bleach.clean(meta_tag.attrs.get('content', ''), tags=[], attributes={}).strip() for meta_tag in meta_tags]
                return [title for title in titles if title]

            # Look for the first og:title meta tag
            og_title_tags = soup.find_all('meta', property='og:title')
            if og_title_tags:
                sanitized_titles = get_meta_content(og_title_tags)
                if sanitized_titles:
                    return sanitized_titles[0]

            # Look for the first Twitter Card title
            twitter_title_tags = soup.find_all('meta', name='twitter:title')
            if twitter_title_tags:
                sanitized_titles = get_meta_content(twitter_title_tags)
                if sanitized_titles:
                    return sanitized_titles[0]

            # Look for the first Dublin Core title
            dc_title_tags = soup.find_all('meta', name='DC.title')
            if dc_title_tags:
                sanitized_titles = get_meta_content(dc_title_tags)
                if sanitized_titles:
                    return sanitized_titles[0]

            # If none of the above tags are found
            return "Title not found"

        except requests.exceptions.Timeout:
            print(f"Timeout retrieving webpage title for {url}")
            return "Timeout retrieving title"
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 404:
                print(f"Webpage not found (404) for {url}")
                return "Webpage not found"
            else:
                print(f"Error retrieving webpage title for {url}: {e}")
                return "Error retrieving title"

    async def detect_and_parse_urls(self, message):
        sender = message.split('!')[0][1:]
        channel = message.split('PRIVMSG')[1].split(':')[0].strip()
        content = message.split('PRIVMSG')[1].split(':', 1)[1].strip()

        urls = self.url_regex.findall(content)

        for url in urls:
            try:
                # Check if the message starts with '@' symbol and contains a list of URLs
                if content.startswith("@"):
                    return

                # Filter out URLs with private IP addresses
                if self.filter_private_ip(url):
                    print(f"Ignoring URL with private IP address: {url}")
                    continue

                # Check if the URL is a raw text paste
                if await self.is_raw_text_paste(url):
                    paste_code = url.split("/")[-1]
                    response = f"Raw paste: {paste_code}"
                    self.send(f'PRIVMSG {channel} :{response}\r\n')
                    print(f"Sent: {response} to {channel}")
                    continue

                # Extract the full name of the file from the URL
                file_name = url.split("/")[-1]

                # Check if the URL ends with a file extension
                if "." in file_name:
                    file_extension = file_name.split(".")[-1].lower()
                else:
                    file_extension = None

                # Check if the URL is a GitHub file URL with a line range
                if "github.com" in url and "/blob/" in url and "#L" in url:
                    response = f"GitHub file URL with line range"
                else:
                    # Extract the webpage title, sanitize it using bleach and the new function
                    webpage_title = await self.sanitize_input(await self.extract_webpage_title(url))

                    if webpage_title == "Title not found":
                        # Handle the case where the title is not found
                        site_name = url.split('/')[2]  # Extract the site name from the URL
                        paste_code = url.split('/')[-1]
                        response = f"[Website] {site_name} paste: {paste_code}"

                    elif webpage_title == "Image URL, no title available":
                        # Handle the case where it's an image.
                        site_name = url.split('/')[2] 
                        paste_code = url.split('/')[-1]
                        response = f"[Website] {site_name} (Image) {paste_code}"

                    elif webpage_title == "Timeout retrieving title":
                        print(f"Timeout retrieving title")
                        return

                    elif webpage_title == "Error retrieving title":
                        print(f"Error retrieving title")

                    elif webpage_title == "Webpage not found":
                        print(f"Error 404 - not found")
                        return

                    else:
                        # Process the URL based on its file extension
                        if file_extension in ["jpg", "jpeg", "png", "gif", "webp", "tiff", "eps", "ai", "indd", "raw"]:
                            response = f"[Website] image file: {file_name}"
                        elif file_extension in ["m4a", "flac", "wav", "wma", "aac", "mp3", "mp4", "avi", "webm", "mov", "wmv", "flv", "xm"]:
                            response = f"[Website] media file: {file_name}"
                        elif file_extension in ["sh", "bat", "rs", "cpp", "py", "java", "cs", "vb", "c", "txt", "pdf"]:
                            response = f"[Website] data file: {file_name}"
                        else:
                            # Sanitize the response before sending it to the channel
                            response = escape(f"[Website] {webpage_title}")

                # Send the response to the channel
                self.send(f'PRIVMSG {channel} :{response}\r\n')
                print(f"Sent: {response} to {channel}")

            except requests.exceptions.Timeout:
                print(f"Timeout processing URL: {url}")
                continue

            except Exception as e:
                print(f"Error fetching or parsing URL: {e}")

    def get_available_commands(self):
        # List all available commands (excluding admin commands)
        commands = [
            "!hi",
            "!roll",
            "!fact <criteria>",
            "!last [1-10] shows last said in chan",
            "!tell <user> <message>",
            "!seen <user>",
            "!info",
            "!topic",
            "!moo",
            "!moof",
            "!help",
            "!rollover",
            # Add more commands as needed
        ]
        return commands

    async def help_command(self, channel, sender):
        # Get the list of available commands
        commands = self.get_available_commands()

        # Send the list of commands to the channel
        response = f"PRIVMSG {channel} :{sender}, Commands: {', '.join(commands)}\r\n"
        self.send(response)
        print(f"Sent: {response} to {channel}")

    def send_dog_cow_message(self, channel):
        dog_cow = "https://i.imgur.com/1S6flQw.gif"
        response = "Hello Claris, dog or cow?"
        self.send(f'PRIVMSG {channel} :{response} {dog_cow}\r\n')

    async def user_commands(self, message):
        global disconnect_requested
        sender_match = re.match(r":(\S+)!\S+@\S+", message)
        if not sender_match:
            print("Unable to extract sender from the message:", message)
            return

        sender = sender_match.group(1)
        channel = message.split('PRIVMSG')[1].split(':')[0].strip()
        content = message.split('PRIVMSG')[1].split(':', 1)[1].strip()

        hostmask_match = re.search(r":(\S+!\S+@\S+)", message)
        hostmask = hostmask_match.group(1) if hostmask_match else "Unknown Hostmask"

        print(f"Sender: {sender}")
        print(f"Channel: {channel}")
        print(f"Content: {content}")
        print(f"Full Hostmask: {hostmask}")

        # Check if the message starts with 's/' for sed-like command
        if content and content.startswith('s/'):
            await self.handle_sed_command(channel, sender, content)
        else:
            # Check if there are any words in the content before accessing the first word
            if content:
                command = content.split()[0]
                args = content[len(command):].strip()

                match command:
                    case '!hi':
                        # Says hi (like ping)
                        response = f"PRIVMSG {channel} :Hi {sender}!"
                        self.send(response)

                    case '!roll':
                        # Roll the dice
                        await self.dice_roll(args, channel, sender)

                    case "!fact":
                        # Extract the criteria from the user's command
                        criteria = self.extract_factoid_criteria(args)
                        self.send_random_mushroom_fact(channel, criteria)

                    case '!tell':
                        # Save a message for a user
                        await self.handle_tell_command(channel, sender, content)

                    case '!info':
                        self.handle_info_command(channel, sender)

                    case '!moo':
                        response = "Hi cow!"
                        self.send(f'PRIVMSG {channel} :{response}\r\n')

                    case '!moof':
                        self.send_dog_cow_message(channel)

                    case '!topic':
                        # Get and send the channel topic
                        topic = await self.get_channel_topic(channel)
                        if topic:
                            response = f"PRIVMSG {channel} :{topic}\r\n"
                        else:
                            response = f"PRIVMSG {channel} :Unable to retrieve the topic\r\n"
                        self.send(response)
                        print(f"Sent: {response} to {channel}")

                    case '!help':
                        # Handle the help command
                        await self.help_command(channel, sender)

                    case '!seen':
                        # Handle the !seen command
                        await self.seen_command(channel, sender, content)

                    case '!last':
                        await self.last_command(channel, sender, content)

                    case '!version':
                        version = "Clov3rBot Version 1.0"
                        response = f"PRIVMSG {channel} :{version}"
                        self.send(response)

                    case '!rollover':
                        # Perform the rollover action
                        barking_action = f"PRIVMSG {channel} :woof woof!"
                        action_message = f"PRIVMSG {channel} :\x01ACTION rolls over\x01"
                        self.send(barking_action)
                        self.send(action_message)

                    case '!factadd' if hostmask in self.admin_list:
                        # Handle the !factadd command
                        new_fact = args.strip()
                        if new_fact:
                            self.mushroom_facts.append(new_fact)
                            self.save_mushroom_facts()
                            response = f"PRIVMSG {channel} :New mushroom fact added: {new_fact}"
                        else:
                            response = f"PRIVMSG {channel} :Please provide a valid mushroom fact."
                        self.send(response)

                    case '!quit' if hostmask in self.admin_list:
                        # Quits the bot from the network.
                        response = f"PRIVMSG {channel} :Acknowledged {sender} quitting..."
                        self.send(response)
                        disconnect_requested = True

                    case '!op' if hostmask in self.admin_list:
                        # Op the user
                        self.send(f"MODE {channel} +o {sender}\r\n")

                    case '!deop' if hostmask in self.admin_list:
                        # Deop the user
                        self.send(f"MODE {channel} -o {sender}\r\n")

                    case '!botop' if hostmask in self.admin_list:
                        # Op the bot using Chanserv
                        self.send(f"PRIVMSG Chanserv :OP {channel} {self.nickname}\r\n")

                    case '!join' if hostmask in self.admin_list:
                        # Join a specified channel
                        if args:
                            new_channel = args.split()[0]
                            self.send(f"JOIN {new_channel}\r\n")

                    case '!part' if hostmask in self.admin_list:
                        # Part from a specified channel
                        if args:
                            part_channel = args.split()[0]
                            self.send(f"PART {part_channel}\r\n")

                    case '!reload' if hostmask in self.admin_list:
                        # Reload lists/dicts
                        await self.purge_message_queue(channel, sender)
                        await self.reload_command(channel, sender)

    async def reload_command(self, channel, sender):
        self.mushroom_facts = []
        self.last_seen = {}
        self.load_mushroom_facts()
        self.load_message_queue()
        self.load_last_seen()
        response = f"PRIVMSG {channel} :{sender}, Clov3r Successfully Reloaded.\r\n"
        self.send(response)
        print(f"Sent: {response} to {channel}")

    async def last_command(self, channel, sender, content):
        try:
            # Try to parse the command: !last [1-10]
            parts = content.split(' ')
            num_messages_str = parts[1] if len(parts) > 1 and parts[1].isdigit() else None

            # Set default number of messages to 1 if not provided
            num_messages = 1 if num_messages_str is None else min(int(num_messages_str), 10)

            # Filter last messages for the specific channel
            channel_messages = [(msg["timestamp"], msg["sender"], msg["content"]) for msg in self.last_messages if msg["channel"] == channel]

            # Take the last N messages (N=num_messages)
            last_n_messages = channel_messages[-num_messages:]

            # Send the last messages to the user via direct message
            if last_n_messages:
                response = f"PRIVMSG {sender} :[Last {num_messages} messages in {channel}]:\r\n"
                for timestamp, nickname, msg_content in last_n_messages:
                    response += f"PRIVMSG {sender} :[{timestamp}] <{nickname}> {msg_content}\r\n"

                # Add a delay before sending the response
                await asyncio.sleep(0.3)

                self.send(response)
                print(f"Sent last messages to {sender} via direct message")
            else:
                response = f"PRIVMSG {sender} :No messages found in {channel}\r\n"

                # Add a delay before sending the response
                await asyncio.sleep(0.3)

                self.send(response)
                print(f"Sent: {response} to {sender}")

        except ValueError:
            # Handle the case where there is no valid number after !last
            response = f"PRIVMSG {channel} :[Last 1 message in {channel}]:\r\n"
            last_message = channel_messages[-1] if channel_messages else ("Unknown", "No messages found")
            response += f"PRIVMSG {sender} :[{last_message[0]}] <{last_message[1]}> {last_message[2]}\r\n"

            # Add a delay before sending the response
            await asyncio.sleep(0.3)

            self.send(response)
            print(f"Sent last messages to {sender} via direct message")

    async def seen_command(self, channel, sender, content):
        try:
            # Parse the command: !seen username
            _, username = content.split(' ', 1)

            # Convert the username to lowercase for case-insensitive comparison
            username_lower = username.lower()

            # Check if the user has been seen in the specific channel
            if username_lower in self.last_seen and channel in self.last_seen[username_lower]:
                last_seen_info = self.last_seen[username_lower][channel]
                response = f"PRIVMSG {channel} :{sender}, <{username}> {last_seen_info['message']} @ {last_seen_info['timestamp']}\r\n"
            else:
                response = f"PRIVMSG {channel} :{sender}, I haven't seen {username} recently in {channel}.\r\n"

            self.send(response)
            print(f"Sent: {response} to {channel}")

        except ValueError:
            response = f"PRIVMSG {channel} :Invalid !seen command format. Use: !seen username\r\n"
            self.send(response)

    async def purge_message_queue(self, channel, sender):
        # Clear the message_queue
        self.message_queue = {}

        # Save the empty message_queue
        self.save_message_queue()

        response = f"PRIVMSG {channel} :{sender}, the message queue has been purged.\r\n"
        self.send(response)
        print(f"Sent: {response} to {channel}")

    def handle_info_command(self, channel, sender):
        response = f"Hiya! I'm Clov3r, a friendly IRC bot, {sender}! Please follow the rules: use !topic to see them."
        self.send(f'PRIVMSG {channel} :{response}\r\n')
        print(f"Sent: {response} to {channel}")

    async def dice_roll(self, args, channel, sender):
        print("Dice roll requested...")

        # Map the die type to its maximum value
        dice_map = {
            "d2": 2,
            "d4": 4,
            "d6": 6,
            "d8": 8,
            "d10": 10,
            "d100": 100,
            "d12": 12,
            "d20": 20,
            "d120": 120
        }

        # Use regular expression to parse the input with custom dice notation
        match = re.match(r'(\d*)[dD](\d+)([+\-]\d+)?', args)
        if not match:
            # Check for custom dice notation
            custom_match = re.match(r'(\d+)[dD](\d+)([+\-]\d+)?', args)
            if not custom_match:
                # If no match, default to d20
                num_dice = 1
                die_type = "d20"
                modifier = 0
            else:
                # Extract the number of dice, the type of each die, and the modifier for custom dice
                num_dice = int(custom_match.group(1))
                die_type = f"d{custom_match.group(2)}"
                modifier = int(custom_match.group(3)) if custom_match.group(3) else 0
        else:
            # Extract the number of dice, the type of each die, and the modifier for standard dice
            num_dice = int(match.group(1)) if match.group(1) else 1
            die_type = f"d{match.group(2)}"
            modifier = int(match.group(3)) if match.group(3) else 0

        # Check if the total number of dice doesn't exceed 9999
        if num_dice * (dice_map.get(die_type, int(die_type[1:])) or int(die_type[1:])) > 9999:
            response = f"{sender}, Please request a more reasonable number of dice (up to 9999).\r\n"
            self.send(f'PRIVMSG {channel} :{response}\r\n')
            return

        # Set a reasonable limit on the number of dice rolls (e.g., 1000)
        max_allowed_rolls = 10
        if num_dice > max_allowed_rolls:
            response = f"{sender}, Please request a more reasonable number of rolls (up to {max_allowed_rolls}).\r\n"
            self.send(f'PRIVMSG {channel} :{response}\r\n')
            return

        # Check if the die_type is in the predefined dice_map or it's a custom die
        max_value = dice_map.get(die_type)

        if not max_value and die_type:
            max_value = int(die_type[1:])

        if not max_value:
            available_dice = ', '.join(dice_map.keys())
            response = f"{sender}, Invalid die type: {die_type}. Available dice types: {available_dice}.\r\n"
            self.send(f'PRIVMSG {channel} :{response}\r\n')
            return

        # Roll the dice the specified number of times, but limit to max_allowed_rolls
        rolls = [random.randint(1, max_value) for _ in range(min(num_dice, max_allowed_rolls))]

        # Apply the modifier
        total = sum(rolls) + modifier

        # Format the action message with both individual rolls and total
        individual_rolls = ', '.join(map(str, rolls))
        action_message = f"{sender} has rolled {num_dice} {die_type}'s modifier of {modifier}: {individual_rolls}. Total: {total}"

        print(f'Sending message: {action_message}')
        self.send(f'PRIVMSG {channel} :{action_message}\r\n')

    async def handle_tell_command(self, channel, sender, content):
        try:
            # Parse the command: !tell username message
            _, username, message = content.split(' ', 2)

            # Convert the recipient's nickname to lowercase
            username_lower = username.lower()

            # Create a tuple key with the channel and recipient's lowercase nickname
            key = (channel, username_lower)

            # Check if the key exists in the message_queue
            if key not in self.message_queue:
                self.message_queue[key] = []

            # Get the current time in UTC
            utc_now = datetime.datetime.now(pytz.utc)

            # Save the message for the user in the specific channel with a timestamp
            timestamp = utc_now.strftime("%Y-%m-%d %H:%M:%S UTC")
            self.message_queue[key].append((username, sender, message, timestamp))

            # Notify the user that the message is saved
            response = f"PRIVMSG {channel} :{sender}, I'll tell {username} that when they return."
            self.send(response)
            self.save_message_queue()
        except ValueError:
            response = f"PRIVMSG {channel} :Invalid !tell command format. Use: !tell username message"
            self.send(response)

    async def send_saved_messages(self, message):
        sender_match = re.match(r":(\S+)!\S+@\S+", message)
        sender = sender_match.group(1) if sender_match else "Unknown Sender"
        channel = message.split('PRIVMSG')[1].split(':')[0].strip()

        # Iterate over keys in the message_queue and find matching recipients
        for key, messages in list(self.message_queue.items()):
            try:
                (saved_channel, saved_recipient) = key
            except ValueError:
                print(f"Error unpacking key: {key}")
                continue

            # Convert the sender and recipient nicknames to lowercase for case-insensitive comparison
            sender_lower = sender.lower()
            recipient_lower = saved_recipient.lower()

            # Check if the lowercase nicknames match and the channels are the same
            if sender_lower == recipient_lower and channel == saved_channel:
                # Send each saved message to the user
                for (username, recipient, saved_message, timestamp) in messages:
                    response = f"PRIVMSG {channel} :<{recipient}> {saved_message} at: ({timestamp})\r\n"
                    self.send(response)
                    print(f"Sent saved message to {channel}: {response}")

                # Clear the saved messages for the user in the specific channel
                del self.message_queue[key]
                self.save_message_queue()

    def send_random_mushroom_fact(self, channel, criteria=None):
        if self.mushroom_facts:
            filtered_facts = [fact for fact in self.mushroom_facts if criteria(fact)]
            
            if filtered_facts:
                random_fact = random.choice(filtered_facts)
                self.send(f"PRIVMSG {channel} :{random_fact}\r\n")
                print(f"Sent mushroom fact to {channel}: {random_fact}")
            else:
                print("No matching mushroom facts found based on the criteria.")

    def extract_factoid_criteria(self, args):
        # Example: !fact parasol
        # Extract the criteria from the user's command (e.g., "parasol")
        return lambda fact: args.lower() in fact.lower()

    async def handle_sed_command(self, channel, sender, content):
        try:
            # Extract old, new, and flags using regex
            match = re.match(r's/(.*?)/(.*?)(?:/([gi]*))?$', content)
            if match:
                old, new, flags = match.groups()
                flags = flags if flags else ''  # Set flags to an empty string if not provided
            else:
                raise ValueError("Invalid sed command format")

            print(f"Processing sed command - Old: {old}, New: {new}, Flags: {flags}")

            # Iterate over the entire message history for the specified channel and replace matching messages
            corrected_message = None
            for formatted_message in reversed(self.last_messages):
                if formatted_message["channel"] != channel:
                    continue  # Skip messages from other channels

                original_message = formatted_message["content"]
                original_sender = formatted_message["sender"]

                print(f"Checking message - Original: {original_message}")

                # Handle regex flags
                regex_flags = re.IGNORECASE if 'i' in flags else 0

                # Set count based on the global flag
                count = 0 if 'g' in flags else 1

                # Replace old with new using regex substitution
                replaced_message = re.sub(old, new, original_message, flags=regex_flags, count=count)

                # Check if the message was actually replaced
                if replaced_message != original_message:
                    corrected_message = replaced_message
                    print(f"Match found - Corrected: {corrected_message}")
                    break  # Stop when the first corrected message is found

            # Check if a match was found
            if corrected_message is not None:
                # Send the corrected message to the channel
                response = f"PRIVMSG {channel} :[Sed] <{original_sender}> {corrected_message}\r\n"
                self.send(response)
                print(f"Sent: {response} to {channel}")
            else:
                response = f"PRIVMSG {channel} :[Sed] No matching message found to correct\r\n"
                self.send(response)
                print(f"Sent: {response} to {channel}")

        except re.error as e:
            response = f"PRIVMSG {channel} :[Sed] Invalid sed command: {str(e)}\r\n"
            self.send(response)
            print(f"Sent: {response} to {channel}")
        except ValueError:
            response = f"PRIVMSG {channel} :[Sed] Invalid sed command format\r\n"
            self.send(response)
            print(f"Sent: {response} to {channel}")

    async def disconnect(self):
        if self.writer:
            self.writer.close()
            asyncio.shield(self.writer.wait_closed())

    async def main_loop(self):
        try:
            self.load_mushroom_facts()
            self.load_message_queue()
            self.load_last_seen()
            await self.connect()

            # Identify with NickServ
            await self.identify_with_nickserv()
            for channel in self.channels:
                await self.join_channel(channel)

            keep_alive_task = asyncio.create_task(self.keep_alive())
            handle_messages_task = asyncio.create_task(self.handle_messages())

            # Wait for either of the tasks to finish
            done, pending = await asyncio.wait(
                [keep_alive_task, handle_messages_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel the remaining tasks
            for task in pending:
                task.cancel()

            # Wait for the canceled tasks to finish
            await asyncio.gather(*pending, return_exceptions=True)
        except KeyboardInterrupt:
            print("KeyboardInterrupt received. Shutting down...")
        finally:
            self.save_message_queue()
            self.save_last_seen()
            await self.disconnect()

    async def start(self):
        await self.main_loop()


if __name__ == "__main__":
    bot = IRCBot.from_config_file("bot_config.ini")
    asyncio.run(bot.start())

import asyncio
import configparser
import datetime
import html
import ipaddress
import json
import pytz
import random
import re
import io
import requests
import ssl
import threading
import time
from PIL import Image
from bs4 import BeautifulSoup
from collections import deque
from html import escape
from typing import Optional

class IRCBot:
    def __init__(self, nickname, channels, server, port=6697, use_ssl=True, admin_list=None, nickserv_password=None,channels_features=None):
        self.nickname = nickname
        self.channels_features = channels_features
        self.channels = channels if isinstance(channels, list) else [channels]
        self.nickserv_password = nickserv_password
        self.server = server
        self.port = port
        self.use_ssl = use_ssl
        self.admin_list = set(admin_list) if admin_list else set()
        self.last_messages = {channel: deque(maxlen=200) for channel in channels}
        self.mushroom_facts = []
        self.message_queue = {}
        self.last_seen = {}
        self.last_command_time = {}
        self.reader = None
        self.writer = None
        self.last_issued_command = None
        self.MIN_COMMAND_INTERVAL = 5
        self.lock = asyncio.Lock()
        self.url_regex = re.compile(r'https?://\S+')
        self.headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

    @classmethod
    def from_config_file(cls, config_file, features_file='channels_features.json'):
        # Load features from the JSON file
        with open(features_file, 'r') as f:
            channels_features = json.load(f)

        config = configparser.ConfigParser()
        config.read(config_file)
        bot_config = config['BotConfig']
        admin_list = config.get('AdminConfig', 'admin_list', fallback='').split(',')
        channels = bot_config.get('channels').split(',')
        nickserv_password = bot_config.get('nickserv_password', fallback=None)

        return cls(
            nickname=bot_config.get('nickname'),
            channels_features=channels_features,
            channels=channels,
            server=bot_config.get('server'),
            port=int(bot_config.get('port', 6697)),
            use_ssl=bot_config.getboolean('use_ssl', True),
            admin_list=admin_list,
            nickserv_password=nickserv_password
        )

    async def handle_channel_features(self, channel, command):
        # Check if the specified channel has the given feature enabled
        if channel in self.channels_features and command in self.channels_features[channel]:
            return True
        return False

    def save_last_seen(self, filename="last_seen.json"):
        try:
            with open(filename, "w") as file:
                json.dump(self.last_seen, file, indent=2)
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

    def load_channel_features(self, filename="channels_features.json"):
        # Load features from the JSON file
        try:
            with open(filename, 'r') as f:
                self.channels_features = json.load(f)
            print("Successfully Loaded Channel Features")
        except FileNotFoundError:
            print(f"{filename} file not found.")
        except Exception as e:
            print(f"Error loading channel features: {e}")

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
                json.dump(serialized_message_queue, file, indent=2)
            
            # Save the backup file
            with open(backup_filename, "w") as backup_file:
                json.dump(serialized_message_queue, backup_file, indent=2)
        
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

        await self.send(f"USER {self.nickname} 0 * :{self.nickname}")
        await self.send(f"NICK {self.nickname}")

    async def identify_with_nickserv(self):
        motd_received = False
        while True:
            data = await self.reader.read(2048)
            message = data.decode("UTF-8")
            print(message)

            if "376" in message:  # End of MOTD
                await self.send(f'PRIVMSG NickServ :IDENTIFY {self.nickname} {self.nickserv_password}\r\n')
                print("Sent NickServ authentication.")  # End of MOTD
                motd_received = True

            if motd_received and "396" in message:  # NickServ authentication successful
                for channel in self.channels:
                    await self.join_channel(channel)
                print("Joined channels after NickServ authentication.")
                break

    async def send(self, message):
        safe_msg = await self.sanitize_input(message)
        self.writer.write((safe_msg + '\r\n').encode())

    async def join_channel(self, channel):
        await self.send(f"JOIN {channel}")
        await asyncio.sleep(0.3)

    async def keep_alive(self):
        while True:
            async with self.lock:
                await self.send("PING :keepalive")
                print(f"Sent: PING to Server: {self.server}")
            await asyncio.sleep(195)

    async def save_message(self, message, channel):
        sender_match = re.match(r":(\S+)!\S+@\S+", message)
        sender = sender_match.group(1) if sender_match else "Unknown Sender"

        # Split the message into parts
        message_parts = message.split('PRIVMSG')[1].split(':', 1)

        # Extract the content of the message
        content = message_parts[1].strip()

        # Determine the local Dublin time
        local_time = datetime.datetime.now(pytz.timezone('Europe/Dublin'))

        # Check if it's a CTCP ACTION message
        if content.startswith("\x01ACTION") and content.endswith("\x01"):
            # If it's an action message, extract the content without the triggers
            action_content = content[len("\x01ACTION") : -len("\x01")]
            formatted_message = {
                "timestamp": local_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "sender": sender,
                "content": f"* {sender}{action_content}"  # Format as an action message
            }
        else:
            # Regular PRIVMSG message
            formatted_message = {
                "timestamp": local_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "sender": sender,
                "content": content
            }

        # Check if the channel key exists in self.last_messages, if not, create it
        if channel not in self.last_messages:
            self.last_messages[channel] = []

        # Append the formatted message to the specific channel's message history
        self.last_messages[channel].append(formatted_message)

    async def handle_messages(self):
        global disconnect_requested
        disconnect_requested = False
        while not disconnect_requested:
            data = await self.reader.read(1000)
            cleaned_data = data.decode(errors='replace')
            print(cleaned_data)

            if "PING" in cleaned_data:
                await self.send("PONG " + cleaned_data.split()[1])
            elif "PRIVMSG" in cleaned_data:
                # Extract sender, channel, and content information
                sender_match = re.match(r":(\S+)!\S+@\S+", cleaned_data)
                sender = sender_match.group(1) if sender_match else "Unknown Sender"
                channel = cleaned_data.split('PRIVMSG')[1].split(':')[0].strip()
                content = cleaned_data.split('PRIVMSG')[1].split(':', 1)[1].strip()

                # Record the last seen information for the user
                if await self.handle_channel_features(channel, '.record'):
                    await self.record_last_seen(sender, channel, content)
                    self.save_last_seen()

                if await self.handle_channel_features(channel, '.usercommands'):
                    await self.user_commands(cleaned_data)

                if await self.handle_channel_features(channel, '.urlparse'):
                    await self.detect_and_parse_urls(cleaned_data)

                await self.save_message(cleaned_data, channel)
                await self.send_saved_messages(cleaned_data)

        print("Disconnecting...")
        await self.disconnect()

    async def record_last_seen(self, sender, channel, content):
        # Existing code for recording last seen information
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

    async def get_channel_topic(self, channel: str) -> Optional[str]:
        await self.send(f"TOPIC {channel}")
        data = await self.reader.read(2048)
        message = data.decode("UTF-8")

        if "332" in message:  # TOPIC message
            topic = message.split(":", 2)[2].strip()
            return topic
        else:
            return None

    async def sanitize_input(self, malicious_input):
        decoded_input = html.unescape(malicious_input)
        safe_output = ''.join(char for char in decoded_input if (32 <= ord(char) <= 126) or char in '\x03\x02\x0F\x16\x1D\x1F\x01')
        return safe_output

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
            # Send a HEAD request to get the content length and type
            head_response = requests.head(url, headers=self.headers)
            head_response.raise_for_status()

            # Get the content length from the headers
            content_length = int(head_response.headers.get('Content-Length', 0))

            # Check if the content type is an image, plain text, audio, or ISO file
            content_type = head_response.headers.get('Content-Type', '').lower()

            # Define the maximum file size allowed (in bytes)
            MAX_FILE_SIZE = 256 * 1024 * 1024  # 256 MB

            # Define the list of executable file extensions
            EXECUTABLE_FILE_EXTENSIONS = ['.exe', '.dll', '.bat', '.jar', '.iso']

            if content_type.startswith('image/'):
                return "Image"
            elif content_type.startswith('text/plain'):
                # Handle plain text file
                return "Plain text file"
            elif content_type.startswith('audio/'):
                return "Audio file"
            elif content_type == 'application/x-iso9660-image':
                return "ISO"
            elif content_length > MAX_FILE_SIZE:
                return "Max Size"
            elif any(url.lower().endswith(ext) for ext in EXECUTABLE_FILE_EXTENSIONS):
                return "Banned File Type"
            else:
                # Download the content and extract the webpage title
                response = requests.get(url, headers=self.headers, timeout=(1.0, 0.5))
                response.raise_for_status()

                # Decode response content using appropriate encoding
                encoding = response.encoding if 'charset' in response.headers.get('content-type', '').lower() else None
                soup = BeautifulSoup(response.content, 'html.parser', from_encoding=encoding)

                # Function to get a list of sanitized titles from meta tags
                def get_meta_content(title_tag, meta_tags):
                    # Extract title from title tag
                    title_from_title_tag = title_tag.text.strip() if title_tag else None

                    # Extract titles from meta tags
                    titles_from_meta_tags = [meta_tag.attrs.get('content', '').strip() for meta_tag in meta_tags]

                    # Combine and prioritize titles
                    all_titles = [title_from_title_tag] + [title for title in titles_from_meta_tags if title]

                    return all_titles

                # Look for the first og:title meta tag, Twitter Card title, Dublin Core title,
                # meta tag with name attribute set to "title", and the title tag directly in the head
                og_title_tags = soup.find_all('meta', {'property': 'og:title'})
                twitter_title_tags = soup.find_all('meta', {'name': 'twitter:title'})
                dc_title_tags = soup.find_all('meta', {'name': 'DC.title'})
                meta_name_title_tags = soup.find_all('meta', {'name': 'title'})
                title_tag = soup.head.title

                # Combine all meta tags
                all_meta_tags = og_title_tags + twitter_title_tags + dc_title_tags + meta_name_title_tags

                # Get all titles from title tag and meta tags
                all_titles = get_meta_content(title_tag, all_meta_tags)

                if all_titles:
                    sanitized_titles = [html.unescape(title) for title in all_titles]
                    title = sanitized_titles[0]
                    print(f"Extracted title from meta tags and title tag: {title}")
                    return title

                # If none of the above tags are found
                return "Title not found"

        except requests.exceptions.Timeout:
            print(f"Timeout retrieving webpage title for {url}")
            return "Timeout retrieving title"
        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 404:
                print(f"Webpage not found (404) for {url}")
                return "Webpage not found"
            else:
                print(f"HTTP error {http_err.response.status_code} for {url}: {http_err}")
                return "Error retrieving title"
        except requests.exceptions.RequestException as e:
            print(f"Error retrieving webpage title for {url}: {e}")
            return "Error retrieving title"

    def format_file_size(self, size_in_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_in_bytes < 1024.0:
                return f"{size_in_bytes:.2f} {unit}"
            size_in_bytes /= 1024.0

        return f"{size_in_bytes:.2f} TB"

    async def detect_and_parse_urls(self, message):
        sender, channel, content = await self.extract_message_parts(message)

        urls = self.url_regex.findall(content)

        for url in urls:
            try:
                if content.startswith("@"):
                    return

                if self.filter_private_ip(url):
                    print(f"Ignoring URL with private IP address: {url}")
                    continue

                response = await self.process_url(url)

                if response is None:
                    return

                # Send the response to the channel
                await self.send(f'PRIVMSG {channel} :{response}\r\n')
                print(f"Sent: {response} to {channel}")

            except requests.exceptions.Timeout:
                print(f"Timeout processing URL: {url}")
                continue

            except Exception as e:
                print(f"Error fetching or parsing URL: {e}")

    async def extract_message_parts(self, message):
        sender = message.split('!')[0][1:]
        channel = message.split('PRIVMSG')[1].split(':')[0].strip()
        content = message.split('PRIVMSG')[1].split(':', 1)[1].strip()
        return sender, channel, content

    async def process_url(self, url):
        if 'amazon.com' in url:
            return self.process_amazon_url(url)
        elif 'crates.io' in url:
            return self.process_crates_url(url)
        else:
            return await self.process_generic_url(url)

    def process_amazon_url(self, url):
        product_name = " ".join(url.split('/')[3].split('-')).title()
        return f"[Amazon] Product: {product_name}"

    def process_crates_url(self, url):
        # Extract the crate name and version from the URL
        parts = url.split('/')
        crate_name = parts[-2]
        crate_version = parts[-1]

        return f"[Webpage] crates.io: Rust Package Registry: {crate_name}{crate_version}"

    async def process_generic_url(self, url):
        file_name = url.split("/")[-1]

        if "." in file_name:
            file_extension = file_name.split(".")[-1].lower()
        else:
            file_extension = None

        webpage_title = await self.sanitize_input(await self.extract_webpage_title(url))
        print(f"webpage_title: {webpage_title}")

        match webpage_title:
            case "Title not found":
                return self.handle_title_not_found(url)
            case "Image":
                return await self.handle_image_url(url)
            case "Audio file":
                return await self.handle_audio_file(url)
            case "Plain text file":
                return await self.handle_text_file(url)
            case "Banned File Type":
                print(f"Banned File Type")
                return
            case "ISO":
                print(f"ISO")
                return
            case "Max Size":
                print(f"Max Size")
                return
            case "Timeout retrieving title":
                print(f"Timeout retrieving title")
                return
            case "Error retrieving title":
                print(f"Error retrieving title")
                return
            case "Webpage not found":
                print(f"Error 404 - not found")
                return
            case _:
                return self.return_page_title(url, webpage_title)

    def handle_title_not_found(self, url):
        site_name = url.split('/')[2]
        paste_code = url.split('/')[-1]
        return f"[Website] {site_name} paste: {paste_code}"

    async def handle_image_url(self, url):
        site_name = url.split('/')[2]
        paste_code = url.split('/')[-1]

        try:
            image_response = requests.get(url, headers=self.headers)
            image_size_bytes = len(image_response.content)
            formatted_image_size = self.format_file_size(image_size_bytes)

            # Use Pillow to get image dimensions
            image = Image.open(io.BytesIO(image_response.content))
            width, height = image.size
            image_dimensions = f"{width}x{height}"

        except Exception as e:
            print(f"Error fetching image size: {e}")
            formatted_image_size = "unknown size"
            image_dimensions = "N/A"

        return f"[Website] {site_name} (Image) {paste_code} - Size: {image_dimensions}/{formatted_image_size}"

    async def handle_audio_file(self, url):
        # Handle the case where it's an audio file.
        site_name = url.split('/')[2]
        paste_code = url.split('/')[-1]

        # Initialize the response variable with a default value
        response = f"[Website] {site_name} (Audio) {paste_code} - Size: unknown size"

        try:
            audio_response = requests.get(url, headers=self.headers, stream=True)
            audio_size_bytes = int(audio_response.headers.get('Content-Length', 0))

            formatted_audio_size = self.format_file_size(audio_size_bytes)
            response = f"[Website] {site_name} (Audio) {paste_code} - Size: {formatted_audio_size}"
        except Exception as e:
            print(f"Error fetching audio size: {e}")

        return response

    async def handle_text_file(self, url):
        # Handle the case where it's a plain text file.
        site_name = url.split('/')[2]
        paste_code = url.split('/')[-1]

        # Get the text file size using a GET request
        try:
            text_response = requests.get(url, headers=self.headers)
            text_size_bytes = len(text_response.content)

            formatted_text_size = self.format_file_size(text_size_bytes)
            response = f"[Website] {site_name} (Text) {paste_code} - Size: {formatted_text_size}"
        except Exception as e:
            print(f"Error fetching text file size: {e}")
            formatted_text_size = "unknown size"

        return response

    def return_page_title(self, url, webpage_title):
        # Directly return the webpage title
        return f"[Website] {webpage_title}"

    def get_available_commands(self, exclude_admin=True):
        # List all available commands (excluding admin commands by default)
        commands = [
            ".ping",
            ".roll",
            ".fact",
            ".last",
            ".tell",
            ".seen",
            ".info",
            ".topic",
            ".moo",
            ".moof",
            ".help",
            ".rollover",
            ".stats",
            ".version",
            ".sed",
            ".weather",
            ".admin",
        ]
        if exclude_admin:
            commands.remove(".admin")
        return commands

    def get_detailed_help(self, command):
        # Provide detailed help for specific commands
        help_dict = {
            ".ping": "Ping command: Check if the bot is responsive.",
            ".roll": "Roll command: Roll a specific die (1d20) Roll multiple dice (4d20) Example: .roll 2d20+4 Available modifiers: +",
            ".fact": "Fact command: Display a random mushroom fact. Use '.fact <criteria>' to filter facts.",
            ".last": "Last command: Display the last messages in the channel. Use '.last [1-10]' for specific messages.",
            ".tell": "Tell command: Save a message for a user. Use '.tell <user> <message>'.",
            ".seen": "Seen command: Check when a user was last seen. Use '.seen <user>'.",
            ".info": "Info command: Display information about the bot.",
            ".topic": "Topic command: Display the current channel topic.",
            ".moo": "Moo command: Greet the cow.",
            ".moof": "Moof command: The dogcow, named Clarus, is a bitmapped image designed by Susan Kare for the demonstration of page layout in the classic Mac OS.",
            ".help": "Help command: Display a list of available commands. Use '.help <command>' for detailed help.",
            ".rollover": "Rollover command: Woof woof!",
            ".stats": "Stats command: Display statistics for a user. Use '.stats <user>'.",
            ".version": "Version command: Shows the version of Clov3r",
            ".sed": "Sed usage s/change_this/to_this/(g/i). Flags are optional. To include word boundaries use \\b Example: s/\\btest\\b/stuff. I can also take regex.",
            ".weather": "Search weather forecast - example: .weather Ireland - Can search by address or other terms",
            ".admin": ".factadd - .quit - .join - .part - .op - .deop - .botop - .reload - .purge",
        }

        return help_dict.get(command, f"No detailed help available for {command}.")

    async def help_command(self, channel, sender, args=None, hostmask=None):
        # Get the list of available commands
        exclude_admin = False if hostmask in self.admin_list else True
        available_commands = self.get_available_commands(exclude_admin=exclude_admin)

        if args:
            # Remove the leading period (.) if present
            specific_command = args.split()[0].lstrip('.')

            # Check if the specific_command is a prefix of any command in available_commands
            matching_commands = [cmd for cmd in available_commands if cmd[1:] == specific_command]

            if matching_commands:
                # Provide detailed help for the specific command
                detailed_help = self.get_detailed_help(matching_commands[0])  # Assuming the first match
                response = f"PRIVMSG {channel} :{sender}, {detailed_help}\r\n"
            else:
                response = f"PRIVMSG {channel} :{sender}, Unknown command: {specific_command}\r\n"
        else:
            # Provide an overview of available commands
            response = f"PRIVMSG {channel} :{sender}, Commands: {', '.join(available_commands)} Use: .help <command> for more info.\r\n"

        # Send the response to the channel
        await self.send(response)
        print(f"Sent: {response} to {channel}")

    async def send_dog_cow_message(self, channel):
        dog_cow = "https://i.imgur.com/1S6flQw.gif"
        response = "Hello Clarus, dog or cow?"
        sound = "http://tinyurl.com/mooooof"
        await self.send(f'PRIVMSG {channel} :{response} {dog_cow} mooof {sound}\r\n')

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
            if await self.handle_channel_features(channel, '.sed'):
                await self.handle_sed_command(channel, sender, content)
        else:
            # Check if there are any words in the content before accessing the first word
            if content:
                # Check if user's last command time is tracked, and calculate time elapsed
                if sender in self.last_command_time:
                    time_elapsed = time.time() - self.last_command_time[sender]
                    if time_elapsed < self.MIN_COMMAND_INTERVAL:
                        return

                command = content.split()[0]
                args = content[len(command):].strip()

                if await self.handle_channel_features(channel, command):
                    match command:
                        case '.ping':
                            # PNOG
                            # Update last command time
                            self.last_command_time[sender] = time.time()
                            response = f"PRIVMSG {channel} :{sender}: PNOG!"
                            await self.send(response)

                        case '.weather':
                            self.last_command_time[sender] = time.time()
                            await self.get_weather(args, channel)

                        case '.roll':
                            # Roll the dice
                            self.last_command_time[sender] = time.time()
                            await self.dice_roll(args, channel, sender)

                        case '.fact':
                            # Extract the criteria from the user's command
                            self.last_command_time[sender] = time.time()
                            criteria = self.extract_factoid_criteria(args)
                            await self.send_random_mushroom_fact(channel, criteria)

                        case '.tell':
                            # Save a message for a user
                            self.last_command_time[sender] = time.time()
                            await self.handle_tell_command(channel, sender, content)

                        case '.info':
                            self.last_command_time[sender] = time.time()
                            await self.handle_info_command(channel, sender)

                        case '.moo':
                            self.last_command_time[sender] = time.time()
                            response = "Hi cow!"
                            await self.send(f'PRIVMSG {channel} :{response}\r\n')

                        case '.moof':
                            self.last_command_time[sender] = time.time()
                            await self.send_dog_cow_message(channel)

                        case '.topic':
                            # Get and send the channel topic
                            self.last_command_time[sender] = time.time()
                            topic = await self.get_channel_topic(channel)
                            if topic:
                                response = f"PRIVMSG {channel} :{topic}\r\n"
                            else:
                                response = f"PRIVMSG {channel} :Unable to retrieve the topic\r\n"
                            await self.send(response)
                            print(f"Sent: {response} to {channel}")

                        case '.help':
                            # Handle the help command
                            self.last_command_time[sender] = time.time()
                            await self.help_command(channel, sender, args, hostmask)

                        case '.seen':
                            # Handle the !seen command
                            self.last_command_time[sender] = time.time()
                            await self.seen_command(channel, sender, content)

                        case '.last':
                            self.last_command_time[sender] = time.time()
                            await self.last_command(channel, sender, content)

                        case '.version':
                            self.last_command_time[sender] = time.time()
                            version = "Clov3rBot Version 1.2"
                            response = f"PRIVMSG {channel} :{version}"
                            await self.send(response)

                        case '.rollover':
                            self.last_command_time[sender] = time.time()
                            # Perform the rollover action
                            barking_action = f"PRIVMSG {channel} :woof woof!"
                            action_message = f"PRIVMSG {channel} :\x01ACTION rolls over\x01"
                            await self.send(barking_action)
                            await self.send(action_message)

                        case '.stats':
                            self.last_command_time[sender] = time.time()
                            # Handle the !stats command
                            await self.stats_command(channel, sender, content)

                        case '.factadd' if hostmask in self.admin_list:
                            # Handle the !factadd command
                            new_fact = args.strip()
                            if new_fact:
                                self.mushroom_facts.append(new_fact)
                                self.save_mushroom_facts()
                                response = f"PRIVMSG {channel} :New mushroom fact added: {new_fact}"
                            else:
                                response = f"PRIVMSG {channel} :Please provide a valid mushroom fact."
                            await self.send(response)

                        case '.quit' if hostmask in self.admin_list:
                            # Quits the bot from the network.
                            response = f"PRIVMSG {channel} :Acknowledged {sender} quitting..."
                            await self.send(response)
                            disconnect_requested = True

                        case '.op' if hostmask in self.admin_list:
                            # Op the user
                            await self.send(f"MODE {channel} +o {sender}\r\n")

                        case '.deop' if hostmask in self.admin_list:
                            # Deop the user
                            await self.send(f"MODE {channel} -o {sender}\r\n")

                        case '.botop' if hostmask in self.admin_list:
                            # Op the bot using Chanserv
                            await self.send(f"PRIVMSG Chanserv :OP {channel} {self.nickname}\r\n")

                        case '.join' if hostmask in self.admin_list:
                            # Join a specified channel
                            if args:
                                new_channel = args.split()[0]
                                await self.send(f"JOIN {new_channel}\r\n")

                        case '.part' if hostmask in self.admin_list:
                            # Part from a specified channel
                            if args:
                                part_channel = args.split()[0]
                                await self.send(f"PART {part_channel}\r\n")

                        case '.reload' if hostmask in self.admin_list:
                            # Reload lists/dicts
                            await self.reload_command(channel, sender)

                        case '.purge' if hostmask in self.admin_list:
                            await self.purge_message_queue(channel, sender)

    async def geocode_location(self, location):
        # If the location is empty, return None
        if not location:
            return None, None

        try:
            # Make a request to retrieve the latitude and longitude for the location
            response = requests.get(f"https://geocode.maps.co/search?q={location}&api_key=65b583605ab6a403481192yza5a9247")
            print("Geocoding response status code:", response.status_code)
            print("Geocoding response content:", response.content)
            
            # Check if the request was successful (status code 200)
            if response.status_code == 200:
                # Parse the JSON response
                data = response.json()
                print("Geocoding response data:", data)
                
                # Extract latitude and longitude from the first place_id
                if data:
                    first_place = data[0]
                    latitude = round(float(first_place["lat"]), 4)
                    longitude = round(float(first_place["lon"]), 4)
                    return latitude, longitude

            # If unable to get latitude and longitude from the location
            print("Unable to geocode the location:", location)
            return None, None
            
        except Exception as e:
            print("An error occurred while geocoding:", e)
            return None, None

    async def get_weather(self, location, channel):
        # Set your user agent
        user_agent = "Clov3r_forecast, connorkim.kim3@gmail.com"

        # Get latitude and longitude from geocoding
        lat, lon = await self.geocode_location(location)

        # If unable to geocode the location, respond accordingly
        if lat is None or lon is None:
            response = f"PRIVMSG {channel} :Unable to get latitude and longitude for the location: {location}."
            await self.send(response)
            return

        # Get the forecast data for the given latitude and longitude
        try:
            # Make a request to retrieve the weather forecast data
            response = requests.get(f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}", headers={"User-Agent": user_agent})
            print("Response status code:", response.status_code)
            print("Response content:", response.content)
            
            # Check if the request was successful (status code 200)
            if response.status_code == 200:
                # Parse the JSON response
                data = response.json()
                
                # Extract relevant weather information
                timeseries = data.get("properties", {}).get("timeseries", [])
                
                if timeseries:
                    # Get the current forecast (first entry in timeseries)
                    current_forecast = timeseries[0]
                    print("Current forecast:", current_forecast)
                    
                    # Extract data from the current forecast
                    instant_details = current_forecast.get("data", {}).get("instant", {}).get("details", {})
                    print("Instant details:", instant_details)
                    next_1_hours_summary = current_forecast.get("data", {}).get("next_1_hours", {}).get("summary", {})
                    print("Next 1 hour summary:", next_1_hours_summary)
                    next_6_hours_summary = current_forecast.get("data", {}).get("next_6_hours", {}).get("summary", {})
                    print("Next 6 hours summary:", next_6_hours_summary)

                    # Calculate temperature in Fahrenheit
                    celsius_temp = instant_details.get('air_temperature')
                    fahrenheit_temp = (celsius_temp * 9/5) + 32
                    
                    # Construct weather forecast message
                    forecast_message = f"{location}, lat={lat}, lon={lon}:"
                    temp_message = f"Current temperature: {celsius_temp}C/{fahrenheit_temp}F"
                    cloud_message = f"Cloud coverage: {instant_details.get('cloud_area_fraction')}%"
                    humidity_message = f"Humidity: {instant_details.get('relative_humidity')}%"
                    wind_direction = f"Wind Direction: {instant_details.get('wind_from_direction')}"
                    wind_speed = f"Wind Speed: {instant_details.get('wind_speed')}"
                    nxt1hr_message = f"Next 1 hour: {next_1_hours_summary.get('symbol_code', 'N/A')}"
                    nxt6hr_message = f"Next 6 hours: {next_6_hours_summary.get('symbol_code', 'N/A')}"
                    
                    # Send weather forecast to the channel
                    response = f"PRIVMSG {channel} :{forecast_message} " + f"{temp_message} " + f"{cloud_message} " + f"{humidity_message} " + f"{wind_speed} " + f"{wind_direction} " + f"{nxt1hr_message} " + f"{nxt6hr_message} "
                    await self.send(response)
                    return
                
            # If no forecast available
            response = f"PRIVMSG {channel} :No forecast available for location: {location}."
            await self.send(response)
            
        except Exception as e:
            print("An error occurred:", e)
            response = f"PRIVMSG {channel} :An error occurred while fetching weather information."
            await self.send(response)

    async def stats_command(self, channel, sender, content):
        # Extract the target user from the command
        target_user = content.split()[1].strip() if len(content.split()) > 1 else None

        if target_user:
            # Convert the target user to lowercase for case-insensitive matching
            target_user = target_user.lower()

            # Check if the target user has chat count information
            if target_user in self.last_seen and channel in self.last_seen[target_user]:
                chat_count = self.last_seen[target_user][channel].get('chat_count', 0)
                response = f"PRIVMSG {channel} :{sender}, I've seen {target_user} send {chat_count} messages"
                await self.send(response)
            else:
                response = f"PRIVMSG {channel} :{sender}, no stats found for {target_user}"
                await self.send(response)
        else:
            response = f"PRIVMSG {channel} :{sender}, please provide a target user for the .stats command"
            await self.send(response)

    async def reload_command(self, channel, sender):
        self.channels_features = {}
        self.mushroom_facts = []
        self.last_seen = {}
        self.load_channel_features()
        self.load_mushroom_facts()
        self.load_message_queue()
        self.load_last_seen()
        response = f"PRIVMSG {channel} :{sender}, Clov3r Successfully Reloaded.\r\n"
        await self.send(response)
        print(f"Sent: {response} to {channel}")

    async def last_command(self, channel, sender, content):
        try:
            # Try to parse the command: !last [1-10]
            parts = content.split(' ')
            num_messages_str = parts[1] if len(parts) > 1 and parts[1].isdigit() else None

            # Set default number of messages to 1 if not provided
            num_messages = 1 if num_messages_str is None else min(int(num_messages_str), 10)

            # Filter last messages for the specific channel
            channel_messages = [(msg["timestamp"], msg["sender"], msg["content"]) for msg in self.last_messages[channel]]

            # Take the last N messages (N=num_messages)
            last_n_messages = channel_messages[-num_messages:]

            # Send the last messages to the user via direct message
            if last_n_messages:
                for timestamp, nickname, msg_content in last_n_messages:
                    response = f"PRIVMSG {sender} :[Last message in {channel}]: {timestamp} <{nickname}> {msg_content}\r\n"
                    
                    # Add a delay before sending each response
                    await asyncio.sleep(0.3)

                    await self.send(response)
                    print(f"Sent last message to {sender} via direct message")
            else:
                response = f"PRIVMSG {sender} :No messages found in {channel}\r\n"

                await self.send(response)
                print(f"Sent: {response} to {sender}")

        except ValueError:
            # Handle the case where there is no valid number after !last
            response = f"PRIVMSG {channel} :[Last 1 message in {channel}]:\r\n"
            last_message = channel_messages[-1] if channel_messages else ("Unknown", "No messages found")
            response += f"PRIVMSG {sender} :[{last_message[0]}] <{last_message[1]}> {last_message[2]}\r\n"

            await self.send(response)
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

                # Convert the timestamp to a datetime object
                timestamp = datetime.datetime.strptime(last_seen_info['timestamp'], "%Y-%m-%d %H:%M:%S")

                # Calculate the time difference
                time_difference = datetime.datetime.now() - timestamp

                # Format the time difference as a human-readable string
                formatted_time = self.format_timedelta(time_difference)

                response = f"PRIVMSG {channel} :{sender}, {formatted_time} ago <{username}> {last_seen_info['message']}\r\n"
            else:
                response = f"PRIVMSG {channel} :{sender}, I haven't seen {username} recently in {channel}.\r\n"

            await self.send(response)
            print(f"Sent: {response} to {channel}")

        except ValueError:
            response = f"PRIVMSG {channel} :Invalid .seen command format. Use: .seen username\r\n"
            await self.send(response)

    async def purge_message_queue(self, channel, sender):
        # Clear the message_queue
        self.message_queue = {}

        # Save the empty message_queue
        self.save_message_queue()

        response = f"PRIVMSG {channel} :{sender}, the message queue has been purged.\r\n"
        await self.send(response)
        print(f"Sent: {response} to {channel}")

    async def handle_info_command(self, channel, sender):
        response = f"Hiya! I'm Clov3r, a friendly IRC bot, {sender}! Please follow the rules: use .topic to see them."
        await self.send(f'PRIVMSG {channel} :{response}\r\n')
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
            await self.send(f'PRIVMSG {channel} :{response}\r\n')
            return

        # Set a reasonable limit on the number of dice rolls (e.g., 1000)
        max_allowed_rolls = 10
        if num_dice > max_allowed_rolls:
            response = f"{sender}, Please request a more reasonable number of rolls (up to {max_allowed_rolls}).\r\n"
            await self.send(f'PRIVMSG {channel} :{response}\r\n')
            return

        # Check if the die_type is in the predefined dice_map or it's a custom die
        max_value = dice_map.get(die_type)

        if not max_value and die_type:
            max_value = int(die_type[1:])

        if not max_value:
            available_dice = ', '.join(dice_map.keys())
            response = f"{sender}, Invalid die type: {die_type}. Available dice types: {available_dice}.\r\n"
            await self.send(f'PRIVMSG {channel} :{response}\r\n')
            return

        # Roll the dice the specified number of times, but limit to max_allowed_rolls
        rolls = [random.randint(1, max_value) for _ in range(min(num_dice, max_allowed_rolls))]

        # Apply the modifier
        total = sum(rolls) + modifier

        # Format the action message with both individual rolls and total
        individual_rolls = ', '.join(map(str, rolls))
        action_message = f"{sender} has rolled {num_dice} {die_type}'s modifier of {modifier}: {individual_rolls}. Total: {total}"

        print(f'Sending message: {action_message}')
        await self.send(f'PRIVMSG {channel} :{action_message}\r\n')

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
            await self.send(response)
            self.save_message_queue()
        except ValueError:
            response = f"PRIVMSG {channel} :Invalid .tell command format. Use: .tell username message"
            await self.send(response)

    def format_timedelta(self, delta):
        days, seconds = delta.days, delta.seconds
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m {seconds}s"

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
                # Get the current time
                current_time = datetime.datetime.utcnow()

                # Calculate the time difference once outside the loop
                for (username, recipient, saved_message, timestamp) in messages:
                    # Convert the timestamp to a datetime object
                    message_time = datetime.datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S %Z')

                    # Calculate the time difference
                    time_difference = current_time - message_time

                    # Format the time difference as a human-readable string
                    formatted_time_difference = self.format_timedelta(time_difference)

                    response = f"PRIVMSG {channel} :{sender}, {formatted_time_difference} ago <{recipient}> {saved_message} \r\n"
                    await self.send(response)
                    print(f"Sent saved message to {channel}: {response}")

                # Clear the saved messages for the user in the specific channel
                del self.message_queue[key]
                self.save_message_queue()

    async def send_random_mushroom_fact(self, channel, criteria=None):
        if self.mushroom_facts:
            filtered_facts = [fact for fact in self.mushroom_facts if criteria(fact)]
            
            if filtered_facts:
                random_fact = random.choice(filtered_facts)
                await self.send(f"PRIVMSG {channel} :{random_fact}\r\n")
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
            match = re.match(r's/(.*?)/(.*?)(?:/([gi]*))?$', content.replace(r'\/', '__SLASH__'))
            character_limit = 256
            if match:
                old, new, flags = match.groups()
                flags = flags if flags else ''  # Set flags to an empty string if not provided
                # Unescape double slashes
                old = old.replace("__SLASH__", "/")
                new = new.replace("__SLASH__", "/")

                # Check for word boundaries flag
                word_boundaries = r'\b' if '\\b' in old else ''

                # If the old string contains \d, replace it with [0-9]
                old = old.replace(r'\\d', r'[0-9]')

                # Update the regular expression with word boundaries
                regex_pattern = fr'{word_boundaries}{old}{word_boundaries}'

            else:
                raise ValueError("Invalid sed command format")

            # Check if the channel key exists in self.last_messages
            if channel in self.last_messages:
                # Iterate over the entire message history for the specified channel and replace matching messages
                corrected_message = None
                total_characters = 0
                for formatted_message in reversed(self.last_messages[channel]):
                    original_message = formatted_message["content"]
                    original_sender = formatted_message["sender"]

                    print(f"Checking message - Original: {original_message}")

                    # Handle regex flags
                    regex_flags = re.IGNORECASE if 'i' in flags else 0

                    # Set count based on the global flag
                    count = 0 if 'g' in flags else 1

                    # Extract color codes from the original message using the find_color_codes function
                    color_codes = self.find_color_codes(original_message)

                    # Replace old with new using regex substitution
                    replaced_message = re.sub(regex_pattern, new, original_message, flags=regex_flags, count=count)

                    # Apply color codes to the corrected message
                    corrected_message = ""
                    color_code_index = 0
                    for new_char in replaced_message:
                        if color_code_index < len(color_codes):
                            orig_char = original_message[color_code_index]

                            if orig_char.isprintable() or orig_char.isspace():
                                corrected_message += new_char
                            else:
                                # Skip non-printable characters in the original message
                                corrected_message += orig_char
                                color_code_index += 1
                        else:
                            corrected_message += new_char

                    # Append remaining color codes that were not replaced
                    corrected_message += ''.join(color_codes[color_code_index:])

                    # Calculate the total characters
                    total_characters += len(corrected_message)

                    # Check if the message was actually replaced and if it exceeds the character limit
                    if corrected_message != original_message and total_characters <= character_limit:
                        print(f"Match found - Corrected: {corrected_message}")
                        break  # Stop when the first corrected message is found

                # Check if a match was found
                if corrected_message is not None:
                    # Check if it's an action message (indicated by an asterisk at the beginning)
                    if original_message.startswith("*"):
                        # If it's an action message, send the corrected message without the original sender
                        response = f"PRIVMSG {channel} :[\x0303Sed\x03] {corrected_message}\r\n"
                    else:
                        # If it's a regular message, send the corrected message with the original sender
                        response = f"PRIVMSG {channel} :[\x0303Sed\x03] <{original_sender}> {corrected_message}\r\n"

                    await self.send(response)
                    print(f"Sent: {response} to {channel}")
                else:
                    response = f"PRIVMSG {channel} :[\x0304Sed\x03] No matching message found to correct\r\n"
                    await self.send(response)
                    print(f"Sent: {response} to {channel}")

            else:
                response = f"PRIVMSG {channel} :[\x0304Sed\x03] No message history found for the channel\r\n"
                await self.send(response)
                print(f"Sent: {response} to {channel}")

        except re.error as e:
            response = f"PRIVMSG {channel} :[\x0304Sed\x03] Invalid sed command: {str(e)}\r\n"
            await self.send(response)
            print(f"Sent: {response} to {channel}")
        except ValueError:
            response = f"PRIVMSG {channel} :[\x0304Sed\x03] Invalid sed command format\r\n"
            await self.send(response)
            print(f"Sent: {response} to {channel}")

    def find_color_codes(self, original_message):
        color_codes = []
        i = 0
        while i < len(original_message):
            if original_message[i] == '\x03':
                # Check if the following characters form a valid color code pattern
                code = original_message[i:i+3]
                if code[1:].isdigit() or (code[1] == ',' and code[2:].isdigit()):
                    color_codes.append(code)
                    i += 3
                else:
                    i += 1
            else:
                i += 1

        return color_codes

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

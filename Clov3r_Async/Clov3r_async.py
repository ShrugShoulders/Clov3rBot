import asyncio
import aiohttp
import base64
import configparser
import datetime
import html
import ipaddress
import json
import pytz
import random
import re
import io
import irctokens
import requests
import ssl
import threading
import time
import http.client
from urllib.parse import urlparse
from requests.exceptions import HTTPError, Timeout, RequestException
from PIL import Image
from bs4 import BeautifulSoup
from collections import deque
from html import escape, unescape
from typing import Optional
from title_scrape import Titlescraper

class IRCBot:
    def __init__(self, nickname, channels, server, port=6697, use_ssl=True, admin_list=None, nickserv_password=None, channels_features=None, ignore_list_file=None):
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
        self.ignore_list = []
        self.message_queue = {}
        self.last_seen = {}
        self.last_command_time = {}
        self.processed_urls = {}
        self.reader = None
        self.writer = None
        self.last_issued_command = None
        self.topic_command = False
        self.MIN_COMMAND_INTERVAL = 5
        self.lock = asyncio.Lock()
        self.url_regex = re.compile(r'https?://\S+')
        self.headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0', 'Accept-Encoding': 'identity'}

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

    async def save_last_messages(self, filename="messages.json"):
        # Convert deque objects to lists for JSON serialization
        serializable_last_messages = {channel: list(messages) for channel, messages in self.last_messages.items()}
        
        # Ensure the function is thread-safe if called concurrently
        async with self.lock:
            try:
                with open(filename, 'w') as file:
                    json.dump(serializable_last_messages, file, indent=2)
                print(f"Saved last messages to {filename}")
            except Exception as e:
                print(f"Error saving last messages: {e}")

    def load_ignore_list(self):
        file_path = 'ignore_list.txt'
        try:
            with open(file_path, 'r') as file:
                self.ignore_list = [line.strip() for line in file.readlines() if line.strip()]
                print("Ignore List Loaded Successfully")
        except FileNotFoundError:
            print(f"Warning: Ignore list file '{file_path}' not found. Continuing with an empty ignore list.")
        except Exception as e:
            print(f"Error loading ignore list from '{file_path}': {e}")

    async def load_last_messages(self, filename="messages.json"):
        # Ensure the function is thread-safe if called concurrently
        async with self.lock:
            try:
                with open(filename, 'r') as file:
                    # Load messages from the file
                    loaded_messages = json.load(file)
                
                # Convert lists back to deque objects and update self.last_messages
                self.last_messages = {channel: deque(messages, maxlen=200) for channel, messages in loaded_messages.items()}
                print(f"Loaded last messages from {filename}")
            except FileNotFoundError:
                print(f"{filename} not found. Starting with an empty message history.")
            except Exception as e:
                print(f"Error loading last messages: {e}")

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
        await self.wait_for_motd()

    async def wait_for_motd(self):
        print("Waiting for MOTD to complete...")
        while True:
            data = await self.reader.read(2048)
            message = data.decode("UTF-8")
            print(message)
            if "376" in message or "422" in message:  # MOTD End or No MOTD
                print("MOTD complete. Proceeding with SASL authentication.")
                await self.identify_with_sasl()
                break
            elif "PING" in message:
                # Respond to PINGs from the server to stay connected
                split_message = message.split()
                await self.send(f"PONG {split_message[1]}")

    async def identify_with_sasl(self):
        # Request SASL capability immediately upon connecting
        await self.send("CAP REQ :sasl\r\n")

        while True:
            data = await self.reader.read(2048)
            message = data.decode("UTF-8")
            print(message)

            match message:
                case _ if f"CAP {self.nickname} ACK :sasl" in message:
                    # Server supports SASL, proceed with authentication
                    await self.send("AUTHENTICATE PLAIN\r\n")

                case _ if "AUTHENTICATE +" in message:
                    # Server is ready for authentication data
                    auth_string = f"{self.nickname}\0{self.nickname}\0{self.nickserv_password}"
                    encoded_auth = base64.b64encode(auth_string.encode("UTF-8")).decode("UTF-8")
                    await self.send(f"AUTHENTICATE {encoded_auth}\r\n")

                case _ if "903" in message:
                    # SASL authentication successful
                    await self.send("CAP END\r\n")
                    print("SASL authentication successful.")
                    for channel in self.channels:
                        await self.join_channel(channel)
                    print("Joined channels after SASL authentication.")
                    break

                case _ if "904" in message or "905" in message:
                    # SASL authentication failed
                    print("SASL authentication failed.")
                    break

                case _ if "PING" in message:
                    # Respond to PINGs from the server
                    split_message = message.split()
                    await self.send(f"PONG {split_message[1]}")

    async def send(self, message):
        safe_msg = await self.sanitize_input(message)
        self.writer.write((safe_msg + '\r\n').encode('utf-8'))

    async def join_channel(self, channel):
        await self.send(f"JOIN {channel}")
        await asyncio.sleep(0.3)

    async def keep_alive(self):
        while True:
            async with self.lock:
                await self.send("PING :keepalive")
                print(f"Sent: PING to Server: {self.server}")
            await asyncio.sleep(195)

    async def clear_urls(self):
        while True:
            async with self.lock:
                self.processed_urls = {}
                print(f"Cleared URLS")
            await asyncio.sleep(600)

    async def save_message(self, sender, content, channel):
        # Use system's current time for Unix timestamp
        unix_timestamp = int(datetime.datetime.now().timestamp())

        # Check if it's a CTCP ACTION message
        if content.startswith("\x01ACTION") and content.endswith("\x01"):
            # If it's an action message, extract the content without the triggers
            action_content = content[len("\x01ACTION"): -len("\x01")]
            formatted_message = {
                "timestamp": unix_timestamp,
                "sender": sender,
                "content": f"* {sender}{action_content}"  # Format as an action message
            }
        else:
            # Regular PRIVMSG message
            formatted_message = {
                "timestamp": unix_timestamp,
                "sender": sender,
                "content": content
            }

        # Append the formatted message to the specific channel's message history
        if channel not in self.last_messages:
            self.last_messages[channel] = []
        self.last_messages[channel].append(formatted_message)

    async def handle_messages(self):
        global disconnect_requested
        disconnect_requested = False
        buffer = ""  # Initialize an empty buffer for accumulating data

        while not disconnect_requested:
            data = await self.reader.read(1000)
            buffer += data.decode('UTF-8', errors='replace')

            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.rstrip('\r').strip().lstrip()

                if not line:
                    continue

                tokens = irctokens.tokenise(line)

                if tokens.command == "PING":
                    await self.send(f"PONG {tokens.params[0].strip().lstrip()}")
                elif tokens.command == "PRIVMSG":
                    sender = tokens.source.split('!')[0].strip().lstrip() if tokens.source else "Unknown Sender"
                    hostmask = tokens.source.strip() if tokens.source else "Unknown Hostmask"
                    channel = tokens.params[0].strip().lstrip()
                    content = tokens.params[1].strip().lstrip()
                    parts = content.split()
                    normalized_content = ' '.join(parts)

                    if sender in self.ignore_list:
                        print(f"Ignored message from {sender}")
                        continue

                    await self.save_message(sender, normalized_content, channel)
                    await self.send_saved_messages(sender, channel)

                    if await self.handle_channel_features(channel, '.record'.strip().lstrip()):
                        await self.record_last_seen(sender, channel, normalized_content)
                        self.save_last_seen()

                    if await self.handle_channel_features(channel, '.usercommands'.strip().lstrip()):
                        await self.user_commands(sender, channel, normalized_content, hostmask)

                    if await self.handle_channel_features(channel, '.urlparse'.strip().lstrip()):
                        await self.detect_and_parse_urls(sender, channel, normalized_content)
                elif tokens.command == "332":  # TOPIC message
                    if self.topic_command == True:
                        topic = tokens.params[2].strip().lstrip()
                        channel = tokens.params[1].strip().lstrip()
                        print(f"{topic}")
                        if topic:
                            response = f"PRIVMSG {channel} :{topic}\r\n"
                        else:
                            response = f"PRIVMSG {channel} :Unable to retrieve the topic\r\n"
                        await self.send(response)
                        print(f"Sent: {response} to {channel}")
                        self.topic_command = False

        print("Disconnecting...")
        await self.disconnect()

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

    async def get_channel_topic(self, channel: str) -> Optional[str]:
        self.topic_command = True
        await self.send(f"TOPIC {channel}")

    async def sanitize_input(self, malicious_input):
        decoded_input = html.unescape(malicious_input)
        # Allow Unicode characters through by checking if the character is not a control character,
        # except for the whitelisted control codes ('\x03', '\x02', '\x0F', '\x16', '\x1D', '\x1F', '\x01').
        # This version considers characters outside the basic ASCII control characters as allowed,
        # including extended Unicode characters.
        safe_output = ''.join(
            char for char in decoded_input
            if (ord(char) > 31 and ord(char) != 127) or char in '\x03\x02\x0F\x16\x1E\x1D\x1F\x01'
        )
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

    async def detect_and_parse_urls(self, sender, channel, content):
        titlescrape = Titlescraper()

        urls = self.url_regex.findall(content)

        for url in urls:
            try:
                if content.startswith("@"):
                    return

                if self.filter_private_ip(url):
                    print(f"Ignoring URL with private IP address: {url}")
                    continue

                # Check if the URL has already been processed for the current channel
                if url in self.processed_urls and channel in self.processed_urls[url]:
                    print(f"URL already processed for this channel: {url}")
                    continue

                response = await titlescrape.process_url(url)

                if response is None:
                    return

                # Send the response to the channel
                await self.send(f'PRIVMSG {channel} :{response}\r\n')
                print(f"Sent: {response} to {channel}")

                # Update the dictionary with the processed URL and channel
                if url not in self.processed_urls:
                    self.processed_urls[url] = set()
                self.processed_urls[url].add(channel)

            except requests.exceptions.Timeout:
                print(f"Timeout processing URL: {url}")
                continue

            except Exception as e:
                print(f"Error fetching or parsing URL: {e}")
                titlescrape.handle_title_not_found(url, e)
                continue

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
            ".color",
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
            ".sed": "Sed usage s/change_this/to_this/(g/i). Flags are optional. To include word boundaries use \\b Example: s/\\btest\\b/stuff. I can also take regex. https://tinyurl.com/sedinfo",
            ".weather": "Search weather forecast - example: .weather Ireland - Can search by address or other terms",
            ".color": "The Colors command takes either r,g,b values or hex #000000",
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

    async def user_commands(self, sender, channel, content, hostmask):
        global disconnect_requested
        print(f"Sender: {sender}")
        print(f"Channel: {channel}")
        print(f"Content: {content}")
        print(f"Full Hostmask: {hostmask}")

        # Ignore empty or whitespace-only content
        if not content.strip():
            return

        # Check if the message starts with 's/' for sed-like command
        if content and content.startswith(('s/', 'S/')):
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

                command = content.split()[0].strip()
                args = content[len(command):].strip()

                if await self.handle_channel_features(channel, command):
                    match command:
                        case '.ping':
                            # PNOG
                            # Update last command time
                            self.last_command_time[sender] = time.time()
                            response = f"PRIVMSG {channel} :[\x0303Ping\x03] {sender}: PNOG!"
                            await self.send(response)

                        case '.color':
                            self.last_command_time[sender] = time.time()
                            input_value = args.strip()

                            # Strip out the '#' if it's present
                            if input_value.startswith('#'):
                                input_value = input_value[1:]

                            # Check if input is in RGB decimal format
                            if ',' in input_value:
                                try:
                                    rgb_values = [int(x) for x in input_value.split(',')]
                                    if len(rgb_values) == 3 and all(0 <= x <= 255 for x in rgb_values):
                                        # Convert RGB to hex
                                        color_code = ''.join(f'{x:02x}' for x in rgb_values)
                                    else:
                                        raise ValueError
                                except ValueError:
                                    response = f"PRIVMSG {channel} :Invalid RGB format. Please use the format R,G,B where R, G, and B are between 0 and 255."
                                    await self.send(response)
                                    return
                            else:
                                color_code = input_value

                            # Validate hex color code
                            if len(color_code) == 6 and all(c in '0123456789abcdefABCDEF' for c in color_code):
                                await self.get_color_info(color_code, channel)
                            else:
                                response = f"PRIVMSG {channel} :Invalid color code format. Please use a 6-digit hexadecimal code or R,G,B format."
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
                            await self.get_channel_topic(channel)

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
                            await self.save_last_messages()
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

    async def get_color_info(self, color_code, channel):
        url = f"https://www.color-hex.com/color/{color_code}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Assuming the title tag contains the color name/description
                    title = soup.title.string if soup.title else 'Unknown Color' #soup.find('title')
                    
                    # Construct the response message with the title and URL
                    response_message = f"Color information for {color_code} ({title}): {url}"
                else:
                    response_message = "Failed to retrieve color information."
        
        await self.send(f"PRIVMSG {channel} :{response_message}")

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
                    forecast_message = f"[\x0311{location}\x03]:" #, lat={lat}, lon={lon}
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
        self.ignore_list = []
        self.last_seen = {}
        self.load_channel_features()
        self.load_mushroom_facts()
        self.load_message_queue()
        self.load_last_seen()
        self.load_ignore_list()
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

            # Get the current time in UTC without pytz
            utc_now = datetime.datetime.utcnow()

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

    async def send_saved_messages(self, sender, channel):
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
            match = re.match(r'[sS]/(.*?)/(.*?)(?:/([gi]*))?(/(\d*))?(?:/(.*))?$', content.replace(r'\/', '__SLASH__'))
            character_limit = 460
            if match:
                old, new, flags, _, occurrence, target_nickname = match.groups()  # Adjusted unpacking to match the new group structure
                flags = flags if flags else ''  # Ensure flags are set to an empty string if not provided
                occurrence = int(occurrence) if occurrence else 0  # Convert occurrence to an integer if provided, defaulting to 0
                # Unescape slashes that were replaced
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
                corrected_message = None
                original_sender_corrected = None
                total_characters = 0
                regex_flags = re.IGNORECASE if 'i' in flags else 0
                for formatted_message in reversed(self.last_messages[channel]):
                    original_message = formatted_message["content"]
                    original_sender = formatted_message["sender"]

                    # Skip messages not matching the target nickname if specified
                    if target_nickname and original_sender != target_nickname:
                        continue

                    if re.match(r'^[sS]/.*/.*/?[gi]*\d*$', original_message):
                        continue

                    print(f"Checking message - Original: <{original_sender}> {original_message}")

                    if re.search(regex_pattern, original_message, flags=regex_flags):
                        if occurrence:
                            # Function to replace only the specified occurrence
                            def replace_nth(match):
                                nonlocal occurrence
                                occurrence -= 1
                                return new if occurrence == 0 else match.group(0)

                            replaced_message = re.sub(regex_pattern, replace_nth, original_message, flags=regex_flags)
                        else:
                            count = 0 if 'g' in flags else 1
                            replaced_message = re.sub(regex_pattern, new, original_message, flags=regex_flags, count=count)

                        total_characters += len(replaced_message)

                        if replaced_message != original_message and total_characters <= character_limit:
                            corrected_message = replaced_message
                            original_sender_corrected = original_sender
                            print(f"Match found - Corrected: <{original_sender_corrected}> {corrected_message}")
                            
                            break

                if corrected_message is not None and original_sender_corrected is not None:
                    if corrected_message.startswith("*"):
                        response = f"PRIVMSG {channel} :[\x0303Sed\x03] {corrected_message}\r\n"
                    else:
                        response = f"PRIVMSG {channel} :[\x0303Sed\x03] <{original_sender_corrected}> {corrected_message}\r\n"

                    await self.send(response)
                    print(f"Sent: {response} to {channel}")
                else:
                    response = f"PRIVMSG {channel} :[\x0304Sed\x03] No matching message found to correct from {target_nickname}\r\n"
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

    async def disconnect(self):
        if self.writer:
            self.writer.close()
            asyncio.shield(self.writer.wait_closed())

    async def main_loop(self):
        try:
            self.load_mushroom_facts()
            self.load_message_queue()
            self.load_last_seen()
            self.load_ignore_list()
            await self.load_last_messages()
            await self.connect()

            keep_alive_task = asyncio.create_task(self.keep_alive())
            handle_messages_task = asyncio.create_task(self.handle_messages())
            clear_urls_task = asyncio.create_task(self.clear_urls())

            # Wait for either of the tasks to finish
            done, pending = await asyncio.wait(
                [keep_alive_task, handle_messages_task, clear_urls_task],
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

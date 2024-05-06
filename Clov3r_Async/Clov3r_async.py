import asyncio
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
import ssl
import time
from typing import Optional
from collections import deque
from gentoo_bugs import get_bug_details
from sed import handle_sed_command
from weather import WeatherSnag
from colorfetch import handle_color_command
from help import get_available_commands
from title_scrape import Titlescraper
from google_api import Googlesearch
from duckduckgo import duck_search, duck_translate
from reddit_urls import parse_reddit_url

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
        self.quotes = {}
        self.message_queue = {}
        self.last_seen = {}
        self.last_command_time = {}
        self.processed_urls = {}
        self.response_queue = asyncio.Queue()
        self.active_quotes = {}
        self.reader = None
        self.writer = None
        self.last_issued_command = None
        self.topic_command = False
        self.MIN_COMMAND_INTERVAL = 5
        self.lock = asyncio.Lock()
        self.url_regex = re.compile(r'https?://[^\s\x00-\x1F\x7F]+')
        self.search = Googlesearch()

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
        while True:
            try:
                if self.use_ssl:
                    ssl_context = ssl.create_default_context()
                    self.reader, self.writer = await asyncio.open_connection(self.server, self.port, ssl=ssl_context)
                else:
                    self.reader, self.writer = await asyncio.open_connection(self.server, self.port)

                await self.send(f'USER {self.nickname} 0 * :{self.nickname}')
                await self.send(f'NICK {self.nickname}')
                await self.identify_with_sasl()
                break
            except NameInUseError as e:
                print(e)
                self.error_log(e, nick_in_use=True)
                await asyncio.sleep(270)
            except (ConnectionError, OSError):
                e = "Connection failed. Retrying in 270 seconds..."
                print(e)
                self.error_log(e)
                await asyncio.sleep(270)

    async def identify_with_sasl(self):
        # Request SASL capability immediately upon connecting
        buffer = ""
        SASL_successful = False
        logged_in = False
        motd_received = False
        await self.send('CAP LS 302')

        while True:
            data = await self.reader.read(4096)
            if not data:
                raise ConnectionError("Connection lost while waiting for the welcome message.")

            decoded_data = data.decode('UTF-8', errors='ignore')
            buffer += decoded_data
            while '\r\n' in buffer:
                line, buffer = buffer.split('\r\n', 1)
                tokens = irctokens.tokenise(line)
                print(line)

                match tokens.command:
                    case "CAP":
                        await self.handle_cap(tokens)

                    case "AUTHENTICATE":
                        # Server is ready for authentication data
                        await self.handle_sasl_auth(tokens)

                    case "900":
                        logged_in = True

                    case "903":
                        # SASL authentication successful
                        await self.send("CAP END\r\n")
                        print("SASL authentication successful.")
                        SASL_successful = True
                        if logged_in and SASL_successful and motd_received:
                            for channel in self.channels:
                                await self.join_channel(channel)
                            print("Joined channels")
                            return

                    case "904" | "905":
                        # SASL authentication failed
                        print("SASL authentication failed.")

                    case "376" | "422":
                        print("MOTD complete.")
                        motd_received = True
                        if logged_in and SASL_successful:
                            for channel in self.channels:
                                await self.join_channel(channel)
                            print("Joined channels on MOTD.")
                            return

                    case "433":
                        raise NameInUseError("Nickname is already in use (error 433)")

                    case "513":
                        await self.send(f"PONG {tokens.params[-1]}")

                    case "PING":
                        # Respond to PINGs from the server
                        await self.send(f"PONG {tokens.params[0]}")

    async def handle_cap(self, tokens):
        print("Handling CAP")
        if "LS" in tokens.params:
            await self.send("CAP REQ :sasl")
        elif "ACK" in tokens.params:
            await self.send("AUTHENTICATE PLAIN")

    async def handle_sasl_auth(self, tokens):
        print("Sent SASL Auth")
        if tokens.params[0] == '+':
            auth_string = f"{self.nickname}\0{self.nickname}\0{self.nickserv_password}"
            encoded_auth = base64.b64encode(auth_string.encode("UTF-8")).decode("UTF-8")
            await self.send(f"AUTHENTICATE {encoded_auth}\r\n")

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

    async def handle_ctcp(self, tokens):
        hostmask = tokens.hostmask
        sender = tokens.hostmask.nickname
        target = tokens.params[0]
        message = tokens.params[1]

        # Detect if this is a CTCP message
        if message.startswith('\x01') and message.endswith('\x01'):
            ctcp_command = message[1:-1].split(' ', 1)[0]  # Extract the CTCP command
            ctcp_content = message[1:-1].split(' ', 1)[1] if ' ' in message else None  # Extract the content if present

            match ctcp_command:
                case "VERSION" | "version":
                    response = f"NOTICE {sender} :\x01VERSION Clov3rbot v1.2\x01\r\n"
                    await self.send(response)
                    print(f"CTCP: {sender} {target}: {ctcp_command}\n")

                case "PING" | "ping":
                    response = f"NOTICE {sender} :\x01PING {ctcp_content}\x01\r\n"
                    await self.send(response)
                    print(f"CTCP: {sender} {target}: {ctcp_command}\n")

                case "ACTION":
                    print(f"Sender: {sender}")
                    print(f"Channel: {target}")
                    print(f"Content: {message}")
                    print(f"Full Hostmask: {hostmask}")
                    await self.save_message(sender, message, target)

                case _:
                    print(f"Unhandled CTCP command: {ctcp_command}")

    def is_ctcp_command(self, message):
        return message.startswith('\x01') and message.endswith('\x01')

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

                    if self.is_ctcp_command(content):
                        await self.handle_ctcp(tokens)
                        continue

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

                    if await self.handle_channel_features(channel, '.redditparse'.strip().lstrip()):
                        response = await parse_reddit_url(normalized_content)
                        if response == None:
                            pass
                        else:
                            await self.response_queue.put((channel, response))

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

    async def send_responses_worker(self):
        """Worker to send responses from the queue with timing."""
        while True:
            channel, response = await self.response_queue.get()
            await self.send(f'PRIVMSG {channel} :{response}\r\n')
            print(f"Sent: {response} to {channel}")
            await asyncio.sleep(0.4)
            self.response_queue.task_done()

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

                if url in self.processed_urls.get(channel, set()):
                    print(f"URL already processed for this channel: {url}")
                    continue

                response = await titlescrape.process_url(url)

                if response is None:
                    return

                # Add the response to the queue instead of sending immediately
                await self.response_queue.put((channel, response))

                # Update the dictionary with the processed URL and channel
                if url not in self.processed_urls:
                    self.processed_urls[url] = set()
                self.processed_urls[url].add(channel)

            except Exception as e:
                print(f"Error fetching or parsing URL: {e}")
                titlescrape.handle_title_not_found(url, e)
                continue

    async def help_command(self, channel, sender, args=None, hostmask=None):
        # Get the list of available commands
        exclude_admin = False if hostmask in self.admin_list else True
        available_commands = get_available_commands(exclude_admin=exclude_admin)

        if args:
            from help import get_detailed_help
            # Remove the leading period (.) if present
            specific_command = args.split()[0].lstrip('.')

            # Check if the specific_command is a prefix of any command in available_commands
            matching_commands = [cmd for cmd in available_commands if cmd[1:] == specific_command]

            if matching_commands:
                # Provide detailed help for the specific command
                detailed_help = get_detailed_help(matching_commands[0])  # Assuming the first match
                response = f"{sender}, {detailed_help}\r\n"
                await self.response_queue.put((channel, response))
            else:
                response = f"{sender}, Unknown command: {specific_command}\r\n"
                await self.response_queue.put((channel, response))
        else:
            # Provide an overview of available commands
            response = f"{sender}, Commands: {', '.join(available_commands)} Use: .help <command> for more info.\r\n"
            await self.response_queue.put((channel, response))

        print(f"Sent: {response} to {channel}")

    async def send_dog_cow_message(self, channel):
        dog_cow = "https://files.catbox.moe/8lk6xx.gif"
        response = "Hello Clarus, dog or cow?"
        sound = "http://tinyurl.com/mooooof"
        await self.send(f'PRIVMSG {channel} :{response} {dog_cow} mooof {sound}\r\n')

    def save_quotes(self, filename='quotes.json'):
        """Save the quotes dictionary to a JSON file."""
        try:
            with open(filename, 'w') as file:
                json.dump(self.quotes, file, indent=2)  # Use indent for pretty-printing
            print("Quotes saved successfully.")
        except Exception as e:
            print(f"Failed to save quotes: {e}")

    def load_quotes(self, filename='quotes.json'):
        """Load the quotes dictionary from a JSON file."""
        try:
            self.quotes = {}
            with open(filename, 'r') as file:
                self.quotes = json.load(file)
            print("Quotes loaded successfully.")
        except FileNotFoundError:
            print("Quotes file not found, starting with an empty dictionary.")
            return {}
        except Exception as e:
            print(f"Failed to load quotes: {e}")
            return {}

    async def handle_quote_commands(self, sender, channel, command, content):
        args = content.split(maxsplit=1)
        command_arg = args[1].strip() if len(args) > 1 else None

        if command == '.quote':
            if command_arg and command_arg.isdigit():
                quote_number = str(command_arg)  # Work with string for consistency
                # Ensure the channel exists in the quotes dictionary
                if channel in self.quotes and quote_number in self.quotes[channel]:
                    quote_info = self.quotes[channel][quote_number]
                    date = quote_info['date']
                    recorded_by = quote_info['recorded_by']
                    quote_content = quote_info['quote']

                    header = f"PRIVMSG {channel} :Quote #{quote_number} recorded by {recorded_by} on {date}:"
                    await self.send(header)
                    await asyncio.sleep(0.3)

                    for message in quote_content:
                        response = f"PRIVMSG {channel} :{message}"
                        await asyncio.sleep(0.3)
                        await self.send(response)
                else:
                    response = f"PRIVMSG {channel} :Invalid quote number."
                    await self.send(response)
            elif sender not in self.active_quotes:
                self.active_quotes[sender] = (channel, [])  # Track the channel and an empty list for quotes
                response = f"PRIVMSG {channel} :Start quoting messages from {sender}. Use '.endquote' to finish."
                await self.send(response)
            else:
                response = f"PRIVMSG {channel} :You have already started quoting. Use '.endquote' to finish."
                await self.send(response)

        elif command == '.endquote':
            if sender in self.active_quotes:
                channel_of_quote, quote_content = self.active_quotes.pop(sender)
                if quote_content:
                    # Initialize the channel in self.quotes if it does not exist
                    if channel_of_quote not in self.quotes:
                        self.quotes[channel_of_quote] = {}
                    quote_number = str(len(self.quotes[channel_of_quote]) + 1)
                    quote = {
                        'recorded_by': sender,
                        'date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'quote': quote_content
                    }
                    # Save the quote under the appropriate channel and quote number
                    self.quotes[channel_of_quote][quote_number] = quote
                    self.save_quotes()
                    self.load_quotes()
                    response = f"PRIVMSG {channel_of_quote} :Quote #{quote_number} recorded."
                else:
                    response = f"PRIVMSG {channel_of_quote} :No messages were quoted."
                await self.send(response)
            else:
                response = f"PRIVMSG {channel} :You have not started quoting. Use '.quote' to start."
                await self.send(response)

    async def user_commands(self, sender, channel, content, hostmask):
        global disconnect_requested
        print(f"Sender: {sender}")
        print(f"Channel: {channel}")
        print(f"Content: {content}")
        print(f"Full Hostmask: {hostmask}")

        # Ignore empty or whitespace-only content
        if not content.strip():
            return

        if sender in self.active_quotes:
            self.active_quotes[sender][1].append(content)

        # Check if the message starts with 's/' for sed-like command
        if content and content.startswith(('s', 'S')):
            if await self.handle_channel_features(channel, '.sed'):
                response = await handle_sed_command(channel, sender, content, self.last_messages)
                if response == None:
                    return
                else:
                    await self.response_queue.put((channel, response))
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
                            if hostmask in self.admin_list:
                                response = f"PRIVMSG {channel} :[\x0303Ping\x03] {sender}: PNOG!"
                                await self.send(response)
                            else:
                                self.last_command_time[sender] = time.time()
                                response = f"PRIVMSG {channel} :[\x0303Ping\x03] {sender}: PNOG!"
                                await self.send(response)

                        case '.yt':
                            if hostmask in self.admin_list:
                                response = self.search.process_youtube_search(args)
                                await self.response_queue.put((channel, response))
                            else:
                                self.last_command_time[sender] = time.time()
                                response = self.search.process_youtube_search(args)
                                await self.response_queue.put((channel, response))

                        case '.tr':
                            if hostmask in self.admin_list:
                                response = duck_translate(args)
                                await self.response_queue.put((channel, response))
                            else:
                                self.last_command_time[sender] = time.time()
                                response = duck_translate(args)
                                await self.response_queue.put((channel, response))

                        case '.g':
                            if hostmask in self.admin_list:
                                response = self.search.google_it(args)
                                await self.response_queue.put((channel, response))
                            else:
                                self.last_command_time[sender] = time.time()
                                response = self.search.google_it(args)
                                await self.response_queue.put((channel, response))

                        case '.ddg':
                            if hostmask in self.admin_list:
                                response = duck_search(args, channel)
                                await self.response_queue.put((channel, response))
                            else:
                                self.last_command_time[sender] = time.time()
                                response = duck_search(args, channel)
                                await self.response_queue.put((channel, response))

                        case '.quote' | '.endquote':
                            await self.handle_quote_commands(sender, channel, command, content)

                        case '.color':
                            if hostmask in self.admin_list:
                                response = await handle_color_command(sender, channel, args)
                                await self.send(response)
                            else:
                                self.last_command_time[sender] = time.time()
                                response = await handle_color_command(sender, channel, args)
                                await self.send(response)

                        case '.weather':
                            if hostmask in self.admin_list:
                                snag = WeatherSnag()
                                response = await snag.get_weather(args, channel)
                                await self.send(response)
                            else:
                                self.last_command_time[sender] = time.time()
                                snag = WeatherSnag()
                                response = await snag.get_weather(args, channel)
                                await self.send(response)

                        case '.roll':
                            # Roll the dice
                            if hostmask in self.admin_list:
                                await self.dice_roll(args, channel, sender)
                            else:
                                self.last_command_time[sender] = time.time()
                                await self.dice_roll(args, channel, sender)

                        case '.fact':
                            # Extract the criteria from the user's command
                            if hostmask in self.admin_list:
                                criteria = self.extract_factoid_criteria(args)
                                await self.send_random_mushroom_fact(channel, criteria)
                            else:
                                self.last_command_time[sender] = time.time()
                                criteria = self.extract_factoid_criteria(args)
                                await self.send_random_mushroom_fact(channel, criteria)

                        case '.tell':
                            # Save a message for a user
                            if hostmask in self.admin_list:
                                await self.handle_tell_command(channel, sender, content)
                            else:
                                self.last_command_time[sender] = time.time()
                                await self.handle_tell_command(channel, sender, content)

                        case '.info':
                            if hostmask in self.admin_list:
                                await self.handle_info_command(channel, sender)
                            else:
                                self.last_command_time[sender] = time.time()
                                await self.handle_info_command(channel, sender)

                        case '.moo':
                            if hostmask in self.admin_list:
                                response = "Hi cow!"
                                await self.send(f'PRIVMSG {channel} :{response}\r\n')
                            else:
                                self.last_command_time[sender] = time.time()
                                response = "Hi cow!"
                                await self.send(f'PRIVMSG {channel} :{response}\r\n')

                        case '.moof':
                            if hostmask in self.admin_list:
                                await self.send_dog_cow_message(channel)
                            else:
                                self.last_command_time[sender] = time.time()
                                await self.send_dog_cow_message(channel)

                        case '.topic':
                            # Get and send the channel topic
                            if hostmask in self.admin_list:
                                await self.get_channel_topic(channel)
                            else:
                                self.last_command_time[sender] = time.time()
                                await self.get_channel_topic(channel)

                        case '.help':
                            # Handle the help command
                            if hostmask in self.admin_list:
                                await self.help_command(channel, sender, args, hostmask)
                            else:
                                self.last_command_time[sender] = time.time()
                                await self.help_command(channel, sender, args, hostmask)

                        case '.seen':
                            # Handle the !seen command
                            if hostmask in self.admin_list:
                                await self.seen_command(channel, sender, content)
                            else:
                                self.last_command_time[sender] = time.time()
                                await self.seen_command(channel, sender, content)

                        case '.last':
                            if hostmask in self.admin_list:
                                await self.last_command(channel, sender, content)
                            else:
                                self.last_command_time[sender] = time.time()
                                await self.last_command(channel, sender, content)

                        case '.version':
                            if hostmask in self.admin_list:
                                version = "Clov3rBot Version 6.66666"
                                response = f"PRIVMSG {channel} :{version}"
                                await self.send(response)
                            else:
                                self.last_command_time[sender] = time.time()
                                version = "Clov3rBot Version 6.66666"
                                response = f"PRIVMSG {channel} :{version}"
                                await self.send(response)

                        case '.rollover':
                            # Perform the rollover action
                            if hostmask in self.admin_list:
                                barking_action = f"PRIVMSG {channel} :woof woof!"
                                action_message = f"PRIVMSG {channel} :\x01ACTION rolls over\x01"
                                await self.send(barking_action)
                                await self.send(action_message)
                            else:
                                self.last_command_time[sender] = time.time()
                                barking_action = f"PRIVMSG {channel} :woof woof!"
                                action_message = f"PRIVMSG {channel} :\x01ACTION rolls over\x01"
                                await self.send(barking_action)
                                await self.send(action_message)

                        case '.stats':
                            # Handle the !stats command
                            if hostmask in self.admin_list:
                                await self.stats_command(channel, sender, content)
                            else:                  
                                self.last_command_time[sender] = time.time()
                                await self.stats_command(channel, sender, content)

                        case '.bug':
                            if hostmask in self.admin_list:
                                response = get_bug_details(args)
                                await self.send(f"PRIVMSG {channel} :{response}")
                            else:
                                self.last_command_time[sender] = time.time()
                                response = get_bug_details(args)
                                await self.send(f"PRIVMSG {channel} :{response}")

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

    async def stats_command(self, channel, sender, content):
        # Extract the target user from the command
        target_user = content.split()[1].strip() if len(content.split()) > 1 else None

        if target_user:
            # Convert the target user to lowercase for case-insensitive matching
            target_user = target_user.lower()

            # Check if the target user has chat count information
            if target_user in self.last_seen and channel in self.last_seen[target_user]:
                chat_count = self.last_seen[target_user][channel].get('chat_count', 0)
                response = f"{sender}, I've seen {target_user} send {chat_count} messages"
                await self.response_queue.put((channel, response))
            else:
                response = f"{sender}, no stats found for {target_user}"
                await self.response_queue.put((channel, response))
        else:
            response = f"{sender}, please provide a target user for the .stats command"
            await self.response_queue.put((channel, response))

    async def reload_command(self, channel, sender):
        self.channels_features = {}
        self.mushroom_facts = []
        self.ignore_list = []
        self.last_seen = {}
        self.active_quotes = {}
        self.quotes = []
        self.load_channel_features()
        self.load_mushroom_facts()
        self.load_message_queue()
        self.load_last_seen()
        self.load_ignore_list()
        self.load_quotes()
        response = f"{sender}, Clov3r Successfully Reloaded.\r\n"
        await self.response_queue.put((channel, response))
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
            self.load_quotes()
            await self.load_last_messages()

            while True:
                try:
                    await self.connect()

                    keep_alive_task = asyncio.create_task(self.keep_alive())
                    handle_messages_task = asyncio.create_task(self.handle_messages())
                    clear_urls_task = asyncio.create_task(self.clear_urls())
                    response_handler = asyncio.create_task(self.send_responses_worker())

                    # Wait for either of the tasks to finish
                    done, pending = await asyncio.wait(
                        [keep_alive_task, handle_messages_task, clear_urls_task, response_handler],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # Cancel the remaining tasks
                    for task in pending:
                        task.cancel()

                    # Wait for the canceled tasks to finish
                    await asyncio.gather(*pending, return_exceptions=True)

                    if disconnect_requested == True:
                        break

                except (ConnectionError, OSError):
                    e = "Error In main_loop: Connection lost. Reconnecting..."
                    print(e)
                    self.error_log(e)
                    await asyncio.sleep(270)
                finally:
                    self.save_message_queue()
                    self.save_last_seen()
                    await self.disconnect()

        except KeyboardInterrupt:
            print("KeyboardInterrupt received. Shutting down...")
        except Exception as e:
            print(f"Unknown Exception: {e}")

    def error_log(self, e, nick_in_use=False):
        # Get the current datetime for the log entry
        now = datetime.datetime.now()
        if not nick_in_use:
            log_entry = f"{now}: Disconnection Occurred: {e}\n"
        elif nick_in_use:
            log_entry = f"{now}: Nickname Error: {e}\n"

        # Append the log entry to the file
        with open("error_log.txt", "a") as log_file:
            log_file.write(log_entry)

    async def start(self):
        await self.main_loop()


class NameInUseError(ConnectionError):
    pass


if __name__ == "__main__":
    bot = IRCBot.from_config_file("bot_config.ini")
    asyncio.run(bot.start())

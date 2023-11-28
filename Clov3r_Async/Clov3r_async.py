import asyncio
import ssl
import threading
import time
import requests
import re
import html
import configparser
import ipaddress
import bleach
from bs4 import BeautifulSoup
from html import escape
from collections import deque

class IRCBot:
    def __init__(self, nickname, channel, server, port=6697, use_ssl=True, admin_list=None):
        self.nickname = nickname
        self.channel = channel
        self.server = server
        self.port = port
        self.use_ssl = use_ssl
        self.admin_list = set(admin_list) if admin_list else set()
        self.last_messages = deque(maxlen=10)
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
        return cls(
            nickname=bot_config.get('nickname'),
            channel=bot_config.get('channel'),
            server=bot_config.get('server'),
            port=int(bot_config.get('port', 6697)),
            use_ssl=bot_config.getboolean('use_ssl', True),
            admin_list=admin_list
        )

    async def connect(self):
        if self.use_ssl:
            ssl_context = ssl.create_default_context()
            self.reader, self.writer = await asyncio.open_connection(self.server, self.port, ssl=ssl_context)
        else:
            self.reader, self.writer = await asyncio.open_connection(self.server, self.port)

        self.send(f"USER {self.nickname} 0 * :{self.nickname}")
        self.send(f"NICK {self.nickname}")

    def send(self, message):
        self.writer.write((message + '\r\n').encode())

    async def join_channel(self):
        self.send(f"JOIN {self.channel}")

    async def keep_alive(self):
        while True:
            async with self.lock:
                self.send("PING :keepalive")
                print(f"Sent: PING to Server: {self.server}")
            await asyncio.sleep(195)

    async def sanitize_input(self, malicious_input):
        decoded_input = html.unescape(malicious_input)
        safe_output = ''.join(char for char in decoded_input if 32 <= ord(char) <= 126)
        title_match = re.search(r'<title>(.+?)</title>', safe_output)
        if title_match:
            safe_output = title_match.group(1)
        return safe_output

    async def save_message(self, message):
        sender_match = re.match(r":(\S+)!\S+@\S+", message)
        sender = sender_match.group(1) if sender_match else "Unknown Sender"
        content = message.split('PRIVMSG')[1].split(':', 1)[1].strip()

        formatted_message = f"<{sender}> {content}"
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
                await self.user_commands(message)
                await self.detect_and_parse_urls(message)
                await self.save_message(message)

        print("Disconnecting...")
        await self.disconnect()

    def is_raw_text_paste(self, url):
        # Patterns for raw text pastes
        raw_text_patterns = [
            "pastebin.com/raw/",
            "bpa.st/raw/",
            "@raw",
        ]
        return any(pattern in url for pattern in raw_text_patterns)

    def filter_private_ip(self, url):
        # Extract the hostname from the URL
        hostname = re.findall(r'https?://([^/]+)', url)
        if hostname:
            hostname = hostname[0]
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private:
                    return True  # URL contains a private IP address
            except ValueError:
                pass  # Not an IP address

        return False

    async def extract_webpage_title(self, url):
        try:
            response = requests.get(url)
            soup = BeautifulSoup(response.text, 'html.parser')
            title_tag = soup.find('title')
            if title_tag:
                # Sanitize the title using bleach and filter out specific characters
                sanitized_title = bleach.clean(str(title_tag), tags=[], attributes={})
                return sanitized_title.strip()
            else:
                return "Title not found"
        except Exception as e:
            print(f"Error retrieving webpage title for {url}: {e}")
            return "Error retrieving title"

    async def detect_and_parse_urls(self, message):
        sender = message.split('!')[0][1:]
        channel = message.split('PRIVMSG')[1].split(':')[0].strip()
        content = message.split('PRIVMSG')[1].split(':', 1)[1].strip()

        urls = self.url_regex.findall(content)

        for url in urls:
            try:
                response = requests.get(url)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                title = await self.sanitize_input(soup.title.string.strip()) if soup.title else "No title found"

                # Integrate detect_and_handle_urls logic
                # Check if the message starts with '@' symbol and contains a list of URLs
                if content.startswith("@"):
                    return
                # Check if the message contains a URL
                url_matches = re.findall(r'(https?://\S+)', content)
                for url in url_matches:
                    # Filter out URLs with private IP addresses
                    if self.filter_private_ip(url):
                        print(f"Ignoring URL with private IP address: {url}")
                        continue

                    # Check if the URL is a raw text paste
                    if self.is_raw_text_paste(url):
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

                        # Process the URL based on its file extension
                        if file_extension in ["jpg", "jpeg", "png", "gif", "webp", "tiff", "eps", "ai", "indd", "raw"]:
                            response = f"image file: {file_name}"
                        elif file_extension in ["m4a", "flac", "wav", "wma", "aac", "mp3", "mp4", "avi", "webm", "mov", "wmv", "flv", "xm"]:
                            response = f"media file: {file_name}"
                        elif file_extension in ["sh", "bat", "rs", "cpp", "py", "java", "cs", "vb", "c", "txt", "pdf"]:
                            response = f"data file: {file_name}"
                        else:
                            # Sanitize the response before sending it to the channel
                            response = escape(webpage_title)

                    # Send the response to the channel
                    self.send(f'PRIVMSG {channel} :[Website]: {response}\r\n')
                    print(f"Sent: {response} to {channel}")

            except Exception as e:
                print(f"Error fetching or parsing URL: {e}")

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
        if content.startswith('s/'):
            await self.handle_sed_command(channel, sender, content)
        else:
            # Handle other commands as before
            match content.split()[0]:
                case '!hi':
                    response = f"PRIVMSG {channel} :Hi {sender}!"
                    self.send(response)

                case '!quit' if hostmask in self.admin_list:
                    response = f"PRIVMSG {channel} :Acknowledged {sender} quitting..."
                    self.send(response)
                    disconnect_requested = True

    async def handle_sed_command(self, channel, sender, content):
        try:
            # Add the missing third slash if not provided
            if content.count('/') == 1:
                content += '/'

            # Extract old, new, and flags using regex
            match = re.match(r's/(.*?)/(.*?)/?([gi]*)$', content)
            if match:
                old, new, flags = match.groups()
            else:
                raise ValueError("Invalid sed command format")

            # Get the last message from the deque
            last_message = self.last_messages[-1] if self.last_messages else None

            if last_message:
                # Handle regex flags
                regex_flags = re.IGNORECASE if 'i' in flags else 0

                # Set count based on the global flag
                count = 0 if 'g' in flags else 1

                # Replace old with new using regex substitution
                corrected_message = re.sub(old, new, last_message, flags=regex_flags, count=count)
                response = f"PRIVMSG {channel} :[Sed] {corrected_message}\r\n"
                self.send(response)
                print(f"Sent: {response} to {channel}")
            else:
                response = f"PRIVMSG {channel} :[Sed] No previous message to correct\r\n"
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
            await self.connect()
            await self.join_channel()

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
            await self.disconnect()

    async def start(self):
        await self.main_loop()


if __name__ == "__main__":
    bot = IRCBot.from_config_file("bot_config.ini")
    asyncio.run(bot.start())

import asyncio
import json
import datetime
import re
import ipaddress
from sed import handle_sed_command
from google_api import Googlesearch
from title_scrape import Titlescraper
from duckduckgo import duck_search, duck_translate
from reddit_urls import parse_reddit_url
from tell_command import Tell
from last_seen import Seenme
from gentoo_bugs import get_bug_details
from mushroom_facts import MushroomFacts
from help import help_command
from weather import WeatherSnag


class CommandHandler:
    def __init__(self):
        self.server_instance = None
        self.url_regex = re.compile(r'https?://[^\s\x00-\x1F\x7F]+')
        self.channels_features = {}  # Start with an empty dictionary
        self.search = Googlesearch()
        self.load_channels_features()  # Load channels features initially
        self.tatle = Tell()
        self.seen = Seenme()
        self.mycelia = MushroomFacts()
        self.snag = WeatherSnag()

    def load_channels_features(self):
        try:
            with open("channels_features.json", 'r') as file:
                self.channels_features = json.load(file)  # Load data into self.channels_features
            print("Channels features loaded successfully.")
        except FileNotFoundError:
            print("Error: The file 'channels_features.json' was not found.")
            self.channels_features = {}
        except json.JSONDecodeError:
            print("Error: The file 'channels_features.json' contains invalid JSON.")
            self.channels_features = {}

    async def handle_channel_features(self, channel, command):
        # Check if the specified channel has the given feature enabled
        if channel in self.channels_features and command in self.channels_features[channel]:
            return True
        return False

    async def handle_command(self, data):
        sender, channel, content, hostmask, last_messages, admin_list = data
        urls = self.url_regex.findall(content)  # `urls` is a list of all found URLs

        if not content.strip():
            print("Empty content received. Ignoring.")
            yield None

        response = None

        if content.startswith(('s', 'S')) and len(content) > 2:
            print("sed command")
            if await self.handle_channel_features(channel, '.sed'):
                print(f"Handling sed command from {sender} in channel {channel}.")
                response = await handle_sed_command(channel, sender, content, last_messages)
                if response == None:
                    pass
                else:
                    yield response  # Yield the response for sed command
        elif urls:
            if await self.handle_channel_features(channel, '.urlparse'):
                titlescrape = Titlescraper()
                for url in urls:
                    try:
                        url_response = await titlescrape.process_url(url)
                        asyncio.sleep(1)
                        yield url_response  # Yield each URL response individually
                    except Exception as e:
                        print(f"Error fetching or parsing URL: {e}")
            elif await self.handle_channel_features(channel, '.redditparse'):
                response = await parse_reddit_url(content)
                yield response
        else:
            command = content.split()[0].strip()
            args = content[len(command):].strip()

            if await self.handle_channel_features(channel, command):
                print(f"Handling command '{command}' from {sender} in channel {channel}.")
                match command:
                    case '.ping':
                        response = f"[\x0303Ping\x03] {sender}: PNOG!"
                    case '.help':
                        response = await help_command(channel, sender, args, hostmask, admin_list)
                    case '.version':
                        response = "Clov3rBot Version 4.0"
                    case '.moo':
                        response = "Hi cow!"
                    case '.moof':
                        dog_cow = "https://files.catbox.moe/8lk6xx.gif"
                        question = "Hello Clarus, dog or cow?"
                        sound = "http://tinyurl.com/mooooof"
                        response = f"{question} {dog_cow} mooof {sound}\r\n"
                    case '.seen':
                        response = await self.seen.seen_command(channel, sender, content)
                    case '.stats':
                        response = await self.seen.stats_command(channel, sender, content)
                    case '.tell':
                        response = await self.tatle.handle_tell_command(channel, sender, content)
                    case '.fact':
                        criteria = self.mycelia.extract_factoid_criteria(args)
                        response = await self.mycelia.send_random_mushroom_fact(channel, criteria)
                    case '.factadd' if hostmask in admin_list:
                        response = self.mycelia.fact_add(args)
                    case '.weather' | '.w' | '.wx':
                        response = await self.snag.get_weather(args)
                    case '.bug':
                        response = get_bug_details(args)
                    case '.yt':
                        response = self.search.process_youtube_search(args)
                    case '.g':
                        response = self.search.google_it(args)
                    case '.ddg':
                        response = duck_search(args, channel)
                    case '.tr':
                        response = duck_translate(args)
                    case '.part' if hostmask in admin_list:
                        if args:
                            part_channel = args.split()[0]
                            response = f"PART {part_channel}\r\n"
                    case '.join' if hostmask in admin_list:
                        if args:
                            new_channel = args.split()[0]
                            response = f"JOIN {new_channel}\r\n"
                    case '.op' if hostmask in admin_list:
                        response = f"MODE {channel} +o {sender}\r\n"
                    case '.deop' if hostmask in admin_list:
                        response = f"MODE {channel} -o {sender}\r\n"

                yield response  # Yield the response for the command

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

    async def handle_client(self, reader, writer):
        buffer = ""
        try:
            while True:
                data = await reader.read(2048)
                if not data:
                    break
                buffer += data.decode('utf-8')

                # Attempt to load a complete JSON object
                while buffer:
                    try:
                        data, index = json.JSONDecoder().raw_decode(buffer)
                        buffer = buffer[index:].lstrip()  # Remove processed part from buffer
                        print("Received data:", data)
                        
                        # Process all responses
                        responses = []
                        async for response in self.handle_command(data):
                            if response:
                                responses.append(response)

                        # Send all responses
                        for response in responses:
                            print("Sending response:", response)
                            writer.write(response.encode())
                            await writer.drain()
                        
                        # Close the connection after all responses are sent
                        writer.close()
                        await writer.wait_closed()
                        print("Connection closed.")
                        return  # Exit the function after closing the connection
                    except json.JSONDecodeError:
                        # If there's an error, continue to accumulate data
                        break
        except asyncio.CancelledError:
            print("Client connection cancelled.")
        finally:
            if not writer.is_closing():
                writer.close()
                await writer.wait_closed()
                print("Connection closed.")

    async def start_server(self):
        print("Server started and listening for connections...")
        self.server_instance = await asyncio.start_server(self.handle_client, '127.0.0.1', 8888)
        async with self.server_instance:
            await self.server_instance.serve_forever()

if __name__ == '__main__':
    command_handler = CommandHandler()
    asyncio.run(command_handler.start_server())
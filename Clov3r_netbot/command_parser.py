import asyncio
import json
import datetime
import re
import ipaddress
import importlib
import sys
import random
import types
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
from botpad import BotPad


class CommandHandler:
    def __init__(self):
        self.command_registry = {}
        self.server_instance = None
        self.url_regex = re.compile(r'https?://[^\s\x00-\x1F\x7F]+')
        self.separator_list = ['/', '_', '-', '~', '.', '|', '@', '+', '!', '`', ';', ':', '>', '<', '=', ')', '(', '*', '&', '^', '%', '#', '?', '[', ']', '{', '}','$', ',', "'", '"', '/', '\'', '\"']
        self.channels_features = {}
        self.search = Googlesearch()
        self.load_channels_features()
        self.tatle = Tell()
        self.seen = Seenme()
        self.mycelia = MushroomFacts()
        self.snag = WeatherSnag()
        self.scribe = BotPad()
        self.load_commands()
        self.snack_count = 0
        self.snack_level = 0
        self.snacks = []
        self.load_snack_data()
        self.load_snack_list()
        self.scraper = Titlescraper()

    def load_commands(self): # We need to try and load this from a text file or something. 
        self.register_command('.ping', self.handle_ping, needs_context=True)
        self.register_command('.help', help_command, full_context=True)
        self.register_command('.version', self.handle_version)
        self.register_command('.moo', self.handle_moo)
        self.register_command('.moof', self.handle_moof)
        self.register_command('.seen', self.seen.seen_command, needs_context=True)
        self.register_command('.stats', self.seen.stats_command, needs_context=True)
        self.register_command('.tell', self.tatle.handle_tell_command, needs_context=True)
        self.register_command('.fact', self.mycelia.send_random_mushroom_fact)
        self.register_command('.factadd', self.mycelia.fact_add)
        self.register_command('.weather', self.snag.get_weather)
        self.register_command('.w', self.snag.get_weather)
        self.register_command('.wx', self.snag.get_weather)
        self.register_command('.bug', get_bug_details)
        self.register_command('.yt', self.search.process_youtube_search)
        self.register_command('.g', self.search.google_it)
        self.register_command('.ddg', duck_search)
        self.register_command('.tr', duck_translate)
        self.register_command('.part', self.handle_part)
        self.register_command('.join', self.handle_join)
        self.register_command('.op', self.handle_op, needs_context=True)
        self.register_command('.deop', self.handle_deop, needs_context=True)
        self.register_command('.remod', self.reload_modules)
        self.register_command('.reload', self.reload_data)
        self.register_command('.botsnack', self.bot_snack, needs_context=True)
        self.register_command('.addsnack', self.add_snack)
        self.register_command('.memo', self.scribe.add_note, needs_context=True)
        self.register_command('.remind', self.scribe.get_notes, needs_context=True)
        self.register_command('.rmnote', self.scribe.clear_user_notes, needs_context=True)
        self.register_command('.topstats', self.seen.top_stats_command, needs_context=True)

    def register_command(self, command, handler, needs_context=False, full_context=False):
        self.command_registry[command] = {
            "handler": handler,
            "needs_context": needs_context,
            "full_context": full_context
        }

    def reload_modules(self, args):
        print("Reloading Modules...")
        module_names = [
            'sed', 'google_api', 'title_scrape', 'duckduckgo', 'reddit_urls',
            'tell_command', 'last_seen', 'gentoo_bugs', 'mushroom_facts',
            'help', 'weather'
        ]

        for module_name in module_names:
            if module_name in sys.modules:
                sys.modules[module_name] = importlib.reload(sys.modules[module_name])
                print(f"Reloaded module: {module_name}")

        self.command_registry.clear()

        # Re-initialize objects with the reloaded module references
        self.search = sys.modules["google_api"].Googlesearch()
        self.tatle = sys.modules["tell_command"].Tell()
        self.seen = sys.modules["last_seen"].Seenme()
        self.mycelia = sys.modules["mushroom_facts"].MushroomFacts()
        self.snag = sys.modules["weather"].WeatherSnag()

        # Reload commands to use the updated handlers
        self.load_commands()
        print("Modules Reloaded. :)")

    def reload_data(self, args):
        print("Reloading Data")
        self.channels_features = {}
        self.load_channels_features()
        print("Reloaded Data :)")

    def load_channels_features(self):
        try:
            with open("channels_features.json", 'r') as file:
                self.channels_features = json.load(file)
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
        urls = self.url_regex.findall(content)

        if not content.strip():
            print("Empty content received. Ignoring.")
            yield None

        response = None
        command_handled = False

        # Create all possible prefixes with 's' and 'S'
        prefixes = [f's{sep}' for sep in self.separator_list] + [f'S{sep}' for sep in self.separator_list]

        # Check if content starts with any of the commands
        command = content.split()[0].strip()
        args = content[len(command):].strip()

        if any(content.startswith(prefix) for prefix in prefixes) and len(content) > 2:
            print("sed command")
            if await self.handle_channel_features(channel, '.sed'):
                print(f"Handling sed command from {sender} in channel {channel}.")
                response = await handle_sed_command(channel, sender, content, last_messages)
                if response is not None:
                    yield response
                    command_handled = True

        if not command_handled and await self.handle_channel_features(channel, command):
            print(f"Handling command '{command}' from {sender} in channel {channel}.")
            if command in self.command_registry:
                handler_info = self.command_registry[command]
                handler = handler_info["handler"]
                needs_context = handler_info["needs_context"]
                full_context = handler_info["full_context"]

                if command in ['.part', '.join', '.op', '.deop', '.remod', '.addsnack'] and hostmask not in admin_list:
                    print(f"Unauthorized command attempt by {sender}.")
                else:
                    try:
                        if full_context:
                            response = await handler(channel, sender, args, hostmask, admin_list) if asyncio.iscoroutinefunction(handler) else handler(channel, sender, args, hostmask, admin_list)
                        elif needs_context:
                            response = await handler(channel, sender, content) if asyncio.iscoroutinefunction(handler) else handler(channel, sender, args)
                        else:
                            response = await handler(args) if asyncio.iscoroutinefunction(handler) else handler(args)
                    except ValueError as e:
                        print(e)
                    except Exception as e:
                        print(e)

                    if response is not None:
                        yield response
                        command_handled = True

        # Handle URLs if any and not a command
        if urls and not content.startswith('.'):
            if await self.handle_channel_features(channel, '.urlparse'):
                for url in urls:
                    try:
                        url_response = await self.scraper.process_url(url, channel)
                        await asyncio.sleep(1)
                        yield url_response
                    except Exception as e:
                        print(f"Error fetching or parsing URL: {e}")
            elif await self.handle_channel_features(channel, '.redditparse'):
                response = await parse_reddit_url(content)
                yield response

    def save_snack_data(self):
        data = {
            'snack_count': self.snack_count,
            'snack_level': self.snack_level
        }
        with open('snack_data.json', 'w') as file:
            json.dump(data, file)

    def load_snack_data(self):
        try:
            with open('snack_data.json', 'r') as file:
                data = json.load(file)
                self.snack_count = data['snack_count']
                self.snack_level = data['snack_level']
        except FileNotFoundError:
            self.snack_count = 0
            self.snack_level = 0

    def load_snack_list(self):
        try:
            with open('snacks.txt', 'r') as file:
                self.snacks = [line.strip() for line in file.readlines()]
        except FileNotFoundError:
            self.snacks = []

    def add_snack(self, snack):
        self.snacks.append(snack)
        self.save_snack_list()
        return "Snack Purchased"

    def save_snack_list(self):
        with open('snacks.txt', 'w') as file:
            for snack in self.snacks:
                file.write(snack + '\n')

    async def bot_snack(self, channel, sender, content):
        self.snack_count += 1
        self.save_snack_data()
        if self.snack_count == 100:
            self.snack_level += 1
            self.snack_count = 0
            self.save_snack_data()
        message = f"\x01ACTION munches on some {random.choice(self.snacks)} ({self.snack_count} lvl{self.snack_level})\x01"
        return f"{message}"

    async def handle_ping(self, channel, sender, args):
        ping_responses = ['PNOG!', 'PONG', 'what?', 'pong', 'doorbell']
        return f"[\x0303Ping\x03] {sender}: {random.choice(ping_responses)}"

    async def handle_version(self, args):
        return "Clov3rBot Version 4.0"

    async def handle_moo(self, args):
        return "Hi cow!"

    async def handle_moof(self, args):
        dog_cow = "https://files.catbox.moe/8lk6xx.gif"
        question = "Hello Clarus, dog or cow?"
        sound = "http://tinyurl.com/mooooof"
        return f"{question} {dog_cow} mooof {sound}\r\n"

    async def handle_part(self, args):
        if args:
            part_channel = args.split()[0]
            return f"PART {part_channel}\r\n"

    async def handle_join(self, args):
        if args:
            new_channel = args.split()[0]
            return f"JOIN {new_channel}\r\n"

    async def handle_op(self, channel, sender, args):
        return f"MODE {channel} +o {sender}\r\n"

    async def handle_deop(self, channel, sender, args):
        return f"MODE {channel} -o {sender}\r\n"

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
                        
                        # Process all responses
                        async for response in self.handle_command(data):
                            if isinstance(response, str):
                                # If it's a regular string response, send it directly
                                print("Sending response:", response)
                                writer.write(response.encode())
                                await writer.drain()
                            elif isinstance(response, types.GeneratorType):
                                # If it's a generator (e.g. from get_notes), iterate through it
                                for note in response:
                                    print("Sending Generator response:", note)
                                    writer.write(note.encode())
                                    await writer.drain()
                        
                        # Close the connection after all responses are sent
                        writer.close()
                        await writer.wait_closed()
                        print("Connection closed.")
                        return 
                    except json.JSONDecodeError:
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
            try:
                await self.server_instance.serve_forever()
            except asyncio.CancelledError:
                print("Server cancelled.")

if __name__ == '__main__':
    command_handler = CommandHandler()
    asyncio.run(command_handler.start_server())

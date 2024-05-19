import asyncio
import base64
import configparser
import datetime
import json
import random
import ssl
import time
import html
import irctokens
import re
from tell_command import Tell
from last_seen import Seenme


class Clov3r:
    def __init__(self, nickname, channels, server, port=6697, use_ssl=True, admin_list=None, nickserv_password=None, sasl_username=None):
        self.nickname = nickname
        self.sasl_username = sasl_username
        self.channels = channels
        self.server = server
        self.port = port
        self.use_ssl = use_ssl
        self.nickserv_password = nickserv_password
        self.reader = None
        self.writer = None
        self.disconnect_requested = False
        self.response_queue = asyncio.Queue()
        self.lock = asyncio.Lock()  # Added for the keep_alive function
        self.last_messages = {}
        self.admin_list = admin_list
        self.url_regex = re.compile(r'https?://[^\s\x00-\x1F\x7F]+')
        self.available_commands = ['s', 'S', '.weather', '.wx', '.w', '.help', '.fact', '.ping', '.yt', '.g', '.ddg', '.tr', '.tell', '.seen', '.stats', '.bug']
        self.admin_commands = ['.part', '.join', '.botop', '.deop', '.op', '.quit', '.factadd']
        self.response_track = set()
        self.speak = Tell()
        self.saw = Seenme()

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
            nickserv_password=nickserv_password,
            sasl_username=bot_config.get('sasl_username')
        )

    async def connect(self):
        while True:
            try:
                if self.use_ssl:
                    ssl_context = ssl.create_default_context()
                    self.reader, self.writer = await asyncio.open_connection(self.server, self.port, ssl=ssl_context)
                else:
                    self.reader, self.writer = await asyncio.open_connection(self.server, self.port)

                await self.send('CAP LS 302')

                await self.send(f'USER {self.nickname} 0 * :{self.nickname}')
                await self.send(f'NICK {self.nickname}')
                await self.identify_with_sasl()
                break
            except (ConnectionError, OSError) as e:
                print(e)
                await asyncio.sleep(5)  # Wait before retrying to connect

    async def identify_with_sasl(self):
        buffer = ""
        SASL_successful = False
        logged_in = False
        motd_received = False

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
                        await self.handle_sasl_auth(tokens)

                    case "900":
                        logged_in = True

                    case "903":
                        await self.send("CAP END")
                        print("SASL authentication successful.")
                        SASL_successful = True
                        if logged_in and SASL_successful and motd_received:
                            for channel in self.channels:
                                await self.join_channel(channel)
                            print("Joined channels")
                            return

                    case "904" | "905":
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
                        await self.send(f"PONG {tokens.params[0]}")

    async def join_channel(self, channel):
        await self.send(f"JOIN {channel}")
        await asyncio.sleep(0.3)

    async def handle_cap(self, tokens):
        print("Handling CAP")
        if "LS" in tokens.params:
            await self.send("CAP REQ :sasl")
        elif "ACK" in tokens.params:
            await self.send("AUTHENTICATE PLAIN")

    async def handle_sasl_auth(self, tokens):
        print("Sent SASL Auth")
        if tokens.params[0] == '+':
            auth_string = f"{self.sasl_username}\0{self.sasl_username}\0{self.nickserv_password}"
            encoded_auth = base64.b64encode(auth_string.encode("UTF-8")).decode("UTF-8")
            await self.send(f"AUTHENTICATE {encoded_auth}")

    async def sanitize_input(self, malicious_input):
        decoded_input = html.unescape(malicious_input)
        safe_output = ''.join(
            char for char in decoded_input
            if (ord(char) > 31 and ord(char) != 127) or char in '\x03\x02\x0F\x16\x1E\x1D\x1F\x01'
        )
        return safe_output

    async def send(self, message):
        safe_msg = await self.sanitize_input(message)
        self.writer.write((safe_msg + '\r\n').encode('utf-8'))
        await self.writer.drain()  # Ensure the message is sent
        return

    async def send_responses_worker(self):
        sent_responses = []  # List to track sent responses
        while True:
            channel, response = await self.response_queue.get()
            try:
                # Check if the response has already been sent
                if response not in sent_responses:
                    await self.send(f'PRIVMSG {channel} :{response}')
                    print(f"Sent: {response} to {channel}")
                    await asyncio.sleep(0.4)
                    # Add the response to the list of sent responses
                    sent_responses.append(response)
            finally:
                self.response_queue.task_done()

            # Check if the response queue is empty
            if self.response_queue.empty():
                # Reset the list of sent responses
                sent_responses = []

    async def handle_ctcp(self, tokens):
        hostmask = tokens.hostmask
        sender = tokens.hostmask.nickname
        target = tokens.params[0]
        message = tokens.params[1]

        if message.startswith('\x01') and message.endswith('\x01'):
            ctcp_command = message[1:-1].split(' ', 1)[0]
            ctcp_content = message[1:-1].split(' ', 1)[1] if ' ' in message else None

            match ctcp_command:
                case "VERSION" | "version":
                    response = f"NOTICE {sender} :\x01VERSION Clov3rbot v1.2\x01"
                    await self.send(response)
                    print(f"CTCP: {sender} {target}: {ctcp_command}")

                case "PING" | "ping":
                    response = f"NOTICE {sender} :\x01PING {ctcp_content}\x01"
                    await self.send(response)
                    print(f"CTCP: {sender} {target}: {ctcp_command}")

                case "ACTION":
                    print(f"Sender: {sender}")
                    print(f"Channel: {target}")
                    print(f"Content: {message}")
                    print(f"Full Hostmask: {hostmask}")
                    await self.save_message(sender, message, target)

                case _:
                    print(f"Unhandled CTCP command: {ctcp_command}")

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
                "content": f"* {sender} {action_content}"  # Format as an action message
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

        # Ensure only the latest 200 messages are kept
        while len(self.last_messages[channel]) > 200:
            self.last_messages[channel].pop(0)  # Remove the oldest message

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

    async def load_last_messages(self, filename="messages.json"):
        # Ensure the function is thread-safe if called concurrently
        async with self.lock:
            try:
                with open(filename, 'r') as file:
                    # Load messages from the file
                    self.last_messages = json.load(file)
                
                print(f"Loaded last messages from {filename}")
            except FileNotFoundError:
                print(f"{filename} not found. Starting with an empty message history.")
            except Exception as e:
                print(f"Error loading last messages: {e}")

    async def handle_messages(self):
        self.disconnect_requested = False
        buffer = ""

        try:
            while not self.disconnect_requested:
                data = await self.reader.read(1000)
                buffer += data.decode('UTF-8', errors='replace')

                if not data:
                    break

                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.rstrip('\r').strip().lstrip()

                    if not line:
                        continue

                    tokens = irctokens.tokenise(line)
                    print(line)

                    if tokens.command == "PING":
                        await self.send(f"PONG {tokens.params[0].strip().lstrip()}")
                    elif tokens.command == "PRIVMSG":
                        sender = tokens.source.split('!')[0].strip().lstrip() if tokens.source else "Unknown Sender"
                        hostmask = tokens.source.strip() if tokens.source else "Unknown Hostmask"
                        channel = tokens.params[0].strip().lstrip()
                        content = tokens.params[1].strip().lstrip()
                        parts = content.split()
                        normalized_content = ' '.join(parts)
                        url = self.url_regex.findall(normalized_content)

                        print(f"Sender: {sender}")
                        print(f"Channel: {channel}")
                        print(f"Content: {content}")
                        print(f"Full Hostmask: {hostmask}")
                        
                        await self.saw.record_last_seen(sender, channel, normalized_content)
                        await self.saw.save_last_seen()
                        await self.tatle_tell(sender, channel)
                        await self.handle_ctcp(tokens)
                        await self.save_message(sender, content, channel)
                        await self.save_last_messages()
                        for command in self.available_commands:
                            if content.startswith(command):
                                await self.user_commands(sender, channel, content, hostmask, self.last_messages, self.admin_list)
                                break  # Exit the loop after finding a match
                        for command in self.admin_commands:
                            if content.startswith(command):
                                if command == '.quit'and hostmask in self.admin_list:
                                    await self.send(f"Acknowledged {sender} quitting...")
                                    await self.send(f"QUIT :Cl4irBot")
                                    self.disconnect_requested = True
                                    break
                                else:
                                    await self.user_commands(sender, channel, content, hostmask, self.last_messages, self.admin_list, admin_command=True)
                                    break  # Exit the loop after finding a match
                        else:
                            # If no match is found, check if content starts with 's' or 'S'
                            if content.startswith(('s', 'S')) and len(content) > 2:
                                await self.user_commands(sender, channel, content, hostmask, self.last_messages, self.admin_list)
                            elif url:
                                await self.user_commands(sender, channel, content, hostmask, self.last_messages, self.admin_list)
        except Exception as e:
            print(e)
        except asyncio.CancelledError:
            print("handle_messages coroutine cancelled.")

    async def user_commands(self, sender, channel, content, hostmask, last_messages, admin_list, admin_command=False):
        try:
            if not content.strip():
                return
            if len(content) <= 1:
                print("Content is too short to send.")
                return

            data = (sender, channel, content, hostmask, last_messages, admin_list)

            # Clear the response track at the start of the method
            self.response_track.clear()

            async for response in self.send_command_to_parser(data):  # Await the coroutine here
                if response:
                    print(f"user_commands: {response}")
                    self.response_track.add(response)

            for response in self.response_track:
                if not admin_command:
                    await self.response_queue.put((channel, response))
                else:
                    await self.send(response)
        except Exception as e:
            print(e)

    async def send_command_to_parser(self, data):
        responses = []
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', 8888)
            try:
                encoded_data = json.dumps(data).encode('utf-8')
                writer.write(encoded_data)
                await writer.drain()

                while True:
                    response = await asyncio.wait_for(reader.read(2048), timeout=5)
                    print(f"send_command_to_parser: {response}")
                    if not response:
                        break  # Break the loop if no more responses
                    if response in responses:
                        pass
                    
                    decoded_response = response.decode()
                    print("Received response from server:", decoded_response)
                    responses.append(decoded_response)
            finally:
                writer.close()
                await writer.wait_closed()
            
            for response in responses:
                yield response

        except asyncio.TimeoutError:
            print("Timeout occurred while waiting for response from the server.")
        except Exception as e:
            print(f"Error in send_command_to_parser: {e}")

    async def tatle_tell(self, sender, channel):
        response = await self.speak.send_saved_messages(sender, channel)
        if response:
            await self.response_queue.put((channel, response))
            return

    async def keep_alive(self):
        while not self.disconnect_requested:
            async with self.lock:
                await self.send("PING :keepalive")
                print(f"Sent: PING to Server: {self.server}")
            await asyncio.sleep(195)

    async def clear_response(self):
        while True:
            async with self.lock:
                self.response_track.clear()
            await asyncio.sleep(30)

    async def disconnect(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None
            self.reader = None

    async def main_loop(self):
        try:
            while True:
                try:
                    await self.connect()
                    await self.load_last_messages()

                    keep_alive_task = asyncio.create_task(self.keep_alive())
                    handle_messages_task = asyncio.create_task(self.handle_messages())
                    clear_response_task = asyncio.create_task(self.clear_response())
                    response_handler = asyncio.create_task(self.send_responses_worker())

                    done, pending = await asyncio.wait(
                        [keep_alive_task, handle_messages_task, response_handler],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    for task in pending:
                        task.cancel()

                    await asyncio.gather(*pending, return_exceptions=True)

                except (ConnectionError, OSError) as e:
                    print(e)
                finally:
                    await self.disconnect()

        except KeyboardInterrupt:
            print("KeyboardInterrupt received. Shutting down...")
        except Exception as e:
            print(f"Unknown Exception: {e}")

    async def start(self):
        await self.main_loop()


if __name__ == "__main__":
    bot = Clov3r.from_config_file("bot_config.ini")
    asyncio.run(bot.start())

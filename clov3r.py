"""
TODO: prevent bot from answering to !help game, just !help commands. 
"""
import bleach
import html
import ipaddress
import socket
import ssl
import re
import random
import requests
import datetime
import sys
import time
import threading
import configparser
from datetime import datetime
from collections import defaultdict
from html import escape
from bs4 import BeautifulSoup

class IRCBot:
    def __init__(self, server, port, bot_name, nickserv_password, admin_list):
        self.server = server
        self.port = port
        self.bot_name = bot_name
        self.nickserv_password = nickserv_password
        self.admin_list = admin_list
        self.channels = []
        self.irc_socket = None
        self.banned_words = []
        self.whitelisted_words = []
        self.mushroom_facts = []
        self.user_warnings = {}
        self.channel_topics = {}
        self.last_messages = defaultdict(list)
        self.sed_enabled_channels = defaultdict(bool)
        self.user_messages = defaultdict(list)
        self.last_command = defaultdict(str)
        self.lock = threading.Lock()

    def is_admin(self, full_hostmask):
        return full_hostmask in self.admin_list

    def load_lists_from_file(self):
        try:
            self.load_user_warnings_from_file()
            with open("banned_words.txt", "r") as file:
                self.banned_words = [line.strip() for line in file.readlines()]

            with open("whitelisted_words.txt", "r") as file:
                self.whitelisted_words = [line.strip() for line in file.readlines()]

            with open("channels.txt", "r") as file:
                for line in file.readlines():
                    channel, sed_enabled = line.strip().split()
                    self.channels.append(channel)
                    self.sed_enabled_channels[channel] = bool(int(sed_enabled))

        except FileNotFoundError:
            print("List files not found.")

    def load_user_warnings_from_file(self):
        try:
            with open("user_warnings.txt", "r") as file:
                lines = file.readlines()
                for line in lines:
                    user, warnings = line.strip().split()
                    self.user_warnings[user] = int(warnings)
        except FileNotFoundError:
            print("User warnings file not found.")

    def save_user_warnings_to_file(self):
        with open("user_warnings.txt", "w") as file:
            for user, warnings in self.user_warnings.items():
                file.write(f"{user} {warnings}\n")

    def load_mushroom_facts(self):
        try:
            with open("mushroom_facts.txt", "r") as file:
                self.mushroom_facts = [line.strip() for line in file.readlines()]
        except FileNotFoundError:
            print("Mushroom facts file not found.")

    def send_random_mushroom_fact(self, channel):
        if self.mushroom_facts:
            random_fact = random.choice(self.mushroom_facts)
            self.send_message(f"PRIVMSG {channel} :{random_fact}\r\n")

            print(f"Sent mushroom fact to {channel}: {random_fact}")

    def reload_lists(self):
        self.banned_words.clear()
        self.whitelisted_words.clear()
        self.channels.clear()
        self.user_warnings.clear()
        self.user_messages.clear()
        self.mushroom_facts.clear()
        self.load_lists_from_file()
        self.load_mushroom_facts()

    def connect_to_irc(self):
        print(f"Connecting to {self.server}")
        context = ssl.create_default_context()
        self.irc_socket = context.wrap_socket(socket.socket(socket.AF_INET), server_hostname=self.server)
        self.irc_socket.connect((self.server, self.port))
        self.send_message("USER " + self.bot_name + " " + self.bot_name + " " + self.bot_name + " :I am a bot!\r\n")
        self.send_message("NICK " + self.bot_name + "\r\n")

    def identify_with_nickserv(self):
        motd_received = False
        while True:
            data = self.irc_socket.recv(2048).decode("UTF-8")
            print(data)

            if "376" in data:  # End of MOTD
                self.send_message(f'PRIVMSG NickServ :IDENTIFY {self.bot_name} {self.nickserv_password}\r\n')
                print("Sent NickServ authentication.")  # End of MOTD
                motd_received = True

            if motd_received and "396" in data:  # NickServ authentication successful
                for channel in self.channels:
                    self.send_message(f"JOIN " + channel + "\r\n")
                print("Joined channels after NickServ authentication.")
                break

    def send_message(self, message):
        if self.irc_socket:
            self.irc_socket.send(bytes(message, "UTF-8"))

    def respond_to_ping(self, data):
        if data.startswith("PING"):
            print(f"PING Detected")
            print(f"Sent PONG")
            self.send_message(f"PONG " + data.split()[1] + "\r\n")

    def keep_alive(self):
        while True:
            with self.lock:
                self.send_message(f'PING :keepalive\r\n')
                print(f"Sent: PING to Server: {self.server}")
            time.sleep(195)

    def is_swear(self, word):
        lower_word = word.lower()
        return (
                any(swear in lower_word for swear in self.banned_words) or
                any(swear in re.sub(r'[^a-zA-Z0-9]', '', lower_word) for swear in self.banned_words)
        ) and not any(whitelisted_word in lower_word for whitelisted_word in self.whitelisted_words)

    def save_last_messages(self, channel, sender, message):
        formatted_message = f"<{sender}> {message}"
        self.last_messages[channel].append(formatted_message)
        if len(self.last_messages[channel]) > 10:
            self.last_messages[channel] = self.last_messages[channel][-10:]

    def apply_sed_command(self, channel, sender, sed_command):
        if channel in self.last_messages and self.sed_enabled_channels[channel]:
            try:
                match = re.match(r"s/(.+)/(.+)", sed_command)
                if match:
                    pattern = match.group(1)
                    replacement = match.group(2)

                    updated_message = None
                    for message in reversed(self.last_messages[channel]):
                        try:
                            if re.search(pattern, message):
                                updated_message = re.sub(pattern, replacement, message)
                                break
                        except re.error as e:
                            print(f"Error in regex pattern: {e}")

                    if updated_message:
                        # Check if the updated message contains a swear word
                        if self.is_swear(updated_message):
                            response = f"[Sed] Message sent to /dev/null due to detected swearing"
                            privmsg_command = f"PRIVMSG {channel} :{response.replace('\r', '').replace('\n', ' ')}\r\n"
                            print("Updated message contains a swear word. Not posting.")
                            self.send_message(f'{privmsg_command}\r\n')
                        else:
                            response = f"[Sed] {updated_message}"
                            privmsg_command = f"PRIVMSG {channel} :{response.replace('\r', '').replace('\n', ' ')}\r\n"
                            self.send_message(f'{privmsg_command}\r\n')
            except re.error as e:
                print(f"Error in regex pattern: {e}")

    def is_raw_text_paste(self, url):
        # Patterns for raw text pastes
        raw_text_patterns = [
            "pastebin.com/raw/",
            "bpa.st/raw/",
            "@raw",
        ]
        return any(pattern in url for pattern in raw_text_patterns)

    def detect_and_handle_urls(self, message, channel):
        # Check if the message starts with '@' symbol and contains a list of URLs
        if message.startswith("@"):
            return
        # Check if the message contains a URL
        url_matches = re.findall(r'(https?://\S+)', message)
        for url in url_matches:
            # Filter out URLs with private IP addresses
            if self.filter_private_ip(url):
                print(f"Ignoring URL with private IP address: {url}")
                continue

            # Check if the URL is a raw text paste
            if self.is_raw_text_paste(url):
                paste_code = url.split("/")[-1]
                response = f"Raw paste: {paste_code}"
                self.send_message(f'PRIVMSG {channel} :{response}\r\n')
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
                webpage_title = self.sanitize_input(self.extract_webpage_title(url))

                # Check if the URL contains a swear word in the file name or webpage title
                if self.is_swear(file_name) or self.is_swear(webpage_title):
                    print(f"Ignoring URL with swear word in title: {url}")
                    continue

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
            self.send_message(f'PRIVMSG {channel} :[Website]: {response}\r\n')
            print(f"Sent: {response} to {channel}")

    def respond_to_message(self, data):
        if "PRIVMSG" in data:
            sender_match = re.match(r":([^!]+)!", data)
            if sender_match:
                sender = sender_match.group(1)
            else:
                print("Failed to extract sender information.")
                return

            # Extract the full hostmask
            full_hostmask_match = re.match(r":([^ ]+)", data)
            if full_hostmask_match:
                full_hostmask = full_hostmask_match.group(1)
            else:
                print("Failed to extract full hostmask.")
                return

            # Extract the message correctly
            message_match = re.match(r":[^ ]+ PRIVMSG ([^ ]+) :(.+)", data)
            if message_match:
                channel = message_match.group(1)
                message = message_match.group(2)

                # Strip leading white spaces
                message = message.lstrip()

                # Check for saved messages for the user
                if sender in self.user_messages:
                    saved_messages = self.user_messages[sender]
                    if saved_messages:
                        responses = [f"{sender}: <{saved_sender}> {saved_message} (at {timestamp})" for saved_sender, saved_message, timestamp in saved_messages]

                        # Send each saved message on its own line
                        for saved_sender, saved_message, timestamp in saved_messages:
                            response = f"{sender}: <{saved_sender}> {saved_message} (at {timestamp})"

                            # Remove \r and \n from the response
                            response = response.replace('\r', '').replace('\n', ' ')

                            time.sleep(0.4)
                            self.send_message(f'PRIVMSG {channel} :{response}\r\n')
                            print(f"Sent saved message for {sender} in {channel}: {response}")

                        # Remove all sent messages from the list
                        self.user_messages[sender].clear()

                # Check for sed commands
                if message.startswith("s/"):
                    self.apply_sed_command(channel, sender, message)

                # Check for swear words
                if self.is_swear(message):
                    # Check if the user already has a warning
                    if sender in self.user_warnings:
                        self.user_warnings[sender] += 1
                    else:
                        self.user_warnings[sender] = 1

                    # Issue a warning message
                    warning_message = f"{sender}! Please refrain from using swear words. Offense: {self.user_warnings[sender]}."
                    self.send_message(f'PRIVMSG {channel} :{warning_message}\r\n')
                    print(f"Sent: {warning_message} to {channel}")

                    # If the user reaches the maximum allowed warnings, kick and/or ban the user
                    if self.user_warnings[sender] >= 2:
                        # Extract the IP address from the full hostmask
                        ip_match = re.match(r".*@([^ ]+)", full_hostmask)
                        if ip_match:
                            ip_address = ip_match.group(1)

                            # Ban the user based on IP address for the current channel
                            # ban_command = f"MODE {channel} +b !*@*{ip_address}\r\n"
                            # self.send_message(f'PRIVMSG {ban_command}')
                            # print(f"Banned {full_hostmask} for using a swear word in {channel}.")

                            # Kick the user from the current channel
                            kick_command = f"KICK {channel} {sender} :You have been kicked for using a swear word.\r\n"
                            self.send_message(f'{kick_command}')
                            print(f"Kicked {full_hostmask} from {channel}.")

                            # Reset the user's warning count after kicking/banning
                            del self.user_warnings[sender]

                # Print debug information
                print(f"Sender: {sender}")
                print(f"Full Hostmask: {full_hostmask}")
                print(f"Channel: {channel}")
                print(f"Message: {message}")

                # Handle user commands
                if message.startswith("!!"):
                    # Repeat the last user command
                    if self.last_command[channel]:
                        last_command = self.last_command[channel]
                        self.handle_user_command(sender, last_command, full_hostmask, channel)
                    else:
                        response = f"{sender}, no previous command found."
                        self.send_message(f'PRIVMSG {channel} :{response}\r\n')
                        print(f"Sent: {response} to {channel}")
                else:
                    self.handle_user_command(sender, message, full_hostmask, channel)
                    self.handle_admin_commands(sender, message, full_hostmask, channel)

                # Detect and handle URLs in the message
                self.detect_and_handle_urls(message, channel)

                # Save the last 10 messages for the channel
                self.save_last_messages(channel, sender, message)

                # Save the last command for the channel
                self.last_command[channel] = message

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

        return False  # URL does not contain a private IP address

    def extract_webpage_title(self, url):
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

    def sanitize_input(self, malicious_input):
        # Decode HTML entities
        decoded_input = html.unescape(malicious_input)

        # Filter out specific characters like 0x0a (newline) and 0x0d (carriage return) fuckin chud.
        safe_output = ''.join(char for char in decoded_input if 32 <= ord(char) <= 126)

        # Remove extra characters
        title_match = re.search(r'<title>(.+?)</title>', safe_output)
        if title_match:
            safe_output = title_match.group(1)

        return safe_output

    def dice_roll(self, args, channel, sender):
        print("Dice roll requested...")

        # Default to 1d20 if no arguments are provided
        if not args:
            args = "1d20"

        # Use regular expression to parse the input
        match = re.match(r'(\d*)[dD](\d+)([+\-]\d+)?', args)
        if not match:
            available_dice = ', '.join(dice_map.keys())
            response = f"{sender}, Invalid roll format: {args}. Available dice types: {available_dice}.\r\n"
            self.send_message(f'PRIVMSG {channel} :{response}\r\n')
            return

        # Extract the number of dice, the type of each die, and the modifier
        num_dice = int(match.group(1)) if match.group(1) else 1
        die_type = f"d{match.group(2)}"
        modifier = int(match.group(3)) if match.group(3) else 0

        # Set a reasonable limit on the number of dice rolls (e.g., 1000)
        max_allowed_rolls = 10
        if num_dice > max_allowed_rolls:
            response = f"{sender}, Please request a more reasonable number of rolls (up to {max_allowed_rolls}).\r\n"
            self.send_message(f'PRIVMSG {channel} :{response}\r\n')
            return

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

        # Check if the die_type is in the predefined dice_map
        if die_type in dice_map:
            max_value = dice_map[die_type]
        else:
            available_dice = ', '.join(dice_map.keys())
            response = f"{sender}, Invalid die type: {die_type}. Available dice types: {available_dice}.\r\n"
            self.send_message(f'PRIVMSG {channel} :{response}\r\n')
            return

        # Roll the dice the specified number of times, but limit to max_allowed_rolls
        rolls = [random.randint(1, max_value) for _ in range(min(num_dice, max_allowed_rolls))]

        # Apply the modifier
        total = sum(rolls) + modifier

        # Format the action message with both individual rolls and total
        individual_rolls = ', '.join(map(str, rolls))
        action_message = f"{sender} has rolled {num_dice} {die_type}'s modifier of {modifier}: {individual_rolls}. Total: {total}"

        print(f'Sending message: {action_message}')
        self.send_message(f'PRIVMSG {channel} :{action_message}\r\n')

    def handle_admin_commands(self, sender, message, full_hostmask, channel):
        # Check if the sender is an admin
        command_match = re.match(r"!(\S+)", message)
        if not command_match:
            return

        if not self.is_admin(full_hostmask):
            return

        command = command_match.group(1)

        # Process admin commands using match statement
        match command:
            case "quit":
                self.handle_quit_command(channel)

            case "join":
                self.handle_join_command(message)

            case "part":
                self.handle_part_command(sender, message, channel)

            case "reload":
                self.handle_reload_command(sender, channel)

            case "op":
                self.handle_op_command(sender, message, channel)

            case "deop":
                self.handle_deop_command(sender, message, channel)

    def handle_deop_command(self, sender, message, channel):
        if (deop_match := re.match(r"!deop(?: (\S+))?", message)):
            target_user = deop_match.group(1) or sender
            deop_command = f"MODE {channel} -o {target_user}\r\n"
            self.send_message(deop_command)
            print(f"Revoked operator status from {target_user} in {channel}")

    def handle_op_command(self, sender, message, channel):
        if (op_match := re.match(r"!op(?: (\S+))?", message)):
            target_user = op_match.group(1) or sender
            op_command = f"MODE {channel} +o {target_user}\r\n"
            self.send_message(op_command)
            print(f"Granted operator status to {target_user} in {channel}")

    def handle_reload_command(self, sender, channel):
        self.reload_lists()
        response = f"{sender}: Acknowledged... Reloaded"
        self.send_message(f'PRIVMSG {channel} :{response}\r\n')
        print(f"Sent: {response} to {channel}")

    def handle_part_command(self, sender, message, channel):
        if (part_match := re.match(r"!part (.+)", message)):
            target_channel = part_match.group(1)
            response = f"Acknowledged {sender}, leaving {target_channel}"
            self.send_message(f'PRIVMSG {channel} :{response}\r\n')

            # Check if the target channel is in the list before removing
            if target_channel in self.channels:
                part_command = f"PART {target_channel}\r\n"
                self.send_message(f'{part_command}\r\n')
                self.channels.remove(target_channel)  # Remove the channel from the list
                print(f"Left channel: {target_channel}")
            else:
                part_command = f"PART {target_channel}\r\n"
                self.send_message(f'{part_command}\r\n')
                print(f"Channel {target_channel} not found in the list.")
        else:
            response = f"{sender}, usage: !part <channel>"
            self.send_message(f'PRIVMSG {channel} :{response}\r\n')

    def handle_quit_command(self, channel):
        response = "Acknowledged, quitting..."
        self.send_message(f'PRIVMSG {channel} :{response}\r\n')
        self.send_message(f"QUIT : I'm out\r\n")
        print("Quitting...")
        self.save_user_warnings_to_file()  # Save offenders on exit
        time.sleep(1)
        self.irc_socket.close()
        sys.exit()

    def handle_join_command(self, message):
        if (join_match := re.match(r"!join (.+)", message)):
            new_channel = join_match.group(1)
            join_command = f"JOIN {new_channel}\r\n"
            self.send_message(f'{join_command}\r\n')
            self.channels.append(new_channel)  # Add the new channel to the list
            print(f"Joined channel: {new_channel}")

    def handle_user_command(self, sender, message, full_hostmask, channel):
        # Extract the command from the message
        command_match = re.match(r"!(\S+)", message)
        if not command_match:
            # No valid command found, ignore the message
            return

        command = command_match.group(1)

        with self.lock:
            # Use the lock to create a critical section
            match command:
                case "hi":
                    self.handle_hi_command(sender, channel)

                case "factoid":
                    self.send_random_mushroom_fact(channel)

                case "tell":
                    self.handle_tell_command(sender, message, channel)

                case "info":
                    self.handle_info_command(sender, channel)

                case "topic":
                    self.handle_topic_command(sender, channel)

                case "dab":
                    response = f"{sender}: Yayy superwax! Enjoy :3"
                    self.send_message(f'PRIVMSG {channel} :{response}\r\n')

                case "help":
                    self.send_help_message(message, channel, full_hostmask)

                case "moo":
                    response = "Hi cow!"
                    self.send_message(f'PRIVMSG {channel} :{response}\r\n')

                case "moof":
                    self.send_dog_cow_message(channel)

                case "roll":
                    self.dice_roll(re.match(r"!roll(?: (.+))?", message).group(1), channel, sender)

                case "cast":
                    self.handle_spell_cast(sender, message, channel, full_hostmask)

                case _:
                    # Default case, handle unknown command
                    self.send_help_message(message, channel, full_hostmask)

    def handle_spell_cast(self, sender, message, channel, full_hostmask):
        if not message:
            # If no message is provided, send a help message
            self.send_help_message("!cast", channel, full_hostmask)
            return

        # Extract the spell_name and target_person from the message
        match = re.match(r"!cast (\S+)\s+(\S+)", message)
        if not match:
            # Invalid command format, send a help message
            self.send_help_message("!cast", channel, full_hostmask)
        else:
            spell_name = match.group(1)
            target_person = match.group(2)  # Use group(2) for the target_person
            total_damage = self.calculate_spell_damage(spell_name)
            response = f"{sender} has cast {spell_name} on target {target_person} for {total_damage} damage!"
            self.send_message(f'PRIVMSG {channel} :{response}\r\n')

    def calculate_spell_damage(self, spell_name):
        spell_damage = {
            "fireball": sum(random.randint(1, 6) for _ in range(8)), # Fireball
            "magicmissile": random.randint(1, 4), # Magic Missile
            "lightningbolt": sum(random.randint(1, 8) for _ in range(5)),  # Lightning Bolt
            "icestorm": sum(random.randint(1, 6) for _ in range(10))  # Ice Storm
            # Add more spells and their damage calculations
        }
        return spell_damage.get(spell_name, 0)

    def send_help_message(self, message, channel, full_hostmask):
        # Check if the message is exactly !help without additional characters
        if message.strip() == "!help":
            available_commands = [
                "!hi: I will say hi",
                "!tell <user> <message>: saves a message for a user",
                "!info: for info",
                "!topic: shows topic",
                "!dab: :3",
                "!help: HELP",
                "!moo: Hi cow!",
                "!moof: Shows Claris the dog cow",
                "!roll d20: roll a dice, pick a type d1-9999",
                "!factoid: show a mushroom fact.",
                "!! to rerun last sent command",
                "!cast <spell> [fireball, magicmissile, lightningbolt, and icestorm]",
                "to use sed: s/wordtoreplace/replacement"
            ]

            user_nickname = full_hostmask.split('!')[0]

            for command_info in available_commands:
                time.sleep(0.3)
                # Send help notice to the channel
                self.send_message(f'NOTICE {user_nickname} :[{channel}] {command_info}\r\n')
                print(f"Sent NOTICE: {command_info} to {channel}")

    def send_dog_cow_message(self, channel):
        dog_cow = "https://i.imgur.com/NbH0AUG.png"
        response = "Hello Claris, dog or cow?"
        self.send_message(f'PRIVMSG {channel} :{response} {dog_cow}\r\n')

    def handle_info_command(self, sender, channel):
        response = f"Hiya! I'm Clov3r, a friendly IRC bot, {sender}! Please follow the rules: use !topic to see them. My protocols are in place to prevent the use of racial slurs and to maintain peace."
        self.send_message(f'PRIVMSG {channel} :{response}\r\n')
        print(f"Sent: {response} to {channel}")

    def handle_topic_command(self, sender, channel):
        # Check if the topic for the channel is already stored
        if channel in self.channel_topics:
            topic = self.channel_topics[channel]
            response = f"{sender}: {topic}"
        else:
            # Fetch the topic dynamically using the IRC TOPIC command
            self.send_message(f'TOPIC {channel}\r\n')
            data = self.irc_socket.recv(2048).decode("UTF-8")
            topic_match = re.match(r":[^ ]+ 332 [^ ]+ ([^ ]+) :(.+)", data)

            if topic_match:
                channel_name = topic_match.group(1)
                topic = topic_match.group(2)

                # Save the topic in the dictionary for future reference
                self.channel_topics[channel] = topic

                response = f"{sender}: {topic}"
            else:
                response = f"{sender}, unable to fetch the topic for {channel}"

        self.send_message(f'PRIVMSG {channel} :{response}\r\n')
        print(f"Sent: {response} to {channel}")

    def handle_hi_command(self, sender, channel):
        response = f"Hello, {sender}!"
        self.send_message(f'PRIVMSG {channel} :{response}\r\n')
        print(f"Sent: {response} to {channel}")

    def handle_tell_command(self, sender, message, channel):
        # Extract the target user and message from the command
        tell_match = re.match(r"!tell (\S+) (.+)", message)
        if tell_match:
            target_user = tell_match.group(1)
            tell_message = tell_match.group(2)

            # Check if the tell_message contains swears
            if self.is_swear(tell_message):
                self.send_message(f'PRIVMSG {channel} :Message contains a swear: Discarded.\r\n')
                return

            # Limit the number of saved messages to 5
            max_saved_messages = 5
            if target_user not in self.user_messages:
                self.user_messages[target_user] = []

            # Check if the limit has been reached
            if len(self.user_messages[target_user]) >= max_saved_messages:
                # Stop further processing for this command
                return

            # Save the new message with the current timestamp
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            self.user_messages[target_user].append((sender, tell_message, timestamp))

            response = f"{sender}, your message for {target_user} has been saved."
            self.send_message(f'PRIVMSG {channel} :{response}\r\n')
            print(f"Saved message for {target_user} from {sender} at {timestamp}")

def load_config(filename="config.ini"):
    config = configparser.ConfigParser()
    config.read(filename)
    return config["IRC"]

def main():
    # Load configuration from the INI file
    config = load_config()

    # Extract admin list from the configuration
    admin_list = config.get("admin_list", "").split(",")

    bot = IRCBot(
        config["server"],
        int(config["port"]),
        config["bot_name"],
        config["nickserv_password"],
        admin_list
    )

    bot.load_lists_from_file()
    bot.load_mushroom_facts()
    bot.connect_to_irc()
    bot.identify_with_nickserv()  # Identify with NickServ

    # The keep-alive thread
    keep_alive_thread = threading.Thread(target=bot.keep_alive, daemon=True)
    keep_alive_thread.start()

    while True:
        data = bot.irc_socket.recv(2048).decode("UTF-8", errors="replace")
        print(data)

        bot.respond_to_ping(data)
        bot.respond_to_message(data)

if __name__ == "__main__":
    main()

async def help_command(channel, sender, args=None, hostmask=None, admin_list=None):
    # Get the list of available commands
    exclude_admin = False if hostmask in admin_list else True
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
            return response

        else:
            response = f"{sender}, Unknown command: {specific_command}\r\n"
            return response
    else:
        # Provide an overview of available commands
        response = f"{sender}, Commands: {', '.join(available_commands)} Use: .help <command> for more info.\r\n"
        return response

    print(f"Sent: {response} to {channel}")

def get_available_commands(exclude_admin=True):
    # List all available commands (excluding admin commands by default)
    commands = [
        ".ping",
        ".fact",
        ".tell",
        ".seen",
        ".moo",
        ".moof",
        ".help",
        ".stats",
        ".version",
        ".sed",
        ".weather",
        ".bug",
        ".g",
        ".ddg",
        ".tr",
        ".yt",
        ".admin",
    ]
    if exclude_admin:
        commands.remove(".admin")
    return commands

def get_detailed_help(command):
    # Provide detailed help for specific commands
    help_dict = {
        ".ping": "Ping command: Check if the bot is responsive.",
        ".fact": "Fact command: Display a random mushroom fact. Use '.fact <criteria>' to filter facts.",
        ".tell": "Tell command: Save a message for a user. Use '.tell <user> <message>'.",
        ".seen": "Seen command: Check when a user was last seen. Use '.seen <user>'.",
        ".moo": "Moo command: Greet the cow.",
        ".moof": "Moof command: The dogcow, named Clarus, is a bitmapped image designed by Susan Kare for the demonstration of page layout in the classic Mac OS.",
        ".help": "Help command: Display a list of available commands. Use '.help <command>' for detailed help.",
        ".stats": "Stats command: Display statistics for a user. Use '.stats <user>'.",
        ".version": "Version command: Shows the version of Clov3r",
        ".sed": "Sed usage s/change_this/to_this/(g/i). Flags are optional. To include word boundaries use \\b Example: s/\\btest\\b/stuff. I can also take regex. https://tinyurl.com/sedinfo",
        ".weather": "Search weather forecast - example: .weather Ireland - Can search by address or other terms",
        ".bug": "Usage .bug <bug_id>, Gives bug information from bugs.gentoo.org API. Extra arguments: change & creation example: .bug <bug_id> <argument>",
        ".g": "Googles a string or term | .g <string>",
        ".ddg": "Searches DuckDuckGo for a given term",
        ".tr": "Translates a string, Example: .tr hello -ga will translate to Irish. Default translate is english",
        ".yt": "Searches YouTube for a video: .yt <search terms>",
        ".admin": ".factadd - .quit - .join - .part - .op - .deop",
    }

    return help_dict.get(command, f"No detailed help available for {command}.")
def get_available_commands(exclude_admin=True):
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
        ".bug",
        ".quote",
        ".endquote",
        ".admin",
    ]
    if exclude_admin:
        commands.remove(".admin")
    return commands

def get_detailed_help(command):
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
        ".bug": "Usage .bug <bug_id>, Gives bug information from bugs.gentoo.org API. Extra arguments: change & creation example: .bug <bug_id> <argument>",
        ".quote": "starts recording a quote, .quote <number> to call a quote by tag number",
        ".endquote": "ends quote recording and saves quote",
        ".admin": ".factadd - .quit - .join - .part - .op - .deop - .botop - .reload - .purge",
    }

    return help_dict.get(command, f"No detailed help available for {command}.")
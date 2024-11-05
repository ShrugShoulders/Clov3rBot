import re
import asyncio

async def handle_sed_command(channel, sender, content, last_messages):
    separator_list = ['/', '_', '-', '~', '.', '|', '@', '+', '!', '`', ';', ':', '>', '<', '=', ')', '(', '*', '&', '^', '%', '#', '?', '[', ']', '{', '}', '$', ',', "'", '"']
    try:
        # Escape all separators in the list
        separators = ''.join(map(re.escape, separator_list))

        # Regular expression to match the sed command
        match = re.match(
            fr'[sS]([{separators}])((?:\\.|[^\1])+?)\1((?:\\.|[^\1])*?)'  # Match 'sed' pattern and new content
            r'(?:\1([gi]*))?(?:\1(\d*))?(?:\1(.*))?$',                    # Optional flags, repeat count, and additional args
            content
        )
        #match = re.match(fr'[sS]([{separators}])(.*?)(\1)(.*?)(?:\1([gi]*))?(\1(\d*))?(?:\1(.*))?$', content)
    except re.error as e:
        response = f"[\x0304Sed\x03] Invalid sed command: {str(e)}\r\n"
        print(response)
        return

    character_limit = 460
    if not match:
        response = f"[\x0304Sed\x03] Not A Valid Sed Command\r\n"
        print(response)
        return

    try:
        # Extract groups from the match
        separator, old, new, flags, occurrence, target_nickname = match.groups()
        new = new if new is not None else ''  # Ensure new is an empty string if not provided
        flags = flags if flags else ''  # Ensure flags are set to an empty string if not provided

        # Handle special regex replacements for \d and \s
        old = old.replace(r'\d', r'[0-9]').replace(r'\s', r'\s')

        # Set up regex flags for case-insensitivity if needed
        regex_flags = re.IGNORECASE if 'i' in flags else 0
        count = 0 if 'g' in flags else 1  # Replace globally if 'g' is in flags

        print(f"Separator: {separator}, Old: {old}, New: '{new}', Flags: {flags}, Occurrence: {occurrence}")
    except re.error as e:
        response = f"[\x0304Sed\x03] Invalid sed command: {str(e)}\r\n"
        print(response)
        return

    if channel not in last_messages:
        response = f"[\x0304Sed\x03] No message history found for the channel\r\n"
        print(response)
        return

    corrected_message = None
    original_sender_corrected = None
    total_characters = 0

    try:
        for formatted_message in reversed(last_messages[channel]):
            original_message = formatted_message["content"]
            original_sender = formatted_message["sender"]

            # Skip messages not matching the target nickname if specified
            if target_nickname and original_sender != target_nickname:
                continue

            if re.match(fr'^[sS][{separators}].*[{separators}].*[{separators}]?[gi]*\d*$', original_message):
                continue

            print(f"Checking message - Original: <{original_sender}> {original_message}")

            # Search and replace using the specified regex
            if re.search(old, original_message, flags=regex_flags):
                if occurrence:
                    # Replace only the specified occurrence
                    def replace_nth(match):
                        nonlocal occurrence
                        occurrence = int(occurrence) - 1
                        return new if occurrence == 0 else match.group(0)

                    replaced_message = re.sub(old, replace_nth, original_message, flags=regex_flags)
                else:
                    replaced_message = re.sub(old, new.replace('&', r'\g<0>'), original_message, flags=regex_flags, count=count)

                total_characters += len(replaced_message)

                if replaced_message != original_message and total_characters <= character_limit:
                    corrected_message = replaced_message
                    original_sender_corrected = original_sender
                    print(f"Match found - Corrected: <{original_sender_corrected}> {corrected_message}")
                    break

        if corrected_message is not None and original_sender_corrected is not None:
            if corrected_message.startswith("*"):
                response = f"[\x0303Sed\x03] {corrected_message}\r\n"
            else:
                response = f"[\x0303Sed\x03] <{original_sender_corrected}> {corrected_message}\r\n"

            print(f"Sent: {response} to {channel}")
            return response
        else:
            response = f"[\x0304Sed\x03] No matching message found to correct from {target_nickname}\r\n"
            print(f"Sent: {response} to {channel}")
            return
    except re.error as e:
        response = f"[\x0304Sed\x03] Invalid sed command: {str(e)}\r\n"
        print(response)
        return
    except ValueError as e:
        response = f"[\x0304Sed\x03] Error in processing sed command: {str(e)}\r\n"
        print(response)
        return

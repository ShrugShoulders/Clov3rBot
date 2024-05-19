import re
import asyncio


async def handle_sed_command(channel, sender, content, last_messages):
    separator_list = ['/', '_', '-', '~', '.', '|', '@', '+', '!', '`', ';', ':', '>', '<', '=', ')', '(', '*', '&', '^', '%', '#', '?', '[', ']', '{', '}','$', ',', "'", '"', '/', '\'', '\"']
    try:
        # Escape all separators in the list
        separators = ''.join(map(re.escape, separator_list))

        # Replace escaped separators with placeholders
        content = re.sub(r'\\([' + re.escape(''.join(separator_list)) + '])', lambda m: f'\\{m.group(1)}', content)

        # Build the regular expression pattern
        match = re.match(fr'[sS]([{separators}])(.*?)(\1)(.*?)(?:\1([gi]*))?(\1(\d*))?(?:\1(.*))?$', content)

        character_limit = 460
        if match:
            # Extract groups from the match
            separator, old, _, new, flags, _, occurrence, target_nickname = match.groups()
            flags = flags if flags else ''  # Ensure flags are set to an empty string if not provided

            # Check for word boundaries flag
            word_boundaries = r'\b' if '\\b' in old else ''

            # If the old string contains \d, replace it with [0-9]
            old = old.replace(r'\\d', r'[0-9]')

            if old == " ":
                old = r'\s'

            # Update the regular expression with word boundaries
            regex_pattern = fr'{word_boundaries}{old}{word_boundaries}'

            # Print the separator
            print(f"Separator: {separator}")

        else:
            print("Not A Valid Sed Command")
            return

        # Check if the channel key exists in self.last_messages
        if channel in last_messages:
            corrected_message = None
            original_sender_corrected = None
            total_characters = 0
            regex_flags = re.IGNORECASE if 'i' in flags else 0
            for formatted_message in reversed(last_messages[channel]):
                original_message = formatted_message["content"]
                original_sender = formatted_message["sender"]

                # Skip messages not matching the target nickname if specified
                if target_nickname and original_sender != target_nickname:
                    continue

                if re.match(fr'^[sS][{separators}].*[{separators}].*[{separators}]?[gi]*\d*$', original_message):
                    continue

                if old in ["*", "$", "^"]:
                    if original_message.startswith("*"):
                        return f"[\x0303Sed\x03] {original_message}\r\n"
                    else:
                        return f"[\x0303Sed\x03] <{original_sender}> {original_message}\r\n"

                print(f"Checking message - Original: <{original_sender}> {original_message}")

                if re.search(regex_pattern, original_message, flags=regex_flags):
                    if occurrence:
                        # Function to replace only the specified occurrence
                        def replace_nth(match):
                            nonlocal occurrence
                            occurrence = int(occurrence) - 1  # Convert occurrence to integer before subtraction
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
                    response = f"[\x0303Sed\x03] {corrected_message}\r\n"
                else:
                    response = f"[\x0303Sed\x03] <{original_sender_corrected}> {corrected_message}\r\n"

                return response
                print(f"Sent: {response} to {channel}")
            else:
                response = f"[\x0304Sed\x03] No matching message found to correct from {target_nickname}\r\n"
                return response
                print(f"Sent: {response} to {channel}")

        else:
            response = f"[\x0304Sed\x03] No message history found for the channel\r\n"
            return response
            print(f"Sent: {response} to {channel}")

    except re.error as e:
        response = f"[\x0304Sed\x03] Invalid sed command: {str(e)}\r\n"
        return response
        print(f"Sent: {response} to {channel}")
    except ValueError:
        response = f"[\x0304Sed\x03] Invalid sed command format\r\n"
        return response
        print(f"Sent: {response} to {channel}")
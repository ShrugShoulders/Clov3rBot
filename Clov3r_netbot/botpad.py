import json
from datetime import datetime, timedelta



class BotPad:
    def __init__(self):
        self.paper = {}
        self.load_from_file()
        self.reminded_users = []
        self.short_term_remind = []
        self.remind_timer = datetime.now()
        self.short_remind_timer = datetime.now()

    def add_note(self, channel, user, note):
        # Split the note to get args
        args = note.split()
        
        # Check if the first argument is a number (time delta in hours)
        time_delta_hours = 12
        if args and args[0].isdigit():
            time_delta_hours = int(args[0])
            note = ' '.join(args[1:])  # Remove the time delta from the note

        luser = user.lower()
        if channel not in self.paper:
            self.paper[channel] = {}

        if luser not in self.paper[channel]:
            self.paper[channel][luser] = []

        # Check for duplicate note by comparing the note content for the user in the channel
        for entry in self.paper[channel][luser]:
            if entry["note"] == note:
                return f"Duplicate note detected for {user} in {channel}: '{note}'"

        # Add the note with a timestamp and optional time delta
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.paper[channel][luser].append({
            "note": note,
            "timestamp": timestamp,
            "time_delta_hours": time_delta_hours  # Store the time delta if it exists
        })
        self.save_to_file()
        print(self.paper)
        return f"Note Added"

    def reset_reminded_users_if_needed(self):
        # Check if 24 hours have passed since the last reset
        if datetime.now() - self.remind_timer > timedelta(hours=24):
            self.reminded_users.clear()
            self.remind_timer = datetime.now()

    def reset_reminded_users_if_needed_6hr(self, user, stored_delta):
        try:
            # Check if the stored time delta has passed since the last short-term reminder
            if datetime.now() - self.short_remind_timer > timedelta(hours=stored_delta):
                
                # Remove user from short-term remind list
                if user in self.short_term_remind:
                    self.short_term_remind.remove(user)
                else:
                    print(f"User '{user}' not found in short_term_remind list")

                # Update the short reminder timer to the current time
                self.short_remind_timer = datetime.now()
            else:
                print(f"Time delta not yet exceeded for user '{user}'")
        
        except Exception as e:
            print(f"Exception in reset_reminded_users_if_needed_6hr: {e}")

    def check_time_deltas(self, user, channel):
        try:
            self.reset_reminded_users_if_needed()  # Check if users have been reminded every day.

            luser = user.lower()

            if channel in self.paper:
                if luser in self.paper[channel]:
                    current_time = datetime.utcnow()

                    for entry in self.paper[channel][luser]:
                        note_time = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S")
                        stored_delta = int(entry["time_delta_hours"])
                        time_delta = current_time - note_time
                        self.reset_reminded_users_if_needed_6hr(luser, stored_delta)

                        if luser not in self.short_term_remind:
                            self.paper = {}
                            self.load_from_file()
                            # If user has already been reminded, use a 6-hour threshold
                            threshold = timedelta(hours=stored_delta)

                            if time_delta > threshold:

                                if luser not in self.short_term_remind:
                                    self.short_term_remind.append(luser)

                                yield f"Reminder ({stored_delta}-hour rule): '{entry['note']}' | Timestamp: {entry['timestamp']} | Time Delta: {stored_delta} vs {time_delta}"

                        elif luser not in self.reminded_users:
                            # If user has not been reminded
                            threshold = timedelta(hours=stored_delta)
                            self.paper = {}
                            self.load_from_file()

                            if time_delta > threshold:
                                if luser not in self.reminded_users:
                                    self.reminded_users.append(luser)
                                yield f"Note: '{entry['note']}' | Timestamp: {entry['timestamp']} | Time Delta: {stored_delta} vs {time_delta}"
                else:
                    print(f"User '{luser}' not found in paper for channel '{channel}'")
            else:
                print(f"Channel '{channel}' not found in paper")

        except Exception as e:
            print(f"Exception occurred: {e}")

    def get_notes(self, channel, user, note):
        luser = user.lower()
        entry_index = 0
        # Retrieve the notes for a user in a specific channel, and yield each note one by one
        if channel in self.paper and luser in self.paper[channel]:
            for entry in self.paper[channel][luser]:
                response = f"Index:{entry_index} [{entry['timestamp']}]: {entry['note']}"
                entry_index += 1
                yield response
        else:
            yield "No User Found"

    def save_to_file(self, filename='notes.json'):
        # Save self.paper
        try:
            with open(filename, 'w') as f:
                json.dump(self.paper, f, indent=4)
            print(f"Data successfully saved to {filename}")
        except Exception as e:
            print(f"Error saving data: {e}")

    def load_from_file(self, filename='notes.json'):
        # Load self.paper
        try:
            with open(filename, 'r') as f:
                self.paper = json.load(f)
            print(f"Data successfully loaded from {filename}")
        except FileNotFoundError:
            print(f"File {filename} not found. Starting with an empty paper.")
        except Exception as e:
            print(f"Error loading data: {e}")

    def clear_user_notes(self, channel, user, index=None):
        luser = user.lower()
        
        if channel in self.paper and luser in self.paper[channel]:
            if index is None or index.strip() == '':
                return "Please provide a valid index number"
            else:
                try:
                    iindex = int(index)
                except ValueError:
                    return "Please provide a valid index number"
                
                # Remove specific note by index
                notes = self.paper[channel][luser]
                if 0 <= iindex < len(notes):
                    removed_note = notes.pop(iindex)
                    # If user has no more notes, remove the user entry
                    if not notes:
                        del self.paper[channel][luser]
                        # Remove the channel entry if it's empty
                        if not self.paper[channel]:
                            del self.paper[channel]
                    self.save_to_file()
                    print(self.paper)
                    return f"Note removed for {user}: '{removed_note['note']}'"
                else:
                    return "No note at the given index"
        else:
            return f"No notes found for {user}"

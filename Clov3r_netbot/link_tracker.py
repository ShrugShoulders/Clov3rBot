from datetime import datetime, timedelta
import json

class TitleTracker:
    def __init__(self):
        self.last_time = datetime.now()
        self.handled_links = {}
        self.load_from_json()

    def reset_url_list(self, channel):
        since_reset = self.time_since_reset()  # Added 'self' for method call
        if since_reset > timedelta(minutes=10):
            self.handled_links[channel] = []
            self.last_time = datetime.now()
            self.save_to_json()
            return True
        return False

    def time_since_reset(self):
        return datetime.now() - self.last_time

    def add_channel(self, channel):
        # Initialize the list of handled links for the channel if it doesn't exist
        if channel not in self.handled_links:
            self.handled_links[channel] = []

    def add_link(self, url, channel):
        # Add the URL to the list for this channel
        if url not in self.handled_links[channel]:
            self.handled_links[channel].append(url)
            self.save_to_json()

    # Save the handled links dictionary to a JSON file
    def save_to_json(self):
        with open('handled_links.json', 'w') as f:
            json.dump(self.handled_links, f, indent=4)

    # Load the handled links dictionary from a JSON file
    def load_from_json(self):
        try:
            with open('handled_links.json', 'r') as f:
                self.handled_links = json.load(f)
        except FileNotFoundError:
            # File doesn't exist, initialize as empty
            self.handled_links = {}
            self.save_to_json()
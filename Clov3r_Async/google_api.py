import requests
import json
import os

class Googlesearch:
    def __init__(self, count_file='search_count.txt'):
        self.api_key = "" # This is the API key needed, usually provided by Google.
        self.bot_id = "" # This is the search engine ID from your google console
        self.count_file = count_file
        self.safe_search = "active"
        self.search_count = self.load_search_count()

    def load_search_count(self):
        """Load the search count from a file."""
        try:
            with open(self.count_file, 'r') as file:
                return int(file.read())
        except FileNotFoundError:
            return 0
        except ValueError:
            return 0

    def save_search_count(self):
        """Save the search count to a file."""
        with open(self.count_file, 'w') as file:
            file.write(str(self.search_count))

    def google_it(self, query):
        if self.search_count >= 500:
            print("Search limit reached.")
            return

        script_directory = os.path.dirname(os.path.abspath(__file__))
        google_cache = os.path.join(script_directory, "google_cache")

        try:
            os.makedirs(google_cache, exist_ok=True)
        except Exception as e:
            print(f"Error creating cache directory: {e}")
            return

        # Sanitize the query to create a valid filename
        filename = "".join([c for c in query if c.isalpha() or c.isdigit() or c==' ']).rstrip()
        path = os.path.join(google_cache, f"{filename}.json")

        try:
            if os.path.exists(path):
                print(f"Loading cached data for '{query}'")
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                response = requests.get(f"https://www.googleapis.com/customsearch/v1?key={self.api_key}&cx={self.bot_id}&q={query}&safe={self.safe_search}")
                if response.status_code == 200:
                    self.search_count += 1
                    self.save_search_count()
                    data = response.json()

                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    print(f"Data saved to {path}")

                else:
                    print("Failed to retrieve search.")
                    return
        except requests.RequestException as e:
            print(f"Network error during search: {e}")
            return
        except json.JSONDecodeError as e:
            print(f"Error decoding search result: {e}")
            return
        except Exception as e:
            print(f"Unexpected error: {e}")
            return

        try:
            if "items" in data and len(data["items"]) > 0:
                search = data["items"][0]
                title = search.get('title', 'No Title Found')
                link = search.get('link', 'No URL Found')
                snippet = search.get('snippet', 'No description available.')
                search_details = f"{title} ({link}) {snippet}"
                return search_details
            else:
                print("No Data Returned")
                return
        except KeyError as e:
            print(f"Missing expected data key: {e}")
        except Exception as e:
            print(f"Error processing search data: {e}")
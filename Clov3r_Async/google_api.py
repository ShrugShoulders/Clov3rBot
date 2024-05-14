import requests
import json
import os
import hashlib
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta

class Googlesearch:
    def __init__(self, count_file='search_count.txt'):
        self.api_key = "" # This is the API key needed, usually provided by Google.
        self.youtube_api_key = ""
        self.bot_id = "" # This is the search engine ID from your google console
        self.count_file = count_file
        self.safe_search = "active"
        self.search_count = self.load_search_count()
        self.youtube_service = build('youtube', 'v3', developerKey=self.youtube_api_key)

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

        cache_is_fresh = False
        if os.path.exists(path):
            # Check modification time of the cache file
            file_mod_time = datetime.fromtimestamp(os.path.getmtime(path))
            if datetime.now() - file_mod_time < timedelta(hours=48):
                cache_is_fresh = True

        if cache_is_fresh:
            print(f"Loading cached data for '{query}'")
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            print("Fetching new data...")
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


    def process_youtube_search(self, args):
        try:
            search_data = self.youtube_search(args)
            return self.format_yt_data(search_data)
        except Exception as e:
            print(f"Error processing search: {e}")

    def youtube_search(self, query, max_results=1):
        try:
            script_directory = os.path.dirname(os.path.abspath(__file__))
            youtube_search_cache = os.path.join(script_directory, "youtube_search_cache")
            if not os.path.exists(youtube_search_cache):
                os.makedirs(youtube_search_cache)
                print("Created Youtube Search Cache")

            # Hash the query to create a unique filename
            filename = hashlib.md5(query.encode('utf-8')).hexdigest()
            file_path = os.path.join(youtube_search_cache, f"{filename}.json")

            if os.path.exists(file_path):
                print(f"Cached Data Exists")
                # Check modification time of the cache file
                file_mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                if datetime.now() - file_mod_time < timedelta(hours=72):
                    print("Responding with cached data")
                    # Cache is fresh, load and return the cached response
                    with open(file_path, 'r') as file:
                        cached_data = json.load(file)
                        return cached_data

            # If no cache or cache is stale, make a new request
            print("Making new request")
            search_response = self.youtube_service.search().list(
                q=query,
                part='snippet',
                maxResults=max_results,
                type='video'
            ).execute()

            # Update cache with the new result
            with open(file_path, 'w') as file:
                print("Saving Data")
                json.dump(search_response, file, indent=2)
            return search_response

        except HttpError as e:
            print(f"HTTP Error: {e}")
            return

    def format_yt_data(self, search_data):
        # Validate that 'items' is present and not empty
        if not search_data.get('items'):
            print('No results found or incorrect data format')
            return

        # Validate the structure of the first item
        first_result = search_data['items'][0]
        required_keys = ['snippet', 'id']
        if not all(key in first_result for key in required_keys):
            print('Missing required data in search result')
            return

        snippet = first_result['snippet']
        video_id = first_result['id'].get('videoId')
        if not all(key in snippet for key in ['title', 'description', 'channelTitle']) or not video_id:
            print('Incomplete video information')
            return

        # Prepare the response
        title = snippet['title']
        description = snippet['description'][:150]
        channel_title = snippet['channelTitle']
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        # The bot response
        response = f"[\x0301,00\x02You\x0300,04\x02Tube\x03]\x0F {title} | {channel_title} | {description}... | {video_url}"
        return response
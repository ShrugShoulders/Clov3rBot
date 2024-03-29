import asyncio
import aiohttp
import socket
import re
import requests
import ipaddress
import html
import http.client
import datetime
import io
import os
import magic
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from html import escape, unescape
from requests.exceptions import HTTPError, Timeout, RequestException
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from PIL import Image

class Titlescraper:
    def __init__(self):
        self.headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0', 'Accept-Encoding': 'identity'}
        self.api_key = ""
        self.youtube_service = build('youtube', 'v3', developerKey=self.api_key)

    async def sanitize_input(self, malicious_input):
        decoded_input = html.unescape(malicious_input)
        # Allow Unicode characters through by checking if the character is not a control character,
        # except for the whitelisted control codes ('\x03', '\x02', '\x0F', '\x16', '\x1D', '\x1F', '\x01').
        # This version considers characters outside the basic ASCII control characters as allowed,
        # including extended Unicode characters.
        safe_output = ''.join(
            char for char in decoded_input
            if (ord(char) > 31 and ord(char) != 127) or char in '\x16\x03\x02\x0F\x16\x1E\x1D\x1F\x01'
        )
        return safe_output

    def filter_private_ip(self, url):
        # Extract the hostname from the URL
        hostname = re.findall(r'https?://([^/:]+)', url)
        if hostname:
            hostname = hostname[0]
            try:
                ip = ipaddress.ip_address(hostname)
                return ip.is_private  # Return True for private IP addresses
            except ValueError:
                pass  # Not an IP address

        return False

    async def extract_webpage_title(self, url, redirect_limit=25):
        REQUEST_TIMEOUT = 10
        parsed_url = urlparse(url)
        connection = http.client.HTTPConnection(parsed_url.netloc, timeout=REQUEST_TIMEOUT) if parsed_url.scheme == 'http' else http.client.HTTPSConnection(parsed_url.netloc, timeout=REQUEST_TIMEOUT)
        EXECUTABLE_FILE_EXTENSIONS = ['.exe', '.dll', '.bat', '.jar', '.iso']

        # Define headers with User-Agent
        headers = self.headers

        try:
            # Include the headers in the request
            connection.request("GET", parsed_url.path or '/', headers=headers)
            response = connection.getresponse()

            # Follow redirects if status code is 301 or 302, up to a limit
            num_redirects = 0
            while response.status in [301, 302, 303] and num_redirects < redirect_limit:
                num_redirects += 1
                new_location = response.getheader('Location')
                if not new_location:
                    return "Error: No location for redirect"
                parsed_url = urlparse(new_location)
                connection = http.client.HTTPConnection(parsed_url.netloc) if parsed_url.scheme == 'http' else http.client.HTTPSConnection(parsed_url.netloc)
                # Include the headers again for the new request after redirect
                connection.request("GET", parsed_url.path or '/', headers=headers)
                response = connection.getresponse()

            if response.status in [400, 404, 401, 405, 403]:
                print(f"GET request failed with {response.status}")
                e = f"{response.status}"
                self.save_no_title(url, e)
                return
            elif response.status == 200:
                content_bytes = response.read(2048)
                content_type = magic.from_buffer(content_bytes, mime=True)
                print(f"{content_type}")
                
                if content_type in ['application/octet-stream', 'application/zip']:
                    if url.endswith(('.mp3', '.flac', '.wav', '.aac', '.ogg', '.wma', '.mha', '.mhm', '.aiff', '.alac', '.opus', '.spx', '.amr', '.ac3', '.dsf', '.dff', '.ape')):
                        return await self.handle_audio_file(url)

                #content_type = response.getheader('Content-Type', '').lower()
                charset = 'utf-8'
                if 'charset' in content_type.lower():
                    charset = charset = content_type.split('charset=')[-1].split(';')[0]
                content_length = int(response.getheader('Content-Length', 0))
                MAX_FILE_SIZE = 256 * 1024 * 1024  # 256 MB

                if content_type.startswith('image/'):
                    return await self.handle_image_url(url)
                elif content_type.startswith('video/'):
                    return await self.handle_video_file(url)
                elif content_type.startswith('text/plain'):
                    return await self.handle_text_file(url)
                elif content_type.startswith('audio/'):
                    return await self.handle_audio_file(url)
                elif content_type == 'application/pdf':
                    return await self.handle_pdf_file(url)
                elif content_type == 'application/octet-stream':
                    return await self.handle_gzip(url)
                elif content_type == 'application/x-iso9660-image':
                    return "ISO"
                elif content_type.startswith('text/html'):
                    remaining_content_bytes = response.read()
                    full_content = content_bytes + remaining_content_bytes
                    
                    decoded_content = full_content.decode('utf-8', errors='ignore')
                    soup = BeautifulSoup(decoded_content, 'html.parser')

                    title_tag = soup.find('title')
                    title = title_tag.text if title_tag else None

                    if title:
                        print(f"Extracted title tag: {title}")
                        return f"[\x0303Website\x03] {title}"
                    else:
                        meta_name_title_tag = soup.find('meta', {'name': 'title'})
                        meta_name_title = meta_name_title_tag['content'] if meta_name_title_tag else None

                        if meta_name_title:
                            print(f"Extracted meta name=title: {meta_name_title}")
                            return f"[\x0303Website\x03] {meta_name_title}"
                        else:
                            og_title_tag = soup.find('meta', attrs={'property': 'og:title'})
                            og_title = og_title_tag['content'] if og_title_tag else None

                            if og_title:
                                print(f"Extracted og:title: {og_title}")
                                return f"[\x0303Website\x03] {og_title}"
                            else:
                                print(f"Title not found")
                                e = f"extract_webpage_title could not find title for {url}"
                                self.handle_title_not_found(url, e)

                elif content_length > MAX_FILE_SIZE:
                    print(f"Max Size")
                    return 
                elif any(url.lower().endswith(ext) for ext in EXECUTABLE_FILE_EXTENSIONS):
                    print(f"Banned File Type")
                    return 
                else:
                    return
            else:
                return
        except socket.timeout:
            print(f"Request timed out for {url}")
            # Handle the timeout appropriately, maybe by logging or notifying the user
        except http.client.HTTPException as e:
            print(f"Error retrieving webpage title for {url}: {e}")
            # Handle other HTTP exceptions as before
        finally:
            connection.close()

    def format_file_size(self, size_in_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_in_bytes < 1024.0:
                return f"{size_in_bytes:.2f} {unit}"
            size_in_bytes /= 1024.0

        return f"{size_in_bytes:.2f} TB"

    async def process_reddit_url(self, url):
        try:
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                title_tag = soup.find('title')
                if title_tag:
                    return f"[\x0303Website\x03] {title_tag.text}"
                else:
                    return "Title not found"
            else:
                print(f"Error: Response status {response.status_code}")
                return
        except Exception as e:
            return f"Error: {str(e)}"

    async def process_url(self, url):
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname

        if hostname in ['www.amazon.com', 'www.amazon.co.uk']:
            return self.process_amazon_url(url)
        elif hostname == 'crates.io':
            return self.process_crates_url(url)
        elif hostname == 'twitter.com':
            return f"[\x0303Website\x03] X (formerly Twitter)"
        elif hostname in ['www.youtube.com', 'youtube.com', 'youtu.be']:
            return await self.process_youtube_video(url)
        elif hostname in ['reddit.com', 'www.reddit.com']:
            old_reddit_url = url.replace(hostname, 'old.reddit.com')
            return await self.process_reddit_url(old_reddit_url)
        elif hostname == 'dpaste.com':
            raw_text_url = f"{url}.txt" if not url.endswith('.txt') else url
            return await self.sanitize_input(await self.extract_webpage_title(raw_text_url))
        else:
            return await self.sanitize_input(await self.extract_webpage_title(url))

    async def process_youtube_video(self, url):
        loop = asyncio.get_event_loop()
        try:
            video_id = self.extract_video_id(url)
            video_data = await loop.run_in_executor(None, self.fetch_youtube_video_data, video_id)
            return self.format_video_data(video_data)
        except Exception as e:
            print(f"Error processing YouTube video: {e}")

    def extract_video_id(self, url):
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        video_id = query_params.get('v', [None])[0]
        if not video_id:
            raise ValueError("YouTube video ID could not be extracted.")
        return video_id

    def fetch_youtube_video_data(self, video_id):
        request = self.youtube_service.videos().list(
            part="snippet,statistics",
            id=video_id
        )
        response = request.execute()
        if 'items' in response and len(response['items']) > 0:
            return response['items'][0]
        else:
            raise Exception("Video data not found")

    def format_video_data(self, video_data):
        title = video_data['snippet']['title']
        viewCount = video_data['statistics']['viewCount']
        likeCount = video_data['statistics']['likeCount']
        favoriteCount = video_data['statistics']['favoriteCount']
        commentCount = video_data['statistics']['commentCount']
        
        formatted_data = (f"Title: \x02{title}\x0F Views: \x1F{viewCount}\x0F Likes: \x1D{likeCount}\x0F Favorites: \x0303\x02{favoriteCount}\x0F Comments: \x0307\x02{commentCount}\x0F")
        return f"[\x0301,00\x02You\x0300,04\x02Tube\x03] {formatted_data}"

    def process_amazon_url(self, url):
        product_name = " ".join(url.split('/')[3].split('-')).title()
        return f"[\x0303Amazon\x03] Product: {product_name}"

    def process_crates_url(self, url):
        # Extract the crate name and version from the URL
        parts = url.split('/')
        crate_name = parts[-2]
        crate_version = parts[-1]

        return f"[\x0303Webpage\x03] crates.io: Rust Package Registry: {crate_name}{crate_version}"

    def handle_title_not_found(self, url, e):
        self.save_no_title(url, e)

    def save_no_title(self, url, e):
        # Get the current datetime for the log entry
        now = datetime.datetime.now()
        log_entry = f"{now}: Title not found for URL: {url} {e}\n"

        # Append the log entry to the file
        with open("error_log.txt", "a") as log_file:
            log_file.write(log_entry)

    async def handle_pdf_file(self, url):
        site_name = url.split('/')[2]
        file_identifier = url.split('/')[-1]

        # Determine the script directory and pdfs directory
        script_directory = os.path.dirname(os.path.abspath(__file__))
        pdfs_directory = os.path.join(script_directory, "pdfs")
        
        # Ensure the pdfs directory exists
        if not os.path.exists(pdfs_directory):
            os.makedirs(pdfs_directory)

        # Make a HEAD request to get headers
        head_response = requests.head(url)

        # Extract the Content-Length header, which contains the file size in bytes
        pdf_size_bytes = head_response.headers.get('Content-Length')

        # If Content-Length header is present, format the file size
        if pdf_size_bytes is not None:
            pdf_size_bytes = int(pdf_size_bytes)  # Convert to integer
            formatted_size = self.format_file_size(pdf_size_bytes)
            
            try:
                # Download the PDF content with a GET request
                pdf_response = requests.get(url, stream=True)

                # Save the PDF file to the pdfs directory
                pdf_path = os.path.join(pdfs_directory, file_identifier)
                with open(pdf_path, "wb") as pdf_file:
                    for chunk in pdf_response.iter_content(chunk_size=8192):
                        pdf_file.write(chunk)

                response = f"[\x0313PDF file\x03] {site_name} {file_identifier}: {formatted_size}"
            except Exception as e:
                print(f"Unable to download the PDF file: {e}")
        else:
            response = f"[\x0304PDF file\x03] {site_name} {file_identifier}: Size Unknown"

        return response

    async def handle_gzip(self, url):
        site_name = url.split('/')[2]
        file_identifier = url.split('/')[-1]
        # Make a HEAD request to get headers
        response = requests.head(url)
        
        # Extract the Content-Length header, which contains the file size in bytes
        file_size_bytes = response.headers.get('Content-Length')
        
        # If Content-Length header is present, format the file size
        if file_size_bytes is not None:
            file_size_bytes = int(file_size_bytes)  # Convert to integer
            formatted_size = self.format_file_size(file_size_bytes)
            response = f"[\x0313Compressed file\x03] {site_name} {file_identifier}: {formatted_size}"
            return response
        else:
            return f"[\x0304Compressed file\x03] {site_name} {file_identifier}: Size Unknown"

    async def handle_video_file(self, url):
        site_name = url.split('/')[2]
        paste_code = url.split('/')[-1]

        # Determine the script directory and video_files directory
        script_directory = os.path.dirname(os.path.abspath(__file__))
        video_files_directory = os.path.join(script_directory, "video_files")
        
        # Ensure the video_files directory exists
        if not os.path.exists(video_files_directory):
            os.makedirs(video_files_directory)

        # Make a HEAD request to get headers
        head_response = requests.head(url)

        # Extract the Content-Length header, which contains the file size in bytes
        video_size_bytes = head_response.headers.get('Content-Length')

        # If Content-Length header is present, format the file size
        if video_size_bytes is not None:
            video_size_bytes = int(video_size_bytes)  # Convert to integer
            formatted_size = self.format_file_size(video_size_bytes)
            
            try:
                # Download the video content with a GET request
                video_response = requests.get(url, stream=True)

                # Save the video file to the video_files directory
                video_path = os.path.join(video_files_directory, paste_code)
                with open(video_path, "wb") as video_file:
                    for chunk in video_response.iter_content(chunk_size=8192):
                        video_file.write(chunk)

                response = f"[\x0307Video file\x03] {site_name} {paste_code}: {formatted_size}"
            except Exception as e:
                print(f"Unable to download the video file: {e}")
        else:
            response = f"[\x0304Video file\x03] {site_name} {paste_code}: Size Unknown"

        return response

    async def handle_image_url(self, url):
        # Clean the URL by removing query parameters
        clean_url = url.split('?')[0]
        
        site_name = clean_url.split('/')[2]
        paste_code = clean_url.split('/')[-1]

        # Determine the script directory
        script_directory = os.path.dirname(os.path.abspath(__file__))
        images_directory = os.path.join(script_directory, "images")
        
        # Ensure the images directory exists
        if not os.path.exists(images_directory):
            os.makedirs(images_directory)

        try:
            image_response = requests.get(clean_url, headers=self.headers)
            image_size_bytes = len(image_response.content)
            formatted_image_size = self.format_file_size(image_size_bytes)

            # Use Pillow to get image dimensions
            image = Image.open(io.BytesIO(image_response.content))
            width, height = image.size
            image_dimensions = f"{width}x{height}"
            
            # Save the image to the images directory
            image_path = os.path.join(images_directory, paste_code)
            with open(image_path, "wb") as img_file:
                img_file.write(image_response.content)

        except Exception as e:
            print(f"Error fetching and saving image: {e}")
            formatted_image_size = "unknown size"
            image_dimensions = "N/A"
        
        return f"[\x0311Image File\x03] {site_name} {paste_code} - Size: {image_dimensions}/{formatted_image_size}"

    async def handle_audio_file(self, url):
        site_name = url.split('/')[2]
        paste_code = url.split('/')[-1]

        script_directory = os.path.dirname(os.path.abspath(__file__))
        sounds_directory = os.path.join(script_directory, "sounds")

        if not os.path.exists(sounds_directory):
            os.makedirs(sounds_directory)

        response = f"[\x0307Audio File\x03] {site_name} (Audio) {paste_code} - Size: unknown size"

        try:
            audio_response = requests.get(url, headers=self.headers, stream=True)
            audio_size_bytes = int(audio_response.headers.get('Content-Length', 0))

            formatted_audio_size = self.format_file_size(audio_size_bytes)

            # Save the audio file to the sounds directory
            audio_path = os.path.join(sounds_directory, paste_code)
            with open(audio_path, "wb") as audio_file:
                for chunk in audio_response.iter_content(chunk_size=8192):
                    audio_file.write(chunk)

            response = f"[\x0307Audio File\x03] {site_name} {paste_code} - Size: {formatted_audio_size}"
        except Exception as e:
            print(f"Error fetching and saving audio file: {e}")

        return response

    async def handle_text_file(self, url):
        site_name = url.split('/')[2]
        paste_code = url.split('/')[-1]

        script_directory = os.path.dirname(os.path.abspath(__file__))
        texts_directory = os.path.join(script_directory, "texts")

        if not os.path.exists(texts_directory):
            os.makedirs(texts_directory)

        response = f"[\x0313Text File\x03] {paste_code} - Size: unknown size"

        try:
            text_response = requests.get(url, headers=self.headers)
            text_size_bytes = len(text_response.content)
            formatted_text_size = self.format_file_size(text_size_bytes)

            text_path = os.path.join(texts_directory, f"{paste_code}.txt")
            with open(text_path, "wb") as text_file:
                text_file.write(text_response.content)

            response = f"[\x0313Text File\x03] {paste_code} - Size: {formatted_text_size}"
        except Exception as e:
            print(f"Error fetching and saving text file: {e}")

        return response

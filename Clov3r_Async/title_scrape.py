import asyncio
import aiohttp
import socket
import re
import requests
import ipaddress
import html
import http.client
import ssl
import io
import os
import magic
import json
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from html import escape, unescape
from requests.exceptions import HTTPError, Timeout, RequestException
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from PIL import Image
from gentoo_bugs import get_bug_details
from reddit_urls import parse_reddit_url


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
        ignore_ssl_errors = False  # Flag to indicate whether to ignore SSL errors
        headers = self.headers  # Define headers with User-Agent

        for attempt in range(2):  # Attempt connection with possible retry for SSL error
            try:
                parsed_url = urlparse(url)  # Re-parse URL on retry
                if parsed_url.scheme == 'http':
                    connection = http.client.HTTPConnection(parsed_url.netloc, timeout=REQUEST_TIMEOUT)
                else:
                    if ignore_ssl_errors:
                        # Create an unverified SSL context
                        context = ssl._create_unverified_context()
                        connection = http.client.HTTPSConnection(parsed_url.netloc, timeout=REQUEST_TIMEOUT, context=context)
                    else:
                        connection = http.client.HTTPSConnection(parsed_url.netloc, timeout=REQUEST_TIMEOUT)
                
                connection.request("GET", parsed_url.path or '/', headers=headers)  # Include the headers in the request
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
                    
                    if content_type in ['application/octet-stream', 'application/zip', 'text/plain']:
                        if url.endswith(('.mp3', '.flac', '.wav', '.aac', '.ogg', '.wma', '.mha', '.mhm', '.aiff', '.alac', '.opus', '.spx', '.amr', '.ac3', '.dsf', '.dff', '.ape')):
                            return await self.handle_audio_file(url)
                        elif url.endswith(('.bat', '.toml', '.sh')):
                            return await self.handle_script(url, content_type)
                    else:
                        pass

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
                    elif content_type in ['text/plain', 'text/rtf', 'text/richtext']:
                        return await self.handle_text_file(url)
                    elif content_type.startswith(('text/x-', 'application/x-')) or content_type in ['application/perl', 'application/x-python-code', 'application/javascript', 'text/css', 'application/json', 'text/vnd.curl', 'application/typescript', 'application/xml', 'text/xml', 'application/toml']:
                        return await self.handle_script(url, content_type)
                    elif content_type.startswith('audio/'):
                        return await self.handle_audio_file(url)
                    elif content_type == 'application/pdf':
                        return await self.handle_pdf_file(url)
                    elif content_type in ['application/octet-stream', 'application/zip']:
                        return await self.handle_gzip(url)
                    elif content_type == 'application/x-iso9660-image':
                        return "ISO"
                    elif content_type.startswith('text/html'):
                        remaining_content_bytes = response.read()
                        full_content = content_bytes + remaining_content_bytes
                        
                        decoded_content = full_content.decode(charset, errors='ignore')
                        soup = BeautifulSoup(decoded_content, 'html.parser')

                        title_tag = soup.find('title')
                        title = title_tag.text.strip() if title_tag else None

                        if title:
                            print(f"Extracted title tag: {title}")
                            return f"[\x0303Website\x03] {title}"
                        else:
                            meta_name_title_tag = soup.find('meta', {'name': 'title'})
                            meta_name_title = meta_name_title_tag['content'].strip() if meta_name_title_tag else None

                            if meta_name_title:
                                print(f"Extracted meta name=title: {meta_name_title}")
                                return f"[\x0303Website\x03] {meta_name_title}"
                            else:
                                og_title_tag = soup.find('meta', attrs={'property': 'og:title'})
                                og_title = og_title_tag['content'].strip() if og_title_tag else None

                                if og_title:
                                    print(f"Extracted og:title: {og_title}")
                                    return f"[\x0303Website\x03] {og_title}"
                                else:
                                    print(f"Title not found")
                                    e = f"extract_webpage_title could not find title for {url}"
                                    self.handle_title_not_found(url, e)

                    elif content_length > MAX_FILE_SIZE:
                        e = f"Max Size"
                        self.handle_title_not_found(url, e)
                        return 
                    elif any(url.lower().endswith(ext) for ext in EXECUTABLE_FILE_EXTENSIONS):
                        e = f"Banned File Type"
                        self.handle_title_not_found(url, e)
                        return 
                    else:
                        e = f"Unknown mime/type {content_type}"
                        self.handle_title_not_found(url, e)
                        return
                else:
                    return
            except socket.timeout:
                print(f"Request timed out for {url}")
                # Handle timeout, potentially with a 'break' or 'continue' depending on your retry logic
            except ssl.SSLCertVerificationError:
                if attempt == 0:
                    print("SSL certificate verification failed. Retrying with verification disabled.")
                    ignore_ssl_errors = True
                    # Continue to retry the connection
                    continue
                else:
                    raise
            except http.client.HTTPException as e:
                print(f"Error retrieving webpage title for {url}: {e}")
                # Handle HTTP exceptions here
                break
            finally:
                connection.close()

    def format_file_size(self, size_in_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_in_bytes < 1024.0:
                return f"{size_in_bytes:.2f} {unit}"
            size_in_bytes /= 1024.0

        return f"{size_in_bytes:.2f} TB"

    async def process_url(self, url):
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname

        if hostname in ['www.amazon.com', 'www.amazon.co.uk']:
            return self.process_amazon_url(url)
        elif hostname == 'crates.io':
            return self.process_crates_url(url)
        elif hostname == 'twitter.com':
            return f"[\x0303Website\x03] X (formerly Twitter)"
        elif hostname in ['www.youtube.com', 'youtube.com', 'youtu.be', 'm.youtube.com']:
            return await self.process_youtube_video(url)
        elif hostname in ['reddit.com', 'www.reddit.com']:
            return await parse_reddit_url(url)
        elif hostname == 'dpaste.com':
            raw_text_url = f"{url}.txt" if not url.endswith('.txt') else url
            return await self.sanitize_input(await self.extract_webpage_title(raw_text_url))
        elif hostname == 'bugs.gentoo.org':
            return await self.handle_gentoo_bugs(url)
        else:
            return await self.sanitize_input(await self.extract_webpage_title(url)) # https://bugs.gentoo.org/902829

    async def handle_gentoo_bugs(self, url):
        bug_number = url.split('/')[-1]
        response = get_bug_details(bug_number)
        return response

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
        video_id = None
        
        if parsed_url.netloc in ['www.youtube.com', 'youtu.be', 'm.youtube.com']:
            if parsed_url.path.startswith('/watch'):
                query_params = parse_qs(parsed_url.query)
                video_id = query_params.get('v', [None])[0]
            elif parsed_url.path.startswith('/shorts'):
                video_id = parsed_url.path.split('/')[2]
            elif parsed_url.netloc == 'youtu.be':
                video_id = parsed_url.path.lstrip('/')
        
        if not video_id:
            raise ValueError("YouTube video ID could not be extracted.")
        return video_id

    def fetch_youtube_video_data(self, video_id):
        script_directory = os.path.dirname(os.path.abspath(__file__))
        youtube_cache = os.path.join(script_directory, "youtube_cache")
        
        # Ensure the youtube_cache directory exists
        if not os.path.exists(youtube_cache):
            os.makedirs(youtube_cache)
        
        cache_file_path = os.path.join(youtube_cache, f"{video_id}.json")
        
        # Check if the cache file exists and is less than 24 hours old
        if os.path.exists(cache_file_path):
            file_mod_time = datetime.fromtimestamp(os.path.getmtime(cache_file_path))
            if datetime.now() - file_mod_time < timedelta(hours=72):
                with open(cache_file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        
        # If the cache file does not exist or is outdated, fetch data from the API
        request = self.youtube_service.videos().list(
            part="snippet,contentDetails,statistics",
            id=video_id
        )
        response = request.execute()
        
        if 'items' in response and len(response['items']) > 0:
            print(f"{response['items'][0]}")
            
            # Save the new or updated video data to the cache file
            with open(cache_file_path, 'w', encoding='utf-8') as f:
                json.dump(response['items'][0], f, ensure_ascii=False, indent=2)
            
            return response['items'][0]
        else:
            raise Exception("Video data not found")

    def format_video_data(self, video_data):
        title = video_data['snippet']['title']
        uploader = video_data['snippet']['channelTitle']
        live = video_data['snippet']['liveBroadcastContent']
        duration = video_data['contentDetails']['duration']
        
        # Use regular expressions to find hours, minutes, and seconds
        hours = re.search(r'(\d+)H', duration)
        minutes = re.search(r'(\d+)M', duration)
        seconds = re.search(r'(\d+)S', duration)
        
        # Convert matches to integers, or default to 0 if not found
        hours_value = int(hours.group(1)) if hours else 0
        minutes_value = int(minutes.group(1)) if minutes else 0
        seconds_value = int(seconds.group(1)) if seconds else 0
        
        formatted_parts = [f"\x02{title}\x0F"]
        if live and live != 'none':
            formatted_parts.append("\x0304LIVE!\x0F")
        else:
            # Format the duration, including hours if present
            if hours_value > 0:
                formatted_duration = f"\x02{hours_value}h:{minutes_value:02d}m:{seconds_value:02d}s\x0F"
            else:
                formatted_duration = f"\x02{minutes_value}m:{seconds_value:02d}s\x0F"
            formatted_parts.append(formatted_duration)
            
        if uploader:
            formatted_parts.append(f"\x02{uploader}\x0F")
        
        formatted_data = " | ".join(formatted_parts)
        return f"[\x0301,00\x02You\x0300,04\x02Tube\x03]\x0F {formatted_data}"

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
        now = datetime.now()
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

                response = f"[\x0313PDF file\x03] {file_identifier}: {formatted_size}"
            except Exception as e:
                print(f"Unable to download the PDF file: {e}")
        else:
            response = f"[\x0304PDF file\x03] {file_identifier}: Size Unknown"

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
            response = f"[\x0313Compressed file\x03] {file_identifier}: {formatted_size}"
            return response
        else:
            return f"[\x0304Compressed file\x03] {file_identifier}: Size Unknown"

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

                response = f"[\x0307Video file\x03] {paste_code}: {formatted_size}"
            except Exception as e:
                print(f"Unable to download the video file: {e}")
        else:
            response = f"[\x0304Video file\x03] {paste_code}: Size Unknown"

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
        
        return f"[\x0311Image File\x03] {paste_code} - Size: {image_dimensions}/{formatted_image_size}"

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

            response = f"[\x0307Audio File\x03] {paste_code} - Size: {formatted_audio_size}"
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

    async def handle_script(self, url, content_type):
        site_name = url.split('/')[2]
        paste_code = url.split('/')[-1].split('?')[0]

        mime_type_extension_mapping = {
            'text/plain': '.txt',
            'application/javascript': '.js',
            'text/css': '.css',
            'application/json': '.json',
            'text/x-python': '.py',
            'text/x-diff': '.diff',
            'text/x-yaml': '.yaml',
            'text/x-log': '.log',
            'text/x-asm': '.asm',
            'text/x-csv': '.csv',
            'text/x-c': '.c',
            'text/x-java-source': '.java',
            'text/x-json': '.json',
            'text/x-markdown': '.markdown',
            'text/x-latex': '.tex',
            'text/x-httpd-php': '.php',
            'text/vnd.curl': '.curl',
            'text/x-shellscript': '.sh',
            'text/x-scriptzsh': '.zsh',
            'text/x-sql': '.sql',
            'text/x-ruby': '.rb',
            'text/x-perl': '.pl',
            'text/x-c++src': '.cpp',
            'text/x-csrc': '.c',
            'application/xml': '.xml',
            'text/xml': '.xml',
            'text/x-lua': '.lua',
            'text/x-scala': '.scala',
            'text/x-erlang': '.erl',
            'text/x-groovy': '.groovy',
            'text/x-kotlin': '.kt',
            'text/x-swift': '.swift',
            'text/x-go': '.go',
            'text/x-typescript': '.ts',
            'application/typescript': '.ts',
            'text/x-sass': '.sass',
            'text/x-scss': '.scss',
            'text/x-haskell': '.hs',
            'text/x-rust': '.rs',
            'text/x-powershell': '.ps1',
            'application/x-bat': '.bat',
            'application/x-shellscript': '.sh',
            'text/x-matlab': '.m',
            'application/toml': '.toml',
        }

        script_directory = os.path.dirname(os.path.abspath(__file__))
        texts_directory = os.path.join(script_directory, "scripts")

        if not os.path.exists(texts_directory):
            os.makedirs(texts_directory)

        response = f"[\x0310Script/Source\x03] {paste_code} - Size: unknown size"

        try:
            headers = self.headers
            text_response = requests.get(url, headers=headers)
            text_size_bytes = len(text_response.content)
            formatted_text_size = self.format_file_size(text_size_bytes)

            # Extract file extension from URL if present
            url_file_extension = os.path.splitext(paste_code)[1]
            if url_file_extension:
                file_extension = ""
            else:
                file_extension = mime_type_extension_mapping.get(content_type, '.txt')
            
            # Generate the file path with the appropriate extension
            text_path = os.path.join(texts_directory, f"{paste_code}{file_extension}")
            
            with open(text_path, "wb") as text_file:
                text_file.write(text_response.content)

            response = f"[\x0310Script/Source\x03] {paste_code} - Size: {formatted_text_size}"
        except Exception as e:
            print(f"Error fetching and saving text file: {e}")

        return response
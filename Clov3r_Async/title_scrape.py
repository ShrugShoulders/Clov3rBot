import asyncio
import aiohttp
import re
import requests
import ipaddress
import html
import http.client
import datetime
import io
import os
from html import escape, unescape
from requests.exceptions import HTTPError, Timeout, RequestException
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from PIL import Image

class Titlescraper:
    def __init__(self):
        self.headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0', 'Accept-Encoding': 'identity'}
        self.url_regex = re.compile(r'https?://\S+')

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
        parsed_url = urlparse(url)
        connection = http.client.HTTPConnection(parsed_url.netloc) if parsed_url.scheme == 'http' else http.client.HTTPSConnection(parsed_url.netloc)
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
                content_type = response.getheader('Content-Type', '').lower()
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
                    content = response.read()
                    decoded_content = content.decode(charset, errors='ignore')
                    soup = BeautifulSoup(decoded_content, 'html.parser')

                    # Attempt to extract the og:title tag
                    og_title_tag = soup.find('meta', attrs={'property': 'og:title'})
                    og_title = og_title_tag['content'].strip() if og_title_tag else None

                    meta_name_title_tag = soup.find('meta', {'name': 'title'})
                    meta_name_title = meta_name_title_tag['content'].strip() if meta_name_title_tag else None

                    # Extract the <title> tag, also consider additional attributes like data-react-helmet
                    title_tag = soup.find('title')
                    title = title_tag.text.strip() if title_tag else None

                    # Determine which title to return
                    if og_title:
                        print(f"Extracted og:title: {og_title}")
                        return f"[\x0303Website\x03] {og_title}"
                    elif meta_name_title:
                        print(f"Extracted meta name=title: {meta_name_title}")
                        return f"[\x0303Website\x03] {meta_name_title}"
                    elif title:
                        print(f"Extracted title tag: {title}")
                        return f"[\x0303Website\x03] {title}"
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
        except http.client.HTTPException as e:
            print(f"Error retrieving webpage title for {url}: {e}")
            self.handle_title_not_found(url, e)
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
        elif hostname in ['www.youtube.com', 'youtube.com', 'youtu.be']:
            return await self.process_youtube(url)
        else:
            return await self.sanitize_input(await self.extract_webpage_title(url))

    async def process_youtube(self, url):
        try:
            response = await self.fetch_youtube_title(url)
            return await self.extract_webpage_title_from_youtube(response)
        except Exception as e:
            print(f"Error processing YouTube link: {e}")

    async def fetch_youtube_title(self, url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=1.5)) as response:
                    response.raise_for_status()
                    return await response.text()
        except Exception as e:
            raise Exception(f"Error fetching YouTube site content: {e}")

    async def extract_webpage_title_from_youtube(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        og_title_tag = soup.find('meta', attrs={'property': 'og:title'})
        if og_title_tag and og_title_tag.has_attr('content'):
            title = unescape(og_title_tag['content'].strip())
            return f"[\x0303YouTube\x03] {title}"
        else:
            return "Title not found"

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
        # Make a HEAD request to get headers
        response = requests.head(url)
        
        # Extract the Content-Length header, which contains the file size in bytes
        pdf_size_bytes = response.headers.get('Content-Length')
        
        # If Content-Length header is present, format the file size
        if pdf_size_bytes is not None:
            pdf_size_bytes = int(pdf_size_bytes)  # Convert to integer
            formatted_size = self.format_file_size(pdf_size_bytes)
            response = f"[\x0313PDF file\x03] {site_name} {file_identifier}: {formatted_size}"
            return response
        else:
            return f"[\x0304PDF file\x03] {site_name} {file_identifier}: Size Unknown"

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
        # Make a HEAD request to get headers
        response = requests.head(url)
        
        # Extract the Content-Length header, which contains the file size in bytes
        video_size_bytes = response.headers.get('Content-Length')
        
        # If Content-Length header is present, format the file size
        if video_size_bytes is not None:
            video_size_bytes = int(video_size_bytes)  # Convert to integer
            formatted_size = self.format_file_size(video_size_bytes)
            response = f"[\x0307Video file\x03] {site_name} {paste_code}: {formatted_size}"
            return response
        else:
            return f"[\x0304Video file\x03] {site_name} {paste_code}: Size Unknown"

    async def handle_image_url(self, url):
        site_name = url.split('/')[2]
        paste_code = url.split('/')[-1]

        # Determine the script directory
        script_directory = os.path.dirname(os.path.abspath(__file__))
        images_directory = os.path.join(script_directory, "images")
        
        # Ensure the images directory exists
        if not os.path.exists(images_directory):
            os.makedirs(images_directory)

        try:
            image_response = requests.get(url, headers=self.headers)
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
        # Handle the case where it's an audio file.
        site_name = url.split('/')[2]
        paste_code = url.split('/')[-1]

        # Initialize the response variable with a default value
        response = f"[\x0307Audio File\x03] {site_name} (Audio) {paste_code} - Size: unknown size"

        try:
            audio_response = requests.get(url, headers=self.headers, stream=True)
            audio_size_bytes = int(audio_response.headers.get('Content-Length', 0))

            formatted_audio_size = self.format_file_size(audio_size_bytes)
            response = f"[\x0307Audio File\x03] {site_name} {paste_code} - Size: {formatted_audio_size}"
        except Exception as e:
            print(f"Error fetching audio size: {e}")

        return response

    async def handle_text_file(self, url):
        # Handle the case where it's a plain text file.
        site_name = url.split('/')[2]
        paste_code = url.split('/')[-1]

        # Get the text file size using a GET request
        try:
            text_response = requests.get(url, headers=self.headers)
            text_size_bytes = len(text_response.content)

            formatted_text_size = self.format_file_size(text_size_bytes)
            response = f"[\x0313Text File\x03] {site_name} {paste_code} - Size: {formatted_text_size}"
        except Exception as e:
            print(f"Error fetching text file size: {e}")
            formatted_text_size = "unknown size"

        return response
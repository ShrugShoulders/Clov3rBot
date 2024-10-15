import asyncio
import requests
import re
import reddit_test
from urllib.parse import urlparse
from bs4 import BeautifulSoup


async def process_reddit_url(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0', 'Accept-Encoding': 'identity'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            title_tag = soup.find('title')
            if title_tag:
                return f"[\x0303Reddit\x03] {title_tag.text}"
            else:
                return "Title not found"
        else:
            print(f"Error: Response status {response.status_code}")
            return
    except Exception as e:
        return f"Error: {str(e)}"

async def process_video_reddit_url(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0', 'Accept-Encoding': 'identity'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            title_tag = soup.find('shreddit-title', {'title': True})
            if title_tag:
                return f"[\x0303Reddit\x03] {title_tag['title']}"
            else:
                return "shreddit-title tag not found"
        else:
            return f"Error: Response status {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

async def parse_reddit_url(normalized_content):
    url_regex = re.compile(r'https?://[^\s\x00-\x1F\x7F]+')
    match = url_regex.search(normalized_content)
    
    if match:
        url = match.group()
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
        path = parsed_url.path

        if hostname and ('reddit.com' in hostname or 'redd.it' in hostname):
            if '/videos/' in path:
                if 'old.reddit.com' in hostname:
                    new_url = url.replace('old.reddit.com', 'www.reddit.com')
                    return await process_video_reddit_url(new_url)
                else:
                    return await process_video_reddit_url(url)
            if '/videos/' not in path:
                if '/s/' in path:
                    resolved_url = reddit_test.get_resolved_url(url)
                    old_reddit_url = reddit_test.convert_to_old_reddit(resolved_url)
                    title = reddit_test.fetch_title(old_reddit_url)
                    return f"[\x0303Reddit\x03] {title}" 
                if 'old.reddit.com' not in hostname:
                    old_reddit_url = url.replace(hostname, 'old.reddit.com')
                    return await process_reddit_url(old_reddit_url)
                else:
                    return await process_reddit_url(url)
        else:
            print(f"URL: {url} is not a Reddit URL")
    else:
        pass

import requests
from bs4 import BeautifulSoup

def get_resolved_url(initial_url):
    response = requests.get(initial_url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0'})
    return response.url

def convert_to_old_reddit(url):
    return url.replace('www.reddit.com', 'old.reddit.com')

def fetch_title(url):
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0'})
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        title_tag = soup.find('title')
        return title_tag.text if title_tag else "Title not found"
    else:
        return f"Error: Response status {response.status_code}"

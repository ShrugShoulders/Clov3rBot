import asyncio
import aiohttp
from bs4 import BeautifulSoup

async def handle_color_command(sender, channel, args):
    input_value = args.strip()

    # Strip out the '#' if it's present
    if input_value.startswith('#'):
        input_value = input_value[1:]

    # Check if input is in RGB decimal format
    if ',' in input_value:
        try:
            rgb_values = [int(x) for x in input_value.split(',')]
            if len(rgb_values) == 3 and all(0 <= x <= 255 for x in rgb_values):
                # Convert RGB to hex
                color_code = ''.join(f'{x:02x}' for x in rgb_values)
            else:
                raise ValueError
        except ValueError:
            response = f"PRIVMSG {channel} :Invalid RGB format. Please use the format R,G,B where R, G, and B are between 0 and 255."
            return response
    else:
        color_code = input_value

    # Validate hex color code
    if len(color_code) == 6 and all(c in '0123456789abcdefABCDEF' for c in color_code):
        response = await get_color_info(color_code, channel)
        return response
    else:
        response = f"PRIVMSG {channel} :Invalid color code format. Please use a 6-digit hexadecimal code or R,G,B format."
        return response

async def get_color_info(color_code, channel):
    url = f"https://www.color-hex.com/color/{color_code}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                   
                # Assuming the title tag contains the color name/description
                title = soup.title.string if soup.title else 'Unknown Color' #soup.find('title')
                    
                # Construct the response message with the title and URL
                response_message = f"Color information for {color_code} ({title}): {url}"
            else:
                response_message = "Failed to retrieve color information."
        
    response = f"PRIVMSG {channel} :{response_message}"
    return response
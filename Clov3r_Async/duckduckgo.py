from duckduckgo_search import DDGS

def duck_search(query, channel):
    # List of channels with safesearch off
    channels_with_safesearch_off = ['##', '##gnu/crack', '##rudechat']
    
    # Determine safesearch setting based on the channel
    if channel in channels_with_safesearch_off:
        safesearch_setting = 'off'
    else:
        safesearch_setting = 'on'
    
    try:
        results = DDGS().text(
            keywords=query,
            region='wt-wt',
            safesearch=safesearch_setting,
            timelimit='7d',
            max_results=1
        )
        
        if results:
            first_result = results[0]
            title = first_result['title']
            href = first_result['href']
            body = first_result['body'][:200]
            formatted_result = f"{title} {href} {body}"
            print(formatted_result)
            return formatted_result
        else:
            print("No results found.")
            return "No results found."
    except Exception as e:
        print(f"An error occurred: {e}")
        return

def duck_translate(args, is_url=False):
    try:
        split_args = args.split()
        if split_args and split_args[-1].startswith('-'):
            lang = split_args[-1][1:]  # Extract language code, excluding the dash
            query = " ".join(split_args[:-1])
        else:
            lang = 'en'  # Default to English
            query = " ".join(split_args)

        result = DDGS().translate(
            keywords=query,
            to=lang
        )
        
        if result:
            detected_language = result[0]['detected_language']
            translated_text = result[0]['translated']
            original_text = result[0]['original']
            
            if is_url == True:
                formatted_result = (f"{translated_text}")
            else:
                formatted_result = (f"Translated ({detected_language})->({lang}): {translated_text}")
                
            print(formatted_result)
            return formatted_result
        else:
            print("Translation not found.")
            return
    except Exception as e:
        print(f"An error occurred: {e}")
        return

#exception=AssertionError(

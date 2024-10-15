from duckduckgo_search import DDGS

def duck_search(query):
    try:
        results = DDGS().text(
            keywords=query,
            region='wt-wt',
            safesearch='off',
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
        from_lang = None
        to_lang = 'en'  # Default target language
        
        # Check if there are language codes specified in the command
        for arg in split_args:
            if arg.startswith('+'):
                from_lang = arg[1:]
            elif arg.startswith('-'):
                to_lang = arg[1:]
        
        # Remove language codes from the command arguments
        clean_args = [arg for arg in split_args if not arg.startswith(('+', '-'))]
        query = " ".join(clean_args)

        result = DDGS().translate(
            keywords=query,
            from_=from_lang,  # Pass the source language
            to=to_lang,      # Pass the target language
        )
        
        if result:
            detected_language = result[0]['detected_language']
            translated_text = result[0]['translated']
            original_text = result[0]['original']
            
            if is_url:
                formatted_result = f"{translated_text}"
            elif from_lang is not None:
                formatted_result = f"Translated ({from_lang})->({to_lang}): {translated_text}"
            else:
                formatted_result = f"Translated ({detected_language})->({to_lang}): {translated_text}"
                
            print(formatted_result)
            return formatted_result
        else:
            print("Translation not found.")
            return
    except Exception as e:
        print(f"An error occurred: {e}")
        return

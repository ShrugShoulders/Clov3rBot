import requests

def get_bug_details(args):
    bug_args = args.split(" ")
    bug_id = bug_args[0]
    action_list = ['change', 'creation']
    search_term = None
    action = None
    occurrence = 1

    # Check if there's a second argument and determine if it's an action or search term
    if len(bug_args) > 1:
        if bug_args[1].lower() in action_list:
            action = bug_args[1].lower()
        else:
            action = None
            search_term = bug_args[1]

    # Check for occurrence as a third argument
    if len(bug_args) > 2:
        try:
            occurrence = int(bug_args[2])  # Convert the third argument to an integer for occurrence
        except ValueError:
            print("Occurrence is not a valid integer. Using default value of 1.")
            occurrence = 1

    url = f"https://bugs.gentoo.org/rest/bug/{bug_id}"
    send_url = f"https://bugs.gentoo.org/{bug_id}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        if "bugs" in data and len(data["bugs"]) > 0:
            bug = data["bugs"][0]
            if search_term:
                search_results = search_bug_data(bug, search_term, occurrence)
                if search_results:
                    return f"Search result for '{search_term}': {search_results} More details: {send_url}"
                else:
                    return f"No results found for '{search_term}' at occurrence {occurrence}."
            else:
                bug_details = f"{bug['product']}, {bug['severity']}, {bug['status']}: {bug['summary']} ({send_url})"
                if action == "change":
                    details = f"{bug_id}: Last Change Time - {bug['last_change_time']} ({send_url})"
                    return details
                elif action == "creation":
                    details = f"Creator: {bug['creator']} @ {bug['creation_time']} ({send_url})"
                    return details
                else:
                    return bug_details
        else:
            return "No bug details found."
    else:
        return "Failed to retrieve bug details."

def search_bug_data(bug, term, occurrence=1):
    """
    Searches the bug's data for the given term, aiming for an exact or partial key match,
    and returns the value of the specified occurrence directly. Prioritizes exact matches.
    """
    term = term.lower()  # Case-insensitive search
    exact_matches = []
    partial_matches = []

    def search_recursive(data):
        if isinstance(data, dict):
            for key, value in data.items():
                key_lower = key.lower()
                # Check for an exact match with the key
                if term == key_lower:
                    exact_matches.append(value)  # Collect the exact match
                elif term in key_lower:
                    partial_matches.append(value)  # Collect the partial match
                # Recursive search within the value
                search_recursive(value)
        elif isinstance(data, list):
            for item in data:
                search_recursive(item)

    search_recursive(bug)

    # Determine which list to use based on the availability of exact matches
    matches = exact_matches if exact_matches else partial_matches

    # Check if the specified occurrence is within the range of found matches
    if 0 < occurrence <= len(matches):
        return matches[occurrence - 1]  # Return the value of the specified occurrence
    else:
        return None
import requests

def get_bug_details(args):
    bug_args = args.split(" ")
    bug_id = bug_args[0]

    if len(bug_args) > 1:
        bug_command = bug_args[1].lower()
        action = bug_command
    else:
        action = None

    url = f"https://bugs.gentoo.org/rest/bug/{bug_id}"
    send_url = f"https://bugs.gentoo.org/{bug_id}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        if "bugs" in data and len(data["bugs"]) > 0:
            bug = data["bugs"][0]
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
            print("No bug details found.")
    else:
        print("Failed to retrieve bug details.")

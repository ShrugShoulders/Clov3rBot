import asyncio
import aiofiles
import random


class MushroomFacts:
    def __init__(self):
        self.mushroom_facts = []
        self.load_mushroom_facts()

    def extract_factoid_criteria(self, args):
        # Example: !fact parasol
        # Extract the criteria from the user's command (e.g., "parasol")
        return lambda fact: args.lower() in fact.lower()

    def load_mushroom_facts(self):
        try:
            with open("mushroom_facts.txt", "r") as file:
                self.mushroom_facts = [line.strip() for line in file.readlines()]
                print("Successfully Loaded Mushroom Facts")
        except FileNotFoundError:
            print("Mushroom facts file not found.")

    def save_mushroom_facts(self):
        with open("mushroom_facts.txt", "w") as file:
            for fact in self.mushroom_facts:
                file.write(f"{fact}\n")

    def fact_add(self, args):
        new_fact = args.strip()
        if new_fact:
            self.mushroom_facts.append(new_fact)
            self.save_mushroom_facts()
            response = f"New mushroom fact added: {new_fact}"
            return response
        else:
            response = "Please provide a valid mushroom fact."
            return response

    async def send_random_mushroom_fact(self, channel, criteria=None):
        if self.mushroom_facts:
            filtered_facts = [fact for fact in self.mushroom_facts if criteria(fact)]
            
            if filtered_facts:
                random_fact = random.choice(filtered_facts)
                print(f"Sent mushroom fact to {channel}: {random_fact}")
                return f"{random_fact}\r\n"
            else:
                print("No matching mushroom facts found based on the criteria.")
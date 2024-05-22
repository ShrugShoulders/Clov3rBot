import asyncio
import aiofiles
import random


class MushroomFacts:
    def __init__(self):
        self.mushroom_facts = []
        self.load_mushroom_facts()

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

    async def send_random_mushroom_fact(self, args):
        if self.mushroom_facts:
            criteria = args.strip().lower()
            if criteria:
                filtered_facts = [fact for fact in self.mushroom_facts if criteria in fact.lower()]
            else:
                filtered_facts = self.mushroom_facts

            if filtered_facts:
                random_fact = random.choice(filtered_facts)
                return f"{random_fact}\r\n"
            else:
                print(f"No matching mushroom facts found for criteria: {criteria}")
                return f"No matching mushroom facts found for: {criteria}\r\n"
        else:
            return "No mushroom facts available.\r\n"

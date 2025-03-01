import random
from username_rules import (
    HURUF_RATA, 
    HURUF_TIDAK_RATA, 
    HURUF_VOKAL,
    UsernameTypes
)

class UsernameGenerator:
    @staticmethod
    def ganhur(base_name: str) -> list:
        """Generate usernames by substituting random letters based on category"""
        generated = []
        for _ in range(30):
            pos = random.randint(0, len(base_name) - 1)
            new_name = list(base_name)
            if base_name[pos] in HURUF_RATA:
                new_name[pos] = random.choice(HURUF_RATA)
            elif base_name[pos] in HURUF_TIDAK_RATA:
                new_name[pos] = random.choice(HURUF_TIDAK_RATA)
            generated.append("".join(new_name))
        return generated

    @staticmethod
    def canon(base_name: str) -> list:
        """Generate usernames by swapping i/l characters"""
        generated = []
        for _ in range(30):
            if 'i' in base_name:
                new_name = base_name.replace('i', 'l', 1)
            elif 'l' in base_name:
                new_name = base_name.replace('l', 'i', 1)
            else:
                new_name = base_name
            generated.append(new_name)
        return generated

    @staticmethod
    def sop(base_name: str) -> list:
        """Generate usernames by doubling existing letters (SOP)"""
        generated = []
        for pos in range(len(base_name)):
            # Double the current letter
            new_name = base_name[:pos] + base_name[pos] + base_name[pos:]
            generated.append(new_name)
        return generated

    @staticmethod
    def scanon(base_name: str) -> list:
        """Generate usernames by adding 's' suffix"""
        return [base_name + "s" for _ in range(30)]

    @staticmethod
    def switch(base_name: str) -> list:
        """Generate usernames by swapping adjacent characters"""
        generated = []
        for _ in range(30):
            if len(base_name) > 1:
                pos = random.randint(0, len(base_name) - 2)
                new_name = list(base_name)
                new_name[pos], new_name[pos+1] = new_name[pos+1], new_name[pos]
                generated.append("".join(new_name))
            else:
                generated.append(base_name)
        return generated

    @staticmethod
    def kurkuf(base_name: str) -> list:
        """Generate usernames by removing random character"""
        generated = []
        for _ in range(30):
            if len(base_name) > 1:
                pos = random.randint(0, len(base_name) - 1)
                new_name = base_name[:pos] + base_name[pos+1:]
                generated.append(new_name)
            else:
                generated.append(base_name)
        return generated

    @staticmethod
    def tamhur(base_name: str, mode="BOTH") -> list:
        """Generate usernames by adding one letter
        mode: "TAMPING" (edges), "TAMDAL" (middle), or "BOTH"
        """
        generated = []
        all_letters = HURUF_RATA + HURUF_TIDAK_RATA

        if mode in ["TAMPING", "BOTH"]:
            # Add at start or end
            for _ in range(15):
                new_letter = random.choice(all_letters)
                if random.choice([True, False]):
                    generated.append(new_letter + base_name)  # Start
                else:
                    generated.append(base_name + new_letter)  # End

        if mode in ["TAMDAL", "BOTH"]:
            # Add in middle
            for _ in range(15):
                if len(base_name) > 1:
                    pos = random.randint(1, len(base_name) - 1)
                    new_letter = random.choice(all_letters)
                    new_name = base_name[:pos] + new_letter + base_name[pos:]
                    generated.append(new_name)
                else:
                    generated.append(base_name)

        return generated
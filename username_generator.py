import random

class UsernameGenerator:
    # Character categories
    HURUF_RATA = "aceimnorsuvwxz"
    HURUF_TIDAK_RATA = "bdfghjklpqty"
    HURUF_VOKAL = "aiueo"

    @staticmethod
    def ganhur(base_name: str) -> list:
        """Generate usernames by substituting random letters based on category"""
        generated = []
        for _ in range(30):
            pos = random.randint(0, len(base_name) - 1)
            new_name = list(base_name)
            if base_name[pos] in UsernameGenerator.HURUF_RATA:
                new_name[pos] = random.choice(UsernameGenerator.HURUF_RATA)
            elif base_name[pos] in UsernameGenerator.HURUF_TIDAK_RATA:
                new_name[pos] = random.choice(UsernameGenerator.HURUF_TIDAK_RATA)
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
        """Generate usernames by adding random character from base name"""
        return [base_name + random.choice(base_name) for _ in range(30)]

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

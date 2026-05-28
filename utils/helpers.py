import hashlib, random, string

def generate_seed(length=32):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def get_md5_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

def deterministic_winners(seed: str, total: int, count: int, exclude: list = None):
    random.seed(seed)
    indices = list(range(total))
    if exclude:
        indices = [i for i in indices if i not in exclude]
    random.shuffle(indices)
    return indices[:count]

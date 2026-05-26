import hashlib
import secrets
import random

def generate_provably_fair_round():
    salt = secrets.token_hex(16)
    seed = str(random.randint(100000, 999999))
    combined = f"{seed}:{salt}".encode('utf-8')
    sha_hash = hashlib.sha256(combined).hexdigest()
    return seed, salt, sha_hash

def get_fair_winners(participants: list, count: int, seed: str, salt: str) -> list:
    """Детерминированный выбор победителей на основе сида и соли"""
    if not participants:
        return []
    combined = f"{seed}:{salt}".encode('utf-8')
    entropy = int(hashlib.sha256(combined).hexdigest(), 16)
    
    local_rand = random.Random(entropy)
    # Копируем список, чтобы не повредить исходный порядок
    pool = list(participants)
    local_rand.shuffle(pool)
    return pool[:count]

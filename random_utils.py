import hashlib
import random
import io
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from typing import List, Tuple

def generate_seed_hash() -> Tuple[str, str]:
    seed = str(random.randint(1000000, 999999999))
    hash_obj = hashlib.sha256(seed.encode())
    return seed, hash_obj.hexdigest()

def select_winners(participants: List[int], count: int, seed: str) -> List[int]:
    rng = random.Random(seed)
    indices = list(range(len(participants)))
    rng.shuffle(indices)
    return [participants[i] for i in indices[:count]]

def create_result_image(winners: List[int], total: int, dt: datetime, seed_hash: str) -> io.BytesIO:
    """Картинка для рулетки: крупные номера победителей."""
    return _create_image_base(winners, total, dt, seed_hash, title="ЧЕСТНАЯ РУЛЕТКА")

def create_random_image(winners: List[int], lo: int, hi: int, dt: datetime, seed_hash: str) -> io.BytesIO:
    """Картинка для @рандом: номера из диапазона."""
    total = hi - lo + 1
    return _create_image_base(winners, total, dt, seed_hash, title="СЛУЧАЙНЫЕ ЧИСЛА")

def _create_image_base(winners: List[int], total: int, dt: datetime, seed_hash: str, title: str) -> io.BytesIO:
    W, H = 800, 600
    bg = (15, 15, 35)
    accent = (255, 215, 0)
    white = (255, 255, 255)

    img = Image.new('RGB', (W, H), bg)
    draw = ImageDraw.Draw(img)

    # Шрифты
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 50)
        font_winners = ImageFont.truetype("DejaVuSans-Bold.ttf", 80)
        font_info = ImageFont.truetype("DejaVuSans.ttf", 30)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 20)
    except:
        font_title = ImageFont.load_default()
        font_winners = ImageFont.load_default()
        font_info = ImageFont.load_default()
        font_small = ImageFont.load_default()

    draw.text((W/2, 70), title, fill=accent, font=font_title, anchor="mm")
    # Номера победителей крупно
    winners_str = ", ".join(str(w) for w in winners)
    draw.text((W/2, 200), winners_str, fill=white, font=font_winners, anchor="mm")
    draw.text((W/2, 300), f"Участников: 1 – {total}", fill=white, font=font_info, anchor="mm")
    time_str = dt.strftime("%d.%m.%Y %H:%M:%S") + " (НСК)"
    draw.text((W/2, 380), time_str, fill=white, font=font_info, anchor="mm")
    draw.text((W/2, 460), f"Честность: SHA256 {seed_hash[:16]}...", fill=accent, font=font_small, anchor="mm")
    draw.rectangle([20, 20, W-20, H-20], outline=accent, width=3)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

def get_verification_instruction(roulette_id: int, seed: str, participants: List[str], winners: List[str]) -> str:
    return (
        "🔍 Проверка честности:\n"
        f"1. Перейдите на https://emn178.github.io/online-tools/sha256.html\n"
        f"2. Введите seed: {seed}\n"
        f"3. Сверьте хеш с объявленным.\n"
        f"4. Скопируйте список участников и выполните код Python (инструкция в /verify)."
    )

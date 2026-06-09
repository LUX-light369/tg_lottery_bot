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
    return _create_base_image(winners, total, dt, seed_hash, "ЧЕСТНАЯ РУЛЕТКА")

def create_random_image(winners: List[int], lo: int, hi: int, dt: datetime, seed_hash: str) -> io.BytesIO:
    return _create_base_image(winners, hi - lo + 1, dt, seed_hash, "СЛУЧАЙНЫЕ ЧИСЛА")

def _create_base_image(winners: List[int], total: int, dt: datetime, seed_hash: str, title: str) -> io.BytesIO:
    W, H = 800, 600
    bg = (15, 15, 35)
    accent = (255, 215, 0)
    white = (255, 255, 255)

    img = Image.new('RGB', (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 50)
        font_info = ImageFont.truetype("DejaVuSans.ttf", 30)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 20)
    except:
        font_title = ImageFont.load_default()
        font_info = ImageFont.load_default()
        font_small = ImageFont.load_default()

    draw.text((W/2, 70), title, fill=accent, font=font_title, anchor="mm")

    # Форматируем номера с переносом, если >7
    winners_text = _format_numbers(winners)
    max_font_size = 80
    min_font_size = 20
    font_winners = None
    fit_single_line = False

    for size in range(max_font_size, min_font_size - 1, -10):
        try:
            font_winners = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
        except:
            font_winners = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), winners_text, font=font_winners)
        if bbox[2] - bbox[0] <= W - 40:
            fit_single_line = True
            break

    if fit_single_line:
        draw.text((W/2, 200), winners_text, fill=white, font=font_winners, anchor="mm")
    else:
        lines = _wrap_text(winners_text, font_winners, W - 40, draw)
        y = 200
        line_height = draw.textbbox((0, 0), "A", font=font_winners)[3] - draw.textbbox((0, 0), "A", font=font_winners)[1]
        for line in lines:
            draw.text((W/2, y), line, fill=white, font=font_winners, anchor="mm")
            y += line_height + 10

    draw.text((W/2, 300), f"Участников: 1 – {total}", fill=white, font=font_info, anchor="mm")
    time_str = dt.strftime("%d.%m.%Y %H:%M:%S") + " (НСК)"
    draw.text((W/2, 380), time_str, fill=white, font=font_info, anchor="mm")
    draw.text((W/2, 460), f"Честность: SHA256 {seed_hash[:16]}...", fill=accent, font=font_small, anchor="mm")
    draw.rectangle([20, 20, W-20, H-20], outline=accent, width=3)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

def _format_numbers(numbers: List[int]) -> str:
    """Форматирует числа с переносом строки, если их больше 7."""
    parts = [str(n) for n in numbers]
    if len(parts) <= 7:
        return ", ".join(parts)
    mid = (len(parts) + 1) // 2
    line1 = ", ".join(parts[:mid])
    line2 = ", ".join(parts[mid:])
    return f"{line1}\n{line2}"

def _wrap_text(text: str, font, max_width: int, draw) -> List[str]:
    words = text.split(', ')
    lines = []
    current_line = ""
    for word in words:
        test_line = f"{current_line}, {word}" if current_line else word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines

def get_verification_instruction(roulette_id: int, seed: str, participants: List[str], winners: List[str]) -> str:
    return (
        "🔍 Проверка честности:\n"
        f"1. Перейдите на https://emn178.github.io/online-tools/sha256.html\n"
        f"2. Введите seed: {seed}\n"
        f"3. Сверьте хеш с объявленным.\n"
        "4. Используйте кнопку «Проверить результат» в ЛС бота или скопируйте код ниже."
    )

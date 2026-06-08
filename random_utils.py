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

def create_reroll_image(old_winners: List[int], crossed: List[int], new_winners: List[int],
                        total: int, old_dt: datetime, new_dt: datetime,
                        old_hash: str, new_hash: str) -> io.BytesIO:
    W, H = 800, 700
    bg = (15, 15, 35)
    accent = (255, 215, 0)
    white = (255, 255, 255)
    grey = (128, 128, 128)

    img = Image.new('RGB', (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
        font_numbers = ImageFont.truetype("DejaVuSans.ttf", 30)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 20)
    except:
        font_title = ImageFont.load_default()
        font_numbers = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Заголовок
    draw.text((W/2, 30), "ПЕРЕКРУТ РУЛЕТКИ", fill=accent, font=font_title, anchor="mm")

    y = 80
    # Старые победители
    draw.text((W/2, y), "Предыдущий результат:", fill=white, font=font_small, anchor="mm")
    y += 30
    old_text = ", ".join(str(n) for n in old_winners)
    if crossed:
        crossed_set = set(crossed)
        parts = []
        for n in old_winners:
            parts.append(f"<s>{n}</s>" if n in crossed_set else str(n))
        old_text = ", ".join(parts)
    draw.text((W/2, y), old_text, fill=grey, font=font_numbers, anchor="mm")
    y += 50
    draw.text((W/2, y), f"Дата: {old_dt.strftime('%d.%m.%Y %H:%M')} (НСК)  Хеш: {old_hash[:16]}...", fill=grey, font=font_small, anchor="mm")
    y += 50

    # Новые победители
    draw.text((W/2, y), "Новый результат:", fill=accent, font=font_small, anchor="mm")
    y += 30
    new_text = ", ".join(str(n) for n in new_winners)
    draw.text((W/2, y), new_text, fill=white, font=font_numbers, anchor="mm")
    y += 50
    draw.text((W/2, y), f"Дата: {new_dt.strftime('%d.%m.%Y %H:%M')} (НСК)  Хеш: {new_hash[:16]}...", fill=white, font=font_small, anchor="mm")
    y += 50

    draw.text((W/2, y), f"Участников: 1 – {total}", fill=white, font=font_small, anchor="mm")
    draw.rectangle([20, 20, W-20, H-20], outline=accent, width=3)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

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

    # Заголовок
    draw.text((W/2, 70), title, fill=accent, font=font_title, anchor="mm")

    # Номера победителей (адаптивный шрифт)
    max_font_size = 80
    min_font_size = 20
    winners_text = ", ".join(str(w) for w in winners)

    # Подбираем размер шрифта
    font_winners = None
    for size in range(max_font_size, min_font_size - 1, -10):
        try:
            font_winners = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
        except:
            font_winners = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), winners_text, font=font_winners)
        text_width = bbox[2] - bbox[0]
        if text_width <= W - 40:
            break
    else:
        # Если цикл завершился без break — текст не помещается, переносим на несколько строк
        lines = _wrap_text(winners_text, font_winners, W - 40, draw)
        y = 200
        line_height = draw.textbbox((0, 0), "A", font=font_winners)[3] - draw.textbbox((0, 0), "A", font=font_winners)[1]
        for line in lines:
            draw.text((W/2, y), line, fill=white, font=font_winners, anchor="mm")
            y += line_height + 10
    else:
        # Если нашли подходящий размер, рисуем одной строкой
        draw.text((W/2, 200), winners_text, fill=white, font=font_winners, anchor="mm")

    draw.text((W/2, 300), f"Участников: 1 – {total}", fill=white, font=font_info, anchor="mm")
    time_str = dt.strftime("%d.%m.%Y %H:%M:%S") + " (НСК)"
    draw.text((W/2, 380), time_str, fill=white, font=font_info, anchor="mm")
    draw.text((W/2, 460), f"Честность: SHA256 {seed_hash[:16]}...", fill=accent, font=font_small, anchor="mm")
    draw.rectangle([20, 20, W-20, H-20], outline=accent, width=3)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

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

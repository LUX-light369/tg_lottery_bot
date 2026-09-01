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
    return _create_base_image(winners, total, dt, seed_hash, "ПОБЕДИТЕЛИ РУЛЕТКИ")

def create_random_image(winners: List[int], lo: int, hi: int, dt: datetime, seed_hash: str) -> io.BytesIO:
    return _create_base_image(winners, hi - lo + 1, dt, seed_hash, "СЛУЧАЙНЫЕ ЧИСЛА")


def _draw_winners_adaptive(draw, winners: List[int], font_path: str, box_x: int, box_y: int, box_w: int, box_h: int, color):
    """Рисует победителей в рамке, адаптируя шрифт и количество строк."""
    if not winners:
        draw.text((box_x + box_w // 2, box_y + box_h // 2), "Нет победителей", fill=color, font=ImageFont.load_default(), anchor="mm")
        return

    parts = [str(n) for n in winners]
    count = len(parts)
    max_lines_allowed = 6

    for size in range(140, 14, -5):
        try:
            font = ImageFont.truetype(font_path, size)
        except:
            font = ImageFont.load_default()

        for lines in range(1, min(count, max_lines_allowed) + 1):
            base_count = count // lines
            remainder = count % lines
            text_lines = []
            idx = 0
            
            for i in range(lines):
                current_line_count = base_count + (1 if i < remainder else 0)
                # ИЗМЕНЕНИЕ: " " заменено на " , " (2 пробела и запятая)
                text_lines.append(", ".join(parts[idx:idx + current_line_count]))
                idx += current_line_count

            max_width = 0
            total_height = 0
            line_heights = []
            spacing = 5

            for line in text_lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]
                max_width = max(max_width, width)
                line_heights.append(height)
                total_height += height

            total_height += spacing * (len(text_lines) - 1)

            if max_width <= box_w and total_height <= box_h:
                # ИЗМЕНЕНИЕ: Добавлено "+ 44" в начало отрисовки, чтобы приспустить текст ниже
                y_current = box_y + (box_h - total_height) // 2 + 44
                x_center = box_x + box_w // 2

                for i, line in enumerate(text_lines):
                    draw.text((x_center, y_current), line, fill=color, font=font, anchor="mm")
                    y_current += line_heights[i] + spacing
                return

    try:
        fallback_font = ImageFont.truetype(font_path, 15)
    except:
        fallback_font = ImageFont.load_default()
    
    chunk_size = (len(parts) + 4) // 5
    # ИЗМЕНЕНИЕ: ", " заменено на " " в запасном варианте
    lines = [" ".join(parts[i:i+chunk_size]) for i in range(0, len(parts), chunk_size)]
    combined_text = "\n".join(lines)
    draw.multiline_text((box_x + box_w // 2, box_y + box_h // 2), combined_text, fill=color, font=fallback_font, anchor="mm", align="center")


def _create_base_image(winners: List[int], total: int, dt: datetime, seed_hash: str, title: str) -> io.BytesIO:
    TEMPLATE_FILE = "roulette_template.png"
    FONT_WINNERS = "Pricedown.ttf"       
    
    # Координаты
    BOX_WINNERS = {"x": 76,  "y": 373, "w": 662, "h": 198}
    CENTER_RANGE = (604, 644)
    CENTER_TIME  = (586, 735)
    CENTER_HASH  = (571, 829)
    
    # Цвета
    COLOR_GOLD = (212, 175, 55) 
    COLOR_WHITE = (255, 255, 255)

    try:
        img = Image.open(TEMPLATE_FILE)
    except FileNotFoundError:
        img = Image.new('RGB', (1000, 667), (20, 30, 20))
    
    draw = ImageDraw.Draw(img)
    
    # Отрисовка победителей
    _draw_winners_adaptive(
        draw, 
        winners, 
        FONT_WINNERS, 
        BOX_WINNERS["x"], 
        BOX_WINNERS["y"], 
        BOX_WINNERS["w"], 
        BOX_WINNERS["h"], 
        COLOR_GOLD
    )

    # ИЗМЕНЕНИЕ: Размер шрифта увеличен с 22 до 28
    try:
        font_info = ImageFont.truetype("DejaVuSans.ttf", 28)
    except:
        font_info = ImageFont.load_default()

    # Диапазон участников
    draw.text(CENTER_RANGE, f"от 1 до {total}", fill=COLOR_GOLD, font=font_info, anchor="mm")

    # Дата и время
    time_str = dt.strftime("%d.%m.%Y %H:%M:%S")
    draw.text(CENTER_TIME, time_str, fill=COLOR_GOLD, font=font_info, anchor="mm")

    # Честность (Hash)
    hash_text = f"{seed_hash[:16]}..." 
    draw.text(CENTER_HASH, hash_text, fill=COLOR_GOLD, font=font_info, anchor="mm")

    # ИЗМЕНЕНИЕ: Сохраняем PNG без сжатия, чтобы на выходе было максимальное качество
    buf = io.BytesIO()
    img.save(buf, format='PNG', compress_level=0)
    buf.seek(0)
    return buf


def get_verification_instruction(roulette_id: int, seed: str, participants: List[str], winners: List[str]) -> str:
    return (
        "🔍 Проверка честности:\n"
        f"1. Перейдите на https://emn178.github.io/online-tools/sha256.html\n"
        f"2. Введите seed: {seed}\n"
        f"3. Сверьте хеш с объявленным.\n"
        "4. Используйте кнопку «Ручная проверка» в ЛС бота или прямую ссылку на результат рулетки."
    )
import os
import datetime
from PIL import Image, ImageDraw, ImageFont
from config import FONT_PATH

def generate_gta_results(winners_indices: list, total_count: int, date_str: str) -> str:
    # Разрешение изображения 1200х800
    img = Image.new("RGB", (1200, 800), color=(10, 25, 15)) # Тёмно-зеленый глубокий фон
    draw = ImageDraw.Draw(img)
    
    # Пытаемся загрузить кастомный шрифт, иначе дефолтный
    try:
        font_large = ImageFont.truetype(FONT_PATH, 90)
        font_medium = ImageFont.truetype(FONT_PATH, 50)
        font_small = ImageFont.truetype(FONT_PATH, 30)
    except IOError:
        font_large = font_medium = font_small = ImageFont.load_default()

    # Декоративные неоновые полосы в стиле GTA / Киберпанк (Салатовый цвет)
    neon_green = (57, 255, 20)
    draw.line([(50, 40), (1150, 40)], fill=neon_green, width=8)
    draw.line([(50, 760), (1150, 760)], fill=neon_green, width=8)
    
    # Шапка текста
    draw.text((600, 100), "ПОБЕДИТЕЛИ РУЛЕТКИ", fill=(255, 255, 255), font=font_medium, anchor="mm")
    
    # Центральный блок: Номера победителей крупно
    winners_str = ", ".join(f"#{idx}" for idx in winners_indices) if winners_indices else "НЕТ"
    draw.text((600, 360), winners_str, fill=neon_green, font=font_large, anchor="mm")
    
    # Ниже диапазон чисел
    range_str = f"Диапазон участников: 1 - {total_count}"
    draw.text((600, 520), range_str, fill=(200, 200, 200), font=font_medium, anchor="mm")
    
    # Дата и время генерации
    draw.text((600, 680), f"Дата генерации: {date_str} (НСК)", fill=(150, 150, 150), font=font_small, anchor="mm")
    
    # Сохранение изображения
    output_path = f"result_{int(datetime.datetime.now().timestamp())}.png"
    img.save(output_path)
    return output_path

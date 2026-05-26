import os
import datetime
from PIL import Image, ImageDraw, ImageFont
# Импортируем настроенные пути к трем шрифтам
from config import FONT_TITLE, FONT_WINNERS, FONT_INFO

def generate_gta_results(winners_indices: list, total_count: int, date_str: str) -> str:
    # Создаем глубокий темно-зеленый фон (1200х800 пикселей)
    img = Image.new("RGB", (1200, 800), color=(10, 25, 15)) 
    draw = ImageDraw.Draw(img)
    
    # --- Безопасная загрузка кастомных шрифтов ---
    # Если какого-то файла не окажется на месте, Pillow плавно откатится на стандартный шрифт
    try:
        font_title = ImageFont.truetype(FONT_TITLE, 65)     # Для главного заголовка
    except IOError:
        font_title = ImageFont.load_default()

    try:
        font_winners = ImageFont.truetype(FONT_WINNERS, 110) # Огромный размер для номеров в стиле GTA
    except IOError:
        font_winners = ImageFont.load_default()

    try:
        font_sub_title = ImageFont.truetype(FONT_TITLE, 45) # Для диапазона участников
        font_info = ImageFont.truetype(FONT_INFO, 26)       # Для даты и времени (мелкий, читаемый)
    except IOError:
        font_sub_title = font_info = ImageFont.load_default()

    # --- Отрисовка графических элементов (Неон) ---
    neon_green = (57, 255, 20)
    # Верхняя и нижняя неоновые рамки-линии
    draw.line([(50, 40), (1150, 40)], fill=neon_green, width=8)
    draw.line([(50, 760), (1150, 760)], fill=neon_green, width=8)
    
    # --- Размещение текста на холсте ---
    # 1. Главный заголовок (Капсом, шрифт Bebas Neue)
    draw.text((600, 120), "ПОБЕДИТЕЛИ РУЛЕТКИ", fill=(255, 255, 255), font=font_title, anchor="mm")
    
    # 2. Центральный блок: Номера победителей (Легендарный шрифт Pricedown)
    winners_str = ", ".join(f"#{idx}" for idx in winners_indices) if winners_indices else "НЕТ"
    draw.text((600, 360), winners_str, fill=neon_green, font=font_winners, anchor="mm")
    
    # 3. Диапазон участников (Шрифт Bebas Neue)
    range_str = f"ДИАПАЗОН УЧАСТНИКОВ: 1 - {total_count}"
    draw.text((600, 540), range_str, fill=(200, 200, 200), font=font_sub_title, anchor="mm")
    
    # 4. Техническая информация: Дата и время генерации (Шрифт Inter)
    draw.text((600, 690), f"Дата генерации: {date_str} (НСК)", fill=(130, 130, 130), font=font_info, anchor="mm")
    
    # Сохраняем готовую картинку во временный файл
    output_path = f"result_{int(datetime.datetime.now().timestamp())}.png"
    img.save(output_path)
    return output_path

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from datetime import datetime
import pytz
from config import TIMEZONE

def generate_roulette_image(winners_indices: list, total: int, prizes: list = None):
    img = Image.new('RGB', (800, 480), color=(10, 10, 10))
    draw = ImageDraw.Draw(img)
    try:
        font_large = ImageFont.truetype("templates/Impact.ttf", 110)
        font_mid = ImageFont.truetype("templates/Impact.ttf", 48)
        font_small = ImageFont.truetype("templates/Roboto-Regular.ttf", 28)
    except:
        font_large = ImageFont.load_default()
        font_mid = font_small = font_large
    win_nums = "  ".join(str(i+1) for i in winners_indices)
    draw.text((400, 140), win_nums, fill=(255, 215, 0), font=font_large, anchor="mm")
    range_text = f"1 — {total}"
    draw.text((400, 270), range_text, fill="white", font=font_mid, anchor="mm")
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz).strftime("%d.%m.%Y %H:%M:%S")
    draw.text((400, 400), now, fill=(180, 180, 180), font=font_small, anchor="mm")
    if prizes:
        y = 320
        for idx, prize in zip(winners_indices, prizes):
            text = f"{idx+1} — {prize}"
            draw.text((400, y), text, fill="white", font=font_small, anchor="mm")
            y += 30
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.read()

import re
import asyncio
import qrcode
import nest_asyncio
import urllib.parse
from collections import deque
from telethon import TelegramClient, events, errors, types
from telethon.tl.types import KeyboardButtonUrl

nest_asyncio.apply()

# --- ВАШІ ДАНІ ---
API_ID = 39693753
API_HASH = 'e227bd0afa19cb574427bcb2e77a11dc'
TARGET_GRAIN_GROUP_NAME = 'Агро-Культура'
TARGET_LOGISTICS_GROUP_NAME = 'Агро-Логістика'

target_grain_id = None
target_logistics_id = None
PROCESSED_MESSAGES = deque(maxlen=200)

KEYWORDS_GRAIN = {
    'Пшениця': [r'пшениц\w*'], 'Фураж': [r'фураж', r'кормов\w*'],
    'Соняшник': [r'соняшник\w*', r'подсолнух\w*', r'сеmechк\w*', r'семечек\b'],
    'Кукурудза': [r'кукурудз\w*', r'кукуруз\w*', r'кук\b'], 'Ячмінь': [r'ячmen\w*', r'ячмін\w*'],
    'Ріпак': [r'ріпак\w*', r'рапс\w*'], 'Горох': [r'горох\w*'],
    'Соя': [r'\bсоя\b', r'\bсою\b', r'\bсої\b', r'\bсое\w*'], 'Просо': [r'\bпросо\b', r'\bпроса\b', r'\bпросу\b']
}

KEYWORDS_LOGISTICS = {
    'Порти / Елеватори': [r'порт\w*', r'элеватор\w*', r'ізмаїл', r'измаил', r'рені', r'рени', r'одес\w*', r'чорноморськ', r'черноморск', r'южн\w*', r'тиса', r'силос\w*'],
    'Зерновози / Самоскиди': [r'зерновоз\w*', r'самосвал\w*', r'самоскид\w*', r'сцепк\w*', r'зчепк\w*', r'тенда\w*', r'штора\w*', r'контейнеровоз\w*', r'тягач\w*', r'камаз\w*'],
    'Регіони / Маршрути': [r'\bобл\b', r'район\w*', r'київ\w*', r'полтав\w*', r'черкас\w*', r'винниц\w*', r'вінниц\w*', r'кіровоград\w*', r'кропивн\w*', r'дніпро\w*', r'днепр\w*', r'миколаї\w*', r'николае\w*', r'умань\w*', r'львів\w*']
}

client = TelegramClient('agro_super_combo_v40', API_ID, API_HASH)

def extract_price(text):
    text_lower = text.lower()
    price_pattern = r'(\d[\d\s]*)\s*(?:грн/т|грн|грн\.|usd|\$|💸)'
    match = re.search(price_pattern, text_lower)
    if match: return f"{match.group(1).strip()} грн/валюта"
    if 'ф1' in text_lower or 'пдв' in text_lower: return "Договірна (Ф1 з ПДВ)"
    if 'ф2' in text_lower or 'готівка' in text_lower: return "Договірна (Ф2 / Готівка)"
    return "Не вказана (Договірна)"

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global target_grain_id, target_logistics_id, PROCESSED_MESSAGES
    if event.is_private or not event.text: return
    if (target_grain_id and event.chat_id == target_grain_id) or (target_logistics_id and event.chat_id == target_logistics_id): return
    
    text_lower = event.text.lower()
    clean_text = " ".join(text_lower.split())
    if clean_text in PROCESSED_MESSAGES: return

    trash_triggers = ['курс валют', 'обмін валют', 'доллар', 'посудомийниця', 'вакансія', 'олія', 'шрот', 'ищем:', 'шукаємо:']
    if any(trash in text_lower for trash in trash_triggers): return

    send_to_grain, send_to_logistics, logistics_type = False, False, None
    found_grain_tags, found_log_tags = [], []

    transport_words = ['зерновоз', 'самосвал', 'самоскид', 'сцепк', 'тенда', 'контейнеровоз', 'фрахт', 'потрібен транспорт']
    route_words = ['завантаження', 'погрузка', 'вивантаження', 'маршрут', 'напрямок', 'доставка']
    
    has_transport = any(tw in text_lower for tw in transport_words)
    has_route = any(rw in text_lower for rw in route_words)
    
    if has_transport and has_route:
        send_to_logistics = True
        logistics_type = 'driver' if any(dt in text_lower for dt in ['вільне авто', 'ищу фрахт']) else 'cargo'
    
    if not send_to_logistics:
        for category, regex_list in KEYWORDS_GRAIN.items():
            for regex in regex_list:
                if re.search(regex, text_lower):
                    found_grain_tags.append(category); break
        if found_grain_tags and any(trade in text_lower for trade in ['куплю', 'закуп', 'ціна', 'продам']):
            send_to_grain = True

    if send_to_logistics or send_to_grain:
        PROCESSED_MESSAGES.append(clean_text)
        sender = await event.get_sender()
        username = f"@{sender.username}" if getattr(sender, 'username', None) else f"ID: {sender.id}"
        contact_url = f"https://t.me/{sender.username}" if getattr(sender, 'username', None) else f"tg://user?id={sender.id}"
        
        phone_str = ", ".join(set(re.findall(r'(\+?\d{1,3}\s?\(?\d{2,3}\)?\s?\d{3,4}[\s-]?\d{2}[\s-]?\d{2})', event.text))) or "Не вказано"
        share_url = f"https://t.me/share/url?url={urllib.parse.quote(event.text)}"
        buttons = [[KeyboardButtonUrl(text="🟢 Написати", url=contact_url), KeyboardButtonUrl(text="↪️ Поділитися", url=share_url)]]

        if send_to_logistics and target_logistics_id:
            report = f"🚛 ЛОГІСТИКА\nМаршрут: {', '.join(found_log_tags)}\nКонтакт: {username}\nТелефон: `{phone_str}`\n\n{event.text}"
            await client.send_message(target_logistics_id, report, buttons=buttons)
        elif send_to_grain and target_grain_id:
            report = f"🌾 ЗЕРНО\nКультура: {', '.join(found_grain_tags)}\nЦіна: `{extract_price(event.text)}`\nКонтакт: {username}\n\n{event.text}"
            await client.send_message(target_grain_id, report, buttons=buttons)

async def main():
    global target_grain_id, target_logistics_id
    await client.connect()
    if not await client.is_user_authorized():
        qr_login = await client.qr_login()
        print(f"QR для входу: {qr_login.url}"); await qr_login.wait()

    async for dialog in client.iter_dialogs():
        if dialog.name == TARGET_GRAIN_GROUP_NAME: target_grain_id = dialog.id
        if dialog.name == TARGET_LOGISTICS_GROUP_NAME: target_logistics_id = dialog.id
    print("✅ Бот активний!"); await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
    except Exception as e:
        print(f"Помилка при запуску: {e}")

# 1. Автоматична установка бібліотек
!pip install telethon cryptg qrcode nest_asyncio

import re
import asyncio
import qrcode
import nest_asyncio
import os
import urllib.parse
from telethon import TelegramClient, events, errors, types
from telethon.tl.types import KeyboardButtonUrl

# Застосовуємо nest_asyncio для коректної роботи в Colab
nest_asyncio.apply()

# 2. Особисті дані
API_ID = 39693753
API_HASH = 'e227bd0afa19cb574427bcb2e77a11dc'

# Назви майданчиків
TARGET_GRAIN_GROUP_NAME = 'Агро-Культура'
TARGET_LOGISTICS_GROUP_NAME = 'Агро-Логістика'

target_grain_id = None
target_logistics_id = None
PROCESSED_MESSAGES = []

KEYWORDS_GRAIN = {
    'Пшениця': [r'пшениц\w*'],
    'Фураж': [r'фураж', r'кормов\w*'],
    'Соняшник': [r'соняшник\w*', r'подсолнух\w*', r'сеmechк\w*', r'семечек\b'],
    'Кукурудза': [r'кукурудз\w*', r'кукуруз\w*', r'кук\b'],
    'Ячмінь': [r'ячmen\w*', r'ячмін\w*'],
    'Ріпак': [r'ріпак\w*', r'рапс\w*'],
    'Горох': [r'горох\w*'],
    'Соя': [r'\bсоя\b', r'\bсою\b', r'\bсої\b', r'\bсое\w*'],
    'Просо': [r'\bпросо\b', r'\bпроса\b', r'\bпросу\b']
}

KEYWORDS_LOGISTICS = {
    'Порти / Елеватори': [r'порт\w*', r'элеватор\w*', r'ізмаїл', r'измаил', r'рені', r'рени', r'одес\w*', r'чорноморськ', r'черноморск', r'южн\w*', r'тиса', r'силос\w*'],
    'Зерновози / Самоскиди': [r'зерновоз\w*', r'самосвал\w*', r'самоскид\w*', r'сцепк\w*', r'зчепк\w*', r'тенда\w*', r'штора\w*', r'контейнеровоз\w*', r'тягач\w*', r'камаз\w*'],
    'Регіони / Маршрути': [r'\bобл\b', r'район\w*', r'київ\w*', r'полтав\w*', r'черкас\w*', r'винниц\w*', r'вінниц\w*', r'кіровоград\w*', r'кропивн\w*', r'дніпро\w*', r'днепр\w*', r'миколаї\w*', r'николае\w*', r'умань\w*', r'львів\w*']
}

ALLOWED_CHATS = []
SESSION_NAME = 'agro_super_combo_v40'

client = TelegramClient(
    SESSION_NAME,
    API_ID,
    API_HASH,
    device_model='POCO F5 Pro',
    system_version='Android 13',
    app_version='10.1.3',
    lang_code='uk'
)

def extract_price(text):
    text_lower = text.lower()
    price_pattern = r'(\d[\d\s]*)\s*(?:грн/т|грн|грн\.|usd|\$|💸)'
    match = re.search(price_pattern, text_lower)
    if match:
        return f"{match.group(1).strip()} грн/валюта"
    if 'ф1' in text_lower or 'ф-1' in text_lower or 'пдв' in text_lower:
        return "Договірна (Ф1 з ПДВ)"
    if 'ф2' in text_lower or 'ф-2' in text_lower or 'нал' in text_lower or 'готівка' in text_lower:
        return "Договірна (Ф2 / Готівка)"
    return "Не вказана (Договірна)"

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global target_grain_id, target_logistics_id, PROCESSED_MESSAGES
    try:
        if event.is_private or not event.text:
            return

        if (target_grain_id and event.chat_id == target_grain_id) or (target_logistics_id and event.chat_id == target_logistics_id):
            return

        if ALLOWED_CHATS:
            chat = await event.get_chat()
            if chat.id not in ALLOWED_CHATS and getattr(chat, 'username', None) not in ALLOWED_CHATS:
                return

        text_lower = event.text.lower()
        clean_text = " ".join(text_lower.split())

        if clean_text in PROCESSED_MESSAGES:
            return

        # 🛑 1. СУВОРИЙ ФІЛЬТР СПАМУ І СМІТТЯ (Блокує лише нецільові теми)
        trash_triggers = [
            'курс валют', 'актуальний курс', 'обмін валют', 'доллар', 'евро', 'usdt',
            'уборка', 'прибирання', 'посудомойка', 'посудомийниця', 'офіціант', 'ресторан', 
            'вакансія', 'робота в офісі', 'прогноз wef', 'економіку', 'форум', 'новости', 'новини',
            'олія', 'олію', 'масло соев', 'масло подсолнеч', 'жмих', 'шрот', 'макух', 'борошно', 'мука',
            'ищем:', 'шукаємо:', 'оператор', 'холодные звонки', 'менеджер по сделкам', 'график 5/2',
            'выплаты еженедельно', 'iqos friendly', 'приведи друга', 'офис в центре', 'жилье сразу'
        ]
        if any(trash in text_lower for trash in trash_triggers):
            return

        send_to_grain = False
        send_to_logistics = False
        logistics_type = None 
        found_grain_tags = []
        found_log_tags = []

        # 🚛 2. ТОЧНИЙ ФІЛЬТР ЛОГІСТИКИ (Потрібен транспорт + маршрут/об'єми)
        transport_words = [
            'зерновоз', 'самосвал', 'самоскид', 'сцепк', 'зчепк', 'тенда', 'штора', 'контейнеровоз',
            'потрібні авто', 'требуются авто', 'нужны машины', 'треба авто', 'вільні машини', 'свободные машины',
            'фрахт', 'шукаю завантаження', 'ищу загрузку', 'потрібен транспорт', 'требуется транспорт'
        ]
        
        route_words = [
            'завантаження', 'погрузка', 'вивантаження', 'выгрузка', 'маршрут', 'напрямок', 
            'направление', 'доставка', 'перевезення', 'рейс', 'ст. ', 'станція', 'ж/д',
            '➔', '→', '->', '=>', '—'
        ]

        has_transport = any(tw in text_lower for tw in transport_words)
        has_route = any(rw in text_lower for rw in route_words)

        driver_triggers = ['вільне авто', 'свободное авто', 'вільна машина', 'свободная машина', 'шукаю фрахт', 'ищу фрахт']
        
        if has_transport and has_route:
            send_to_logistics = True
            logistics_type = 'cargo'
            if any(dt in text_lower for dt in driver_triggers):
                logistics_type = 'driver'

        # 🌾 3. ПЕРЕВІРКА НА ЗЕРНОВІ (Якщо це не транспортна заявка)
        if not send_to_logistics:
            for category, regex_list in KEYWORDS_GRAIN.items():
                for regex in regex_list:
                    if re.search(regex, text_lower):
                        found_grain_tags.append(category)
                        break
            
            if found_grain_tags:
                trade_triggers = [
                    'куплю', 'закуп', 'закупаем', 'закуповуємо', 'купимо', 'потребность', 'потреба', 
                    'приймаємо', 'принимаем', 'закуповує', 'продам', 'продаю', 'реализуем', 'реалізуємо', 
                    'пропонуємо', 'предлагаем', 'в наличии', 'в наявності', 'тн', 'тонн', 'цена', 'ціна'
                ]
                if any(trade_word in text_lower for trade_word in trade_triggers):
                    send_to_grain = True

        # 📨 4. ВІДПРАВКА
        if send_to_logistics or send_to_grain:
            PROCESSED_MESSAGES.append(clean_text)
            if len(PROCESSED_MESSAGES) > 150:
                PROCESSED_MESSAGES.pop(0)

            sender = await event.get_sender()
            if sender and getattr(sender, 'username', None):
                sender_username = f"@{sender.username}"
                contact_button_url = f"https://t.me/{sender.username}"
            elif sender:
                sender_username = f"Прихований (ID: {sender.id})"
                contact_button_url = f"tg://user?id={sender.id}"
            else:
                sender_username = "Невідомий"
                contact_button_url = None

            phone_pattern = r'(\+?\d{1,3}\s?\(?\d{2,3}\)?\s?\d{3,4}[\s-]?\d{2}[\s-]?\d{2}|\b0\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b)'
            found_phones = re.findall(phone_pattern, event.text)
            phone_str = ", ".join(set(found_phones)) if found_phones else "Не вказано"

            detected_price = extract_price(event.text)
            share_text = urllib.parse.quote(f"Знайшов актуальну заявку:\n\n{event.text}")
            share_url = f"https://t.me/share/url?url={share_text}"

            inline_buttons = []
            row = []
            if contact_button_url:
                row.append(KeyboardButtonUrl(text="🟢 Написати", url=contact_button_url))
            row.append(KeyboardButtonUrl(text="↪️ Поділитися", url=share_url))
            inline_buttons.append(row)

            # В Логістику
            if send_to_logistics:
                if not target_logistics_id:
                    return
                
                for category, regex_list in KEYWORDS_LOGISTICS.items():
                    for regex in regex_list:
                        if re.search(regex, text_lower):
                            found_log_tags.append(category)
                            break
                tags_str = ", ".join(found_log_tags) if found_log_tags else "Транспорт"
                
                if logistics_type == 'driver':
                    header = "🚛 🟢 **ВІЛЬНИЙ ТРАНСПОРТ / ВОДІЙ ШУКАЄ ВАНТАЖ**"
                    role_label = "✍ Водій / Перевізник:"
                    loc_label = "📋 Базування / Напрямок:"
                    price_label = "💰 Бажаний фрахт:"
                else:
                    header = "📦 🔴 **НОВА ЗАЯВКА: ПОТРІБЕН ТРАНСПОРТ (ВАНТАЖ)**"
                    role_label = "✍ Замовник / Диспетчер:"
                    loc_label = "📋 Маршрут / Напрямок:"
                    price_label = "💰 Пропонований фрахт:"

                report = (
                    f"{header}\n\n"
                    f"{loc_label} {tags_str}\n"
                    f"{price_label} `{detected_price}`\n"
                    f"{role_label} {sender_username}\n"
                    f"📞 **Телефон:** `{phone_str}`\n"
                    f"───────────────────\n"
                    f"💬 **Текст оголошення:**\n\n{event.text}"
                )
                await client.send_message(target_logistics_id, report, buttons=inline_buttons)

            # В Зернові
            elif send_to_grain:
                if not target_grain_id:
                    return
                report = (
                    f"🌾 📢 **АКТУАЛЬНА ПРОПОЗИЦІЯ / ЗАКУПІВЛЯ ЗЕРНА**\n\n"
                    f"📋 **Культура:** {', '.join(found_grain_tags)}\n"
                    f"💰 **Орієнтовна ціна:** `{detected_price}`\n"
                    f"✍ **Контакт:** {sender_username}\n"
                    f"📞 **Телефон:** `{phone_str}`\n"
                    f"───────────────────\n"
                    f"💬 **Текст оголошення:**\n\n{event.text}"
                )
                await client.send_message(target_grain_id, report, buttons=inline_buttons)

    except Exception as e:
        print(f"Внутрішня помилка в обробнику: {e}")

async def main():
    global target_grain_id, target_logistics_id

    print("[1/3] Підключення до серверів Telegram...")
    await client.connect()

    if not await client.is_user_authorized():
        print("\n=== ВХОД ПО QR-КОДУ ===")
        qr_login = await client.qr_login()
        qr = qrcode.QRCode()
        qr.add_data(qr_login.url)
        print("\n👇 ВІДЗСКАНУЙТЕ ЦЕЙ КОД КАМЕРОЮ TELEGRAM:")
        qr.print_ascii(invert=True)
        print("=========================================\n")
        try:
            await qr_login.wait()
        except errors.SessionPasswordNeededError:
            password = input("Введіть хмарний пароль 2FA: ")
            await client.sign_in(password=password)

    print(f"\n[2/3] Пошук ваших майданчиків на акаунті...")
    async for dialog in client.iter_dialogs():
        if dialog.name == TARGET_GRAIN_GROUP_NAME:
            target_grain_id = dialog.id
            print(f"✅ Знайдено чат ЗЕРНА: '{TARGET_GRAIN_GROUP_NAME}' (ID: {target_grain_id})")
        elif dialog.name == TARGET_LOGISTICS_GROUP_NAME:
            target_logistics_id = dialog.id
            print(f"✅ Знайдено канал ЛОГІСТИКИ: '{TARGET_LOGISTICS_GROUP_NAME}' (ID: {target_logistics_id})")

    print(f"\n[3/3] ФІНАЛ! Оновлений бот успішно запущений.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    client.loop.run_until_complete(main())

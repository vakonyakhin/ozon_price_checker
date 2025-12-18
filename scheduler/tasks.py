import asyncio
from aiogram import Bot
from collections import defaultdict
from tabulate import tabulate
from typing import Optional
from urllib.parse import urlparse

from config import settings
from storage.sqlite_client import get_all_tracked_urls
from parser.price_parser import get_price

async def start_scheduler(bot: Bot):
    """
    Основной цикл планировщика, который запускает проверки цен.
    """
    print("Планировщик запущен...")
    while True:
        try:
            tracked_items = await get_all_tracked_urls()
            print(f"Найдено {len(tracked_items)} URL для проверки.")

            if not tracked_items:
                print(f"Нет активных URL. Следующая проверка через {settings.PRICE_CHECK_INTERVAL} секунд.")
                await asyncio.sleep(settings.PRICE_CHECK_INTERVAL)
                continue

            # 1. Группируем задачи по user_id
            user_tasks = defaultdict(list)
            for user_id, url, product_name, target_price in tracked_items:
                user_tasks[user_id].append({
                    "url": url,
                    "product_name": product_name,
                    "target_price": target_price
                })
            
            print(f"Задачи сгруппированы для {len(user_tasks)} пользователей.")

            # 2. Обрабатываем задачи для каждого пользователя
            for user_id, items in user_tasks.items():
                # Запускаем отдельную задачу для каждого пользователя, чтобы не блокировать основной цикл
                asyncio.create_task(process_user_items(bot, user_id, items))

            print(f"Все задачи для пользователей созданы. Ожидаю {settings.PRICE_CHECK_INTERVAL} секунд...")
            await asyncio.sleep(settings.PRICE_CHECK_INTERVAL)

        except Exception as e:
            print(f"Произошла ошибка в планировщике: {e}")
            await asyncio.sleep(60)


async def process_user_items(bot: Bot, user_id: int, items: list):
    """
    Проверяет все товары для одного пользователя и отправляет единое уведомление.
    """
    print(f"[{user_id}] Начинаю проверку {len(items)} товаров...")
    notifications = []

    for item in items:
        url = item['url']
        product_name = item['product_name']
        target_price = item['target_price']

        price, _ = await get_price(url)

        if price is None:
            print(f"[{user_id}] Не удалось получить цену для {url}")
            continue
        
        hostname = urlparse(url).hostname
        site_name = "Unknown"
        if hostname and 'ozon.ru' in hostname:
            site_name = "Ozon"
        elif hostname and 'wildberries.ru' in hostname:
            site_name = "Wildberries"


        # Условие для уведомления: цена ниже целевой или целевая цена не задана
        if target_price is None or price <= target_price:
            notification_item = {
                "product_name": product_name or url,
                "price": int(price),
                "site": site_name,
            }
            if target_price is not None:
                notification_item["target_price"] = int(target_price)
            notifications.append(notification_item)
    
    if not notifications:
        print(f"[{user_id}] Нет товаров, по которым нужно уведомление.")
        return

    # Формируем и отправляем единое сообщение
    try:
        header = "✨ Обновление цен по отслеживаемым товарам!"
        table_data = []
        headers = ["Название", "Сайт", "Цена", "Цель"]
        for notif in notifications:
            target_price_str = f"{notif['target_price']} ₽" if 'target_price' in notif else "не задана"
            table_data.append([notif['product_name'], notif['site'], f"{notif['price']} ₽", target_price_str])
        
        table = tabulate(table_data, headers, tablefmt="plain", maxcolwidths=[35, 12, None, None])
        
        message_text = f"{header}\n\n<pre>{table}</pre>"

        await bot.send_message(
            chat_id=user_id,
            text=message_text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        print(f"[{user_id}] Отправлено сводное уведомление по {len(notifications)} товарам.")
    except Exception as e:
        print(f"[{user_id}] Не удалось отправить сводное сообщение: {e}")

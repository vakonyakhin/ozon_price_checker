import asyncio
from aiogram import Bot
from collections import defaultdict
from datetime import datetime, timedelta
import html
from typing import Optional
from urllib.parse import urlparse

from config import settings
from storage.sqlite_client import get_all_tracked_urls, get_all_user_settings, update_user_last_check, add_price_history, cleanup_old_price_history
from parser.price_parser import get_price

async def start_scheduler(bot: Bot):
    """
    Основной цикл планировщика, который запускает проверки цен.
    """
    print("Планировщик запущен...")
    while True:
        try:
            # Очистка старой истории цен (старше 7 дней)
            await cleanup_old_price_history()

            tracked_items = await get_all_tracked_urls()
            # print(f"Найдено {len(tracked_items)} URL для проверки.")

            if not tracked_items:
                # Если нет URL, просто ждем минуту
                pass

            # 1. Группируем задачи по user_id
            user_tasks = defaultdict(list)
            for user_id, url, product_name, target_price in tracked_items:
                user_tasks[user_id].append({
                    "url": url,
                    "product_name": product_name,
                    "target_price": target_price
                })
            
            # Получаем настройки всех пользователей
            all_settings = await get_all_user_settings()
            default_interval = settings.PRICE_CHECK_INTERVAL // 60
            now = datetime.now()

            # 2. Обрабатываем задачи для каждого пользователя
            for user_id, items in user_tasks.items():
                user_data = all_settings.get(user_id, {})
                interval = user_data.get("check_interval") or default_interval
                last_check_raw = user_data.get("last_check")
                
                should_run = False
                if not last_check_raw:
                    should_run = True
                else:
                    try:
                        # Парсим дату из строки (формат SQLite)
                        if isinstance(last_check_raw, str):
                            last_check = datetime.fromisoformat(last_check_raw)
                        else:
                            last_check = last_check_raw
                        
                        if now >= last_check + timedelta(minutes=interval):
                            should_run = True
                    except Exception as e:
                        print(f"Ошибка даты для {user_id}: {e}")
                        should_run = True

                if should_run:
                    asyncio.create_task(process_user_items(bot, user_id, items))
                    await update_user_last_check(user_id)

            # Проверка каждую минуту
            await asyncio.sleep(60)

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

        price, _, _ = await get_price(url)

        if price is None:
            print(f"[{user_id}] Не удалось получить цену для {url}")
            continue

        # Сохраняем историю цен, если товар в наличии
        if price != -1:
            await add_price_history(url, price)
        
        if price == -1:
            # Товар закончился, пропускаем уведомление
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
                "url": url,
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
        response_lines = [header, ""]

        for notif in notifications:
            site = notif['site']
            site_icon = "🔵" if site == "Ozon" else "🟣"
            
            price_str = f"{notif['price']} ₽"
            if 'target_price' in notif:
                price_str += f" (цель: {notif['target_price']} ₽)"

            card = f"{site_icon} <b>{site}</b> | <a href=\"{notif['url']}\">{html.escape(notif['product_name'])}</a>\n💰 {price_str}"
            response_lines.append(card)
            response_lines.append("─" * 20)

        if response_lines and response_lines[-1] == "─" * 20:
            response_lines.pop()

        message_text = "\n".join(response_lines)

        await bot.send_message(
            chat_id=user_id,
            text=message_text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        print(f"[{user_id}] Отправлено сводное уведомление по {len(notifications)} товарам.")
    except Exception as e:
        print(f"[{user_id}] Не удалось отправить сводное сообщение: {e}")

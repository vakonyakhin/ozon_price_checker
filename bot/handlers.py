from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from tabulate import tabulate
from urllib.parse import urlparse
import html
import re

from storage.sqlite_client import add_item_for_user, get_urls_for_user, remove_item_by_rowid, get_users_statistics
from parser.price_parser import get_price

# Создаем роутер для обработчиков
router = Router()

SUPPORTED_HOSTS = {
    "ozon.ru": "ozon_items",
    "www.ozon.ru": "ozon_items",
    "m.ozon.ru": "ozon_items",
    "wildberries.ru": "wb_items",
    "www.wildberries.ru": "wb_items",
    "m.wildberries.ru": "wb_items",
}

class DeleteCallback(CallbackData, prefix="del"):
    table: str
    rowid: int


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start."""
    await message.answer(
        "👋 Привет! Я бот для отслеживания цен на Ozon и Wildberries.\n\n"
        "Просто отправь мне ссылку на товар, и я буду проверять цену каждые 10 минут.\n"
        "Вы также можете указать желаемую цену, и я уведомлю вас, когда цена станет ниже или равна ей.\n"
        "Например: `https://ozon.ru/t/Abc1234 1000.50`\n\n"
        "Доступные команды:\n"
        "/list - показать список отслеживаемых товаров\n"
        "/stop_tracking - прекратить отслеживание товара"
    )

@router.message(Command("summary"))
async def cmd_summary(message: Message):
    """Обработчик команды /summary для администратора."""
    if message.from_user.id != 1608118454:
        return

    stats = await get_users_statistics()
    if not stats:
        await message.answer("Нет данных для отображения.")
        return

    headers = ["ID", "Кол-во", "Дата"]
    table_data = []
    for user_id, count, last_added in stats:
        date_str = str(last_added).split('.')[0] if last_added else "-"
        table_data.append([user_id, count, date_str])

    await message.answer(f"<pre>{tabulate(table_data, headers, tablefmt='plain')}</pre>", parse_mode="HTML")

@router.message(Command("list"))
async def cmd_list(message: Message):
    """Обработчик команды /list."""
    user_id = message.from_user.id
    tracked_items = await get_urls_for_user(user_id)
    if not tracked_items:
        await message.answer("У вас нет отслеживаемых товаров.")
        return

    processing_message = await message.answer("🔄 Собираю актуальные цены, это может занять до минуты...")

    items_data = []

    for rowid, url, saved_product_name, target_price, table_name in tracked_items:
        # Получаем актуальную цену и название
        current_price, current_product_name, _ = await get_price(url)

        # Используем сохраненное имя, если актуальное не получено
        display_name = current_product_name or saved_product_name
        # Если оба отсутствуют, используем укороченный URL
        if not display_name:
            display_name = url.split("?")[0]
            if len(display_name) > 40:
                display_name = display_name[:37] + "..."


        if current_price == -1:
            price_info = "Нет в наличии"
        else:
            price_info = f"{int(current_price)} ₽" if current_price is not None else "Ошибка"

        # Добавляем информацию о целевой цене
        if target_price is not None:
            price_info += f" (цель: {int(target_price)} ₽)"

        site_name = "Ozon" if "ozon" in table_name else "WB"
        items_data.append((site_name, display_name, price_info, url))

    if not items_data:
        await processing_message.edit_text("Не удалось получить информацию ни по одному товару.")
        return

    # Формируем список карточек (без тега <pre>, чтобы ссылки работали корректно)
    response_lines = []
    for site, name, price, url in items_data:
        site_icon = "🔵" if site == "Ozon" else "🟣"
        
        # Формат: Иконка Сайт | Название (ссылка)
        #         Цена
        card = f"{site_icon} <b>{site}</b> | <a href=\"{url}\">{html.escape(name)}</a>\n💰 {price}"
        
        response_lines.append(card)
        response_lines.append("─" * 20)  # Разделитель

    # Убираем последний разделитель
    if response_lines:
        response_lines.pop()

    response_text = "\n".join(response_lines)
    await processing_message.edit_text(response_text, parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("stop_tracking"))
async def cmd_stop_tracking(message: Message):
    """Обработчик команды /stop_tracking для интерактивного удаления."""
    user_id = message.from_user.id
    tracked_items = await get_urls_for_user(user_id)

    if not tracked_items:
        await message.answer("У вас нет отслеживаемых товаров для удаления.")
        return

    builder = InlineKeyboardBuilder()
    for rowid, url, product_name, target_price, table_name in tracked_items:
        display_name = product_name
        if not display_name:
            display_name = url.split("?")[0]
            if len(display_name) > 50:
                display_name = display_name[:47] + "..."
        
        builder.row(
            InlineKeyboardButton(
                text=f"❌ {display_name}",
                callback_data=DeleteCallback(table=table_name, rowid=rowid).pack()
            )
        )
    
    await message.answer(
        "Выберите, какой товар вы хотите удалить из отслеживания:",
        reply_markup=builder.as_markup()
    )

@router.callback_query(DeleteCallback.filter())
async def handle_delete_callback(query: CallbackQuery, callback_data: DeleteCallback):
    """Обработчик нажатия на кнопку удаления товара."""
    table = callback_data.table
    rowid = callback_data.rowid

    await remove_item_by_rowid(rowid, table)
    
    await query.answer("Товар удален!")
    
    # Обновляем сообщение, удаляя клавиатуру
    await query.message.edit_text("Товар был удален из списка отслеживания.")


@router.message(lambda m: re.search(r"https?://", m.text or m.caption or ""))
async def handle_product_url(message: Message):
    """Обработчик сообщений, содержащих URL Ozon или Wildberries."""
    user_id = message.from_user.id
    text = message.text or message.caption

    # Ищем URL в тексте
    url_match = re.search(r"(https?://[^\s]+)", text)
    if not url_match:
        await handle_other_messages(message)
        return

    url = url_match.group(1).rstrip(".,;!?")
    
    hostname = urlparse(url).hostname
    if not hostname or hostname not in SUPPORTED_HOSTS:
        await handle_other_messages(message)
        return

    table_name = SUPPORTED_HOSTS[hostname]
    
    target_price = None
    # Проверяем наличие целевой цены после ссылки
    post_url_text = text[url_match.end():].strip()
    if post_url_text:
        parts = post_url_text.split()
        try:
            target_price = float(parts[0].replace(',', '.'))
        except ValueError:
            pass

    processing_message = await message.answer("🔍 Проверяю ссылку и получаю текущую цену...")

    price, product_name, promo_text = await get_price(url)

    if price == -1:
        await processing_message.edit_text("Данного товара нет в наличии.")
        return

    if price is not None and product_name is not None:
        await add_item_for_user(user_id, url, product_name, table_name, target_price)
        response_text = (
            f"✅ Цена успешно получена!\n"
            f"Текущая цена для '{product_name}': {int(price)} ₽\n"
        )
        if promo_text:
            response_text += f"🔥 {promo_text}\n"
        
        response_text += "\n"
        if target_price is not None:
            response_text += f"Я начну отслеживать цену этого товара и уведомлю вас, когда она достигнет {int(target_price)} ₽."
        else:
            response_text += "Я начну отслеживать цену этого товара."
        
        await processing_message.edit_text(response_text)
    else:
        await processing_message.edit_text(
            "❌ Не удалось получить цену или название для этой ссылки. "
            "Возможно, страница товара недоступна или имеет нестандартную структуру. "
            "Попробуйте другую ссылку."
        )

@router.message()
async def handle_other_messages(message: Message):
    """Обработчик для всех остальных сообщений."""
    await message.answer("Пожалуйста, отправьте мне корректную ссылку на товар с сайта Ozon.ru или Wildberries.ru.")

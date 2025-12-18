import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from config import settings
from bot.handlers import router as main_router
from scheduler.tasks import start_scheduler
from storage.sqlite_client import initialize_db


async def set_main_menu(bot: Bot):
    """Создает кнопку меню с основными командами."""
    main_menu_commands = [
        BotCommand(command="/start", description="🏁 Перезапустить бота"),
        BotCommand(command="/list", description="📜 Показать список товаров"),
        BotCommand(command="/stop_tracking", description="🗑️ Удалить товар"),
    ]
    await bot.set_my_commands(main_menu_commands)


async def main():
    """Основная функция для запуска бота с корректной обработкой завершения."""

    # Инициализация базы данных
    await initialize_db()

    # Настройка логирования
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # Инициализация бота и диспетчера
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()

    # Устанавливаем меню
    await set_main_menu(bot)

    # Подключение роутера
    dp.include_router(main_router)

    # Запуск фоновой задачи планировщика
    scheduler_task = asyncio.create_task(start_scheduler(bot))

    logging.info("Запуск бота...")
    try:
        await dp.start_polling(bot)
    finally:
        logging.info("Остановка бота...")
        
        # Отменяем задачу планировщика
        scheduler_task.cancel()
        
        # Ожидаем завершения задачи (она может вызвать CancelledError)
        try:
            await scheduler_task
        except asyncio.CancelledError:
            logging.info("Задача планировщика успешно отменена.")
            
        # Корректно закрываем сессию бота
        if bot.session:
            await bot.session.close()
        
        logging.info("Сессия бота закрыта.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот был остановлен пользователем.")

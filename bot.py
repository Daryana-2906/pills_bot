import logging
import psycopg2
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import asyncio
import threading
import time
import os
from urllib.parse import urlparse
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
MEDICINE_NAME, DOSAGE, TIME, FREQUENCY = range(4)

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в переменных окружения")

# Функция для получения подключения к БД
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    
    if database_url:
        try:
            # Подключаемся к облачной БД на Railway
            conn = psycopg2.connect(database_url, sslmode='require')
            logger.info("Успешное подключение к облачной PostgreSQL")
            return conn
        except Exception as e:
            logger.error(f"Ошибка подключения к облачной БД: {e}")
            raise
    else:
        # Локальная разработка (только для тестирования)
        logger.info("Использую локальную БД для разработки")
        return psycopg2.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            database=os.getenv('DB_NAME', 'medications_bot'),
            user=os.getenv('DB_USER', 'postgres'), 
            password=os.getenv('DB_PASSWORD', 'password'),
            port=os.getenv('DB_PORT', '5432')
        )

# Инициализация базы данных
def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS medications (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                medicine_name TEXT,
                dosage TEXT,
                time TEXT,
                frequency TEXT,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON medications(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_time ON medications(time)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_active ON medications(active)')
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована успешно")
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")


# Функция для получения подключения к БД
def get_db_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        logger.error(f"Ошибка подключения к базе данных: {e}")
        raise

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    keyboard = [['Добавить лекарство', 'Мои лекарства'], ['Удалить лекарство']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f'Привет, {user.first_name}! Я бот для напоминаний о приеме лекарств.\n\n'
        'Выберите действие:',
        reply_markup=reply_markup
    )

# Начало добавления лекарства
async def add_medicine_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Введите название лекарства:')
    return MEDICINE_NAME

# Получение названия лекарства
async def get_medicine_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['medicine_name'] = update.message.text
    await update.message.reply_text('Введите дозировку (например: 1 таблетка, 10мг):')
    return DOSAGE

# Получение дозировки
async def get_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['dosage'] = update.message.text
    await update.message.reply_text('Введите время приема в формате ЧЧ:ММ (например: 09:00):')
    return TIME

# Получение времени
async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_str = update.message.text
    try:
        # Проверка формата времени
        datetime.strptime(time_str, '%H:%M')
        context.user_data['time'] = time_str
        await update.message.reply_text(
            'Выберите частоту приема:\n'
            '1 - Каждый день\n'
            '2 - Только сегодня\n'
            '3 - По рабочим дням\n'
            '4 - По выходным'
        )
        return FREQUENCY
    except ValueError:
        await update.message.reply_text('Неверный формат времени. Введите время в формате ЧЧ:ММ:')
        return TIME

# Получение частоты и сохранение в БД
async def get_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    frequency_choice = update.message.text
    frequency_map = {
        '1': 'daily',
        '2': 'once',
        '3': 'weekdays',
        '4': 'weekends'
    }
    
    frequency = frequency_map.get(frequency_choice, 'daily')
    context.user_data['frequency'] = frequency
    
    # Сохранение в базу данных
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO medications (user_id, medicine_name, dosage, time, frequency)
            VALUES (%s, %s, %s, %s, %s)
        ''', (
            update.message.from_user.id,
            context.user_data['medicine_name'],
            context.user_data['dosage'],
            context.user_data['time'],
            frequency
        ))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f'Лекарство добавлено!\n'
            f'Название: {context.user_data["medicine_name"]}\n'
            f'Дозировка: {context.user_data["dosage"]}\n'
            f'Время: {context.user_data["time"]}\n'
            f'Частота: {frequency}'
        )
        
    except Exception as e:
        logger.error(f"Ошибка при добавлении лекарства: {e}")
        await update.message.reply_text('Произошла ошибка при добавлении лекарства. Попробуйте позже.')
    
    return ConversationHandler.END

# Отмена диалога
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Действие отменено.')
    return ConversationHandler.END

# Показать все лекарства пользователя
async def show_medicines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT medicine_name, dosage, time, frequency FROM medications 
            WHERE user_id = %s AND active = TRUE
            ORDER BY time
        ''', (user_id,))
        
        medicines = cursor.fetchall()
        conn.close()
        
        if not medicines:
            await update.message.reply_text('У вас нет активных напоминаний о лекарствах.')
            return
        
        message = "Ваши лекарства:\n\n"
        for i, (name, dosage, time, freq) in enumerate(medicines, 1):
            frequency_text = {
                'daily': 'каждый день',
                'once': 'только сегодня',
                'weekdays': 'по рабочим дням',
                'weekends': 'по выходным'
            }.get(freq, 'каждый день')
            
            message += f"{i}. {name}\n   Дозировка: {dosage}\n   Время: {time}\n   Частота: {frequency_text}\n\n"
        
        await update.message.reply_text(message)
    
    except Exception as e:
        logger.error(f"Ошибка при получении списка лекарств: {e}")
        await update.message.reply_text('Произошла ошибка при получении списка лекарств.')

# Удаление лекарств
async def delete_medicine_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, medicine_name, dosage, time FROM medications 
            WHERE user_id = %s AND active = TRUE
            ORDER BY time
        ''', (user_id,))
        
        medicines = cursor.fetchall()
        conn.close()
        
        if not medicines:
            await update.message.reply_text('У вас нет активных напоминаний о лекарствах.')
            return
        
        message = "Выберите номер лекарства для удаления:\n\n"
        for i, (med_id, name, dosage, time) in enumerate(medicines, 1):
            message += f"{i}. {name} - {dosage} в {time}\n"
            context.user_data[f'med_{i}'] = med_id
        
        context.user_data['medicines_count'] = len(medicines)
        await update.message.reply_text(message)
        
        return "DELETE"
    
    except Exception as e:
        logger.error(f"Ошибка при получении списка лекарств для удаления: {e}")
        await update.message.reply_text('Произошла ошибка при получении списка лекарств.')
        return ConversationHandler.END

async def delete_medicine_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        choice = int(update.message.text)
        if 1 <= choice <= context.user_data['medicines_count']:
            med_id = context.user_data[f'med_{choice}']
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM medications WHERE id = %s', (med_id,))
            conn.commit()
            conn.close()
            
            await update.message.reply_text('Лекарство удалено!')
        else:
            await update.message.reply_text('Неверный номер. Попробуйте снова.')
            return "DELETE"
    except ValueError:
        await update.message.reply_text('Пожалуйста, введите номер:')
        return "DELETE"
    except Exception as e:
        logger.error(f"Ошибка при удалении лекарства: {e}")
        await update.message.reply_text('Произошла ошибка при удалении лекарства.')
    
    return ConversationHandler.END

# Обработчик текстовых сообщений (для кнопок)
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == 'Добавить лекарство':
        return await add_medicine_start(update, context)
    elif text == 'Мои лекарства':
        return await show_medicines(update, context)
    elif text == 'Удалить лекарство':
        return await delete_medicine_start(update, context)
    else:
        await update.message.reply_text('Пожалуйста, выберите действие из меню ниже.')

# Функция для отправки уведомлений (синхронная версия)
def send_notifications_sync():
    """Синхронная версия функции отправки уведомлений"""
    logger.info("Сервис уведомлений запущен")
    
    while True:
        try:
            current_time = datetime.now().strftime('%H:%M')
            current_weekday = datetime.now().weekday()
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT user_id FROM medications 
                WHERE time = %s AND active = TRUE
            ''', (current_time,))
            
            users = cursor.fetchall()
            
            for (user_id,) in users:
                cursor.execute('''
                    SELECT id, medicine_name, dosage, frequency FROM medications 
                    WHERE user_id = %s AND time = %s AND active = TRUE
                ''', (user_id, current_time))
                
                medicines = cursor.fetchall()
                
                for med_id, medicine_name, dosage, frequency in medicines:
                    should_notify = False
                    
                    if frequency == 'daily':
                        should_notify = True
                    elif frequency == 'once':
                        should_notify = True
                        # После отправки деактивируем одноразовое напоминание
                        cursor.execute('UPDATE medications SET active = FALSE WHERE id = %s', (med_id,))
                    elif frequency == 'weekdays' and current_weekday < 5:
                        should_notify = True
                    elif frequency == 'weekends' and current_weekday >= 5:
                        should_notify = True
                    
                    if should_notify and application_instance:
                        try:
                            # Используем run_coroutine_threadsafe для отправки сообщения
                            future = asyncio.run_coroutine_threadsafe(
                                application_instance.bot.send_message(
                                    chat_id=user_id,
                                    text=f'⏰ Время принять лекарство!\n\n💊 {medicine_name}\n📏 Дозировка: {dosage}'
                                ),
                                application_instance._get_running_loop()
                            )
                            future.result(timeout=10)  # Ждем результат 10 секунд
                            logger.info(f"Уведомление отправлено пользователю {user_id}")
                        except Exception as e:
                            logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Ошибка в системе уведомлений: {e}")
        
        time.sleep(60)  # Проверка каждую минуту

# Запуск системы уведомлений в отдельном потоке
def start_notification_service():
    """Запуск сервиса уведомлений в отдельном потоке"""
    thread = threading.Thread(target=send_notifications_sync, daemon=True)
    thread.start()
    logger.info("Сервис уведомлений запущен в отдельном потоке")

def main():
    global application_instance
    
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application_instance = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики команд
    application_instance.add_handler(CommandHandler("start", start))
    application_instance.add_handler(CommandHandler("medicines", show_medicines))
    application_instance.add_handler(CommandHandler("help", start))
    
    # ConversationHandler для добавления лекарства
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & filters.Regex('^Добавить лекарство$'), add_medicine_start)],
        states={
            MEDICINE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_medicine_name)],
            DOSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_dosage)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
            FREQUENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_frequency)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    application_instance.add_handler(conv_handler)
    
    # ConversationHandler для удаления лекарства
    delete_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & filters.Regex('^Удалить лекарство$'), delete_medicine_start)],
        states={
            "DELETE": [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_medicine_finish)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    application_instance.add_handler(delete_handler)
    
    # Обработчик текстовых сообщений (для кнопок)
    application_instance.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    
    # Запуск системы уведомлений
    start_notification_service()
    
    # Запуск бота
    logger.info("Бот запускается...")
    application_instance.run_polling()

if __name__ == '__main__':
    main()

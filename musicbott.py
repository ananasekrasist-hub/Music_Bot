import telebot
import yt_dlp
import configparser
import logging
import time
import sys
import os
import re

# --- НАСТРОЙКА КОНФИГА И ЛОГИРОВАНИЯ ---
CONFIG_FILE = 'my_settings.ini'
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Чтение INI-файла
config = configparser.ConfigParser()
if not os.path.exists(CONFIG_FILE):
    # На Render файл my_settings.ini будет существовать,
    # но это полезная проверка для локального запуска
    logging.info(f"Загрузка конфигурации из '{CONFIG_FILE}'...")
    
config.read(CONFIG_FILE)

try:
    # Используем os.environ.get для получения данных из переменных среды Render
    # Это важно для безопасности токенов на хостинге
    TOKEN = os.environ.get('BOT_TOKEN', config['telegram']['token'])
    ADMIN_ID = int(os.environ.get('ADMIN_ID', config['telegram']['admin_id']))
    SEARCH_LIMIT = int(config['settings'].get('search_limit', 1)) 
except Exception as e:
    logging.error(f"Ошибка чтения данных из конфигурации. Ошибка: {e}")
    # Если на Render не удалось получить переменные, завершаем работу
    sys.exit(1)

# --- ИНИЦИАЛИЗАЦИЯ БОТА ---
bot = telebot.TeleBot(TOKEN)

# --- ФУНКЦИИ ---

def log_to_admin(message, query):
    # ... (функция log_to_admin остается без изменений)
    user_id = message.chat.id
    username = message.from_user.username if message.from_user.username else "нет ника"
    first_name = message.from_user.first_name if message.from_user.first_name else "Неизвестный"
    
    log_message = (
        f"🎶 **ЗАПРОС МУЗЫКИ** 🎶\n"
        f"├ Пользователь: {first_name} (@{username}) (ID: `{user_id}`)\n"
        f"└ Запрос: *{query}*"
    )
    
    try:
        bot.send_message(ADMIN_ID, log_message, parse_mode='Markdown')
        logging.info(f"Лог отправлен админу. Запрос: {query}")
    except Exception as e:
        logging.error(f"Не удалось отправить лог админу: {e}")
        
def search_and_download_music(query, chat_id):
    """
    Ищет, скачивает и отправляет первый найденный MP3 трек.
    """
    # На Render временные файлы лучше хранить в /tmp,
    # так как это единственное место, где гарантирована запись.
    temp_dir = '/tmp/temp_music' 
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        search_term = f"ytsearch1:{query}"
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'logtostderr': False,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(search_term, download=False)
            
            if 'entries' not in info_dict or not info_dict['entries']:
                return False

            video_info = info_dict['entries'][0]
            title = video_info.get('title', 'Unknown Title')
            
            artist = video_info.get('artist')
            if not artist:
                artist = video_info.get('uploader')
            if not artist:
                artist = None 
            
            # 2. Скачивание
            ydl.download([video_info['webpage_url']])
            
            # Находим имя файла
            original_filename = ydl.prepare_filename(video_info)
            base_filename = os.path.splitext(original_filename)[0]
            mp3_filename = base_filename + '.mp3'
            
            if not os.path.exists(mp3_filename):
                 files = os.listdir(temp_dir)
                 for f in files:
                     if f.endswith(".mp3"):
                         mp3_filename = os.path.join(temp_dir, f)
                         break

            if not os.path.exists(mp3_filename):
                logging.error(f"Файл MP3 не найден: {mp3_filename}")
                return False

            # 3. Отправка файла
            file_size_mb = os.path.getsize(mp3_filename) / (1024 * 1024)
            
            if file_size_mb > 50:
                 bot.send_message(chat_id, f"❌ Файл \"{title}\" слишком большой ({file_size_mb:.2f} MB).")
                 return False

            bot.send_audio(
                chat_id, 
                audio=open(mp3_filename, 'rb'),
                caption=f"🎵 Трек: <b>{title}</b>",
                title=title,
                performer=artist,
                parse_mode='HTML'
            )
            
            return True
            
    except Exception as e:
        if "ffmpeg" in str(e).lower():
            bot.send_message(chat_id, "❌ Ошибка: Не установлен FFmpeg на хостинге.", parse_mode='HTML')
        else:
            bot.send_message(chat_id, "❌ Ошибка при скачивании.", parse_mode='HTML')
        logging.error(f"Ошибка: {e}")
        return False
        
    finally:
        # 4. Очистка
        try:
            if os.path.exists(temp_dir):
                for f in os.listdir(temp_dir):
                    os.remove(os.path.join(temp_dir, f))
                os.rmdir(temp_dir)
        except Exception as e:
            logging.warning(f"Ошибка очистки: {e}")


# --- ОБРАБОТЧИКИ (без изменений) ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "👋 Привет! Я — бот-поисковик музыки.\n"
        "Просто <b>напиши мне название песни</b>, и я пришлю <b>MP3 файл</b>."
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode='HTML')

@bot.message_handler(content_types=['text'])
def handle_text_query(message):
    chat_id = message.chat.id
    query = message.text.strip()
    
    if not query or query.startswith('/'):
        return

    log_to_admin(message, query)

    msg_searching = bot.send_message(chat_id, f"🔍 Ищу и скачиваю <b>{query}</b>...", parse_mode='HTML')

    success = search_and_download_music(query, chat_id)
    
    try:
        bot.delete_message(chat_id, msg_searching.message_id) 
    except Exception:
        pass
    
    if success:
        bot.send_message(chat_id, "✅ MP3 успешно отправлен! 🎧", parse_mode='HTML')


# --- ЗАПУСК БОТА ---

if __name__ == '__main__':
    logging.info("Бот запущен. Начинаю polling...")
    try:
        bot.infinity_polling()
    except Exception as e:
        logging.error(f"Критическая ошибка бота: {e}")
import os
import re
import requests
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id

import google.generativeai as genai

# === ⚙️ ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
load_dotenv()

VK_TOKEN = os.getenv('VK_TOKEN')
VK_GROUP_ID = os.getenv('VK_GROUP_ID')

gemini_keys_str = os.getenv('GEMINI_API_KEYS', '')
GEMINI_API_KEYS = [key.strip() for key in gemini_keys_str.split(',') if key.strip()]

# === 🌐 НАСТРОЙКА ПРОКСИ ===
PROXY_URL = os.getenv('PROXY_URL')
if PROXY_URL:
    os.environ['HTTP_PROXY'] = PROXY_URL
    os.environ['HTTPS_PROXY'] = PROXY_URL
    print(f"[🌐] Успешно подключен прокси-сервер!")
else:
    print("[⚠️] ПРОКСИ НЕ УКАЗАН!")

if not VK_TOKEN or not VK_GROUP_ID or not GEMINI_API_KEYS:
    raise ValueError("❌ Ошибка: Убедитесь, что VK_TOKEN, VK_GROUP_ID и GEMINI_API_KEYS указаны в .env!")

# === 🤖 СПИСОК МОДЕЛЕЙ (СТРОГИЙ ПОРЯДОК ПЕРЕБОРА) ===
MODELS = [
    "gemini-3.1-pro-preview", 
    "gemini-3-flash-preview", 
    "gemini-3.1-flash-lite", 
    "gemini-2.5-pro", 
    "gemini-2.5-flash", 
    "gemini-2.5-flash-lite", 
    "gemini-2.0-flash",
    "gemini-1.5-pro", 
    "gemini-1.5-flash"
]

# === 🧠 СИСТЕМНЫЕ ПРОМПТЫ ===
MODES = {
    "programmer": (
        "Ты — Senior IT-разработчик. Твоя задача писать мощный, оптимизированный и чистый код. "
        "Особый упор делай на Python, JavaScript, HTML/CSS, создание ботов для VK и Telegram, "
        "а также разработку механик и скриптов в Roblox Studio. Отвечай как профи, решай сложные баги."
    ),
    "math": (
        "Ты — гениальный преподаватель математики. Тебе могут прислать фото тетради или школьной доски. "
        "Твоя цель — безошибочно решать уравнения и примеры, объясняя ход решения четко, шаг за шагом, "
        "без лишней философии."
    ),
    "project": (
        "Ты — академический наставник и эксперт по IT-проектам. Помогаешь генерировать идеи для стартапов, "
        "писать код для сложных систем (например, как ИИ-ассистент AlphaMentorAI). "
        "Помогаешь оформлять проектную документацию, презентации, аннотации и титульные листы по строгим стандартам "
        "(включая требования таких учебных заведений, как Государственное бюджетное профессиональное образовательное "
        "учреждение города Москвы 'Колледж информационных технологий 'ИТ.Москва')."
    ),
    "fast": (
        "Ты — быстрый, лаконичный и умный помощник. Пиши только суть, факты и конкретику. "
        "Никакой воды, долгих приветствий или лишних рассуждений. Решай жизненные вопросы мгновенно."
    )
}

user_states = {}

# === 🔧 ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def clean_markdown(text: str) -> str:
    """Удаляет звездочки и решетки для красивого отображения в VK."""
    if not text:
        return ""
    return re.sub(r'[*#]', '', text).strip()

def create_keyboard():
    """Создает клавиатуру с режимами."""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('👨‍💻 Режим программиста', color=VkKeyboardColor.PRIMARY, payload={"mode": "programmer"})
    keyboard.add_line()
    keyboard.add_button('🧮 Режим математики', color=VkKeyboardColor.PRIMARY, payload={"mode": "math"})
    keyboard.add_line()
    keyboard.add_button('📋 Режим проекта', color=VkKeyboardColor.PRIMARY, payload={"mode": "project"})
    keyboard.add_line()
    keyboard.add_button('⚡ Быстрый режим', color=VkKeyboardColor.POSITIVE, payload={"mode": "fast"})
    return keyboard.get_keyboard()

def get_image_from_attachment(attachment):
    """Скачивает фото из сообщения VK в формате пригодном для Gemini."""
    if attachment['type'] == 'photo':
        sizes = attachment['photo']['sizes']
        largest_photo = max(sizes, key=lambda x: x['width'] * x['height'])
        response = requests.get(largest_photo['url'])
        if response.status_code == 200:
            return Image.open(BytesIO(response.content))
    return None

# === 🛡️ ДВОЙНОЕ ЯДРО ИИ: КАСКАД ТОКЕНОВ И МОДЕЛЕЙ ===

def generate_with_fallback(contents, user_mode: str) -> str:
    """
    Двойной перебор: перебирает токены, а внутри каждого токена перебирает список моделей.
    """
    system_instruction = MODES.get(user_mode, MODES["fast"])

    for token_idx, api_key in enumerate(GEMINI_API_KEYS):
        # Настраиваем API на текущий токен
        genai.configure(api_key=api_key)
        
        for model_name in MODELS:
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_instruction
                )
                
                # Пытаемся получить ответ
                response = model.generate_content(contents)
                
                if response.text:
                    print(f"[✅] Успех! Токен №{token_idx + 1} | Модель: {model_name}")
                    return clean_markdown(response.text)
                    
            except Exception as e:
                # Ошибка конкретной модели на этом токене
                print(f"[⚠️] Ошибка (Токен №{token_idx + 1} | Модель {model_name}): {e}. Переключаюсь на следующую модель...")
                continue
                
        # Если ни одна модель не сработала на текущем токене
        print(f"[❌] Все {len(MODELS)} моделей на токене №{token_idx + 1} выдали ошибку. Переключаюсь на следующий токен...")
            
    # Если цикл завершился и вообще ничего не сработало
    print("[☠️] КРИТИЧЕСКАЯ ОШИБКА: Ни один токен и ни одна модель не сработали!")
    return None

# === 🚀 ОСНОВНАЯ ЛОГИКА БОТА ===

def main():
    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    longpoll = VkBotLongPoll(vk_session, group_id=VK_GROUP_ID)
    
    print(f"[✅] Бот запущен! Токенов: {len(GEMINI_API_KEYS)} | Моделей в пуле: {len(MODELS)}")

    for event in longpoll.listen():
        if event.type == VkBotEventType.MESSAGE_NEW:
            msg = event.object.message
            user_id = msg['from_id']
            text = msg['text']
            
            if user_id not in user_states:
                user_states[user_id] = "fast"
                
            # Обработка кнопок
            mode_messages = {
                '👨‍💻 Режим программиста': ("programmer", "Вы переключились в 👨‍💻 Режим программиста. Жду задачи!"),
                '🧮 Режим математики': ("math", "Вы переключились в 🧮 Режим математики. Отправьте пример или фото."),
                '📋 Режим проекта': ("project", "Вы переключились в 📋 Режим проекта. Готов к серьезной работе."),
                '⚡ Быстрый режим': ("fast", "Вы переключились в ⚡ Быстрый режим. Буду отвечать по фактам.")
            }

            if text in mode_messages:
                new_mode, reply_text = mode_messages[text]
                user_states[user_id] = new_mode
                vk.messages.send(user_id=user_id, random_id=get_random_id(), message=reply_text, keyboard=create_keyboard())
                continue

            if not text and not msg.get('attachments'):
                continue

            vk.messages.setActivity(type='typing', user_id=user_id, peer_id=user_id)

            # Собираем контент
            content_to_send = []
            if text:
                content_to_send.append(text)
            
            if msg.get('attachments'):
                for attachment in msg['attachments']:
                    img = get_image_from_attachment(attachment)
                    if img:
                        content_to_send.append(img)
            
            if not content_to_send:
                continue

            # === ЗАПУСК ДВОЙНОЙ ГЕНЕРАЦИИ ===
            current_mode = user_states[user_id]
            final_response = generate_with_fallback(content_to_send, current_mode)

            if final_response:
                vk.messages.send(user_id=user_id, random_id=get_random_id(), message=final_response, keyboard=create_keyboard())
            else:
                error_msg = (
                    "Техническая ошибка: серверы перегружены или исчерпаны лимиты запросов на всех узлах и моделях.\n\n"
                    "Пожалуйста, подождите немного или обратитесь к администратору."
                )
                vk.messages.send(user_id=user_id, random_id=get_random_id(), message=error_msg, keyboard=create_keyboard())

if __name__ == '__main__':
    main()

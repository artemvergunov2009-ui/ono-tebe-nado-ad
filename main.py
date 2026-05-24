import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import google.generativeai as genai
import datetime
import threading
import time
import requests
from io import BytesIO
from PIL import Image
import os
import sys
import logging

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
VK_TOKEN = os.getenv("VK_TOKEN")
PROXY_URL = os.getenv("PROXY_URL")
GEMINI_TOKENS_STR = os.getenv("GEMINI_TOKENS")

if not VK_TOKEN or not GEMINI_TOKENS_STR:
    logging.error("Не заданы обязательные переменные окружения (VK_TOKEN или GEMINI_TOKENS).")
    sys.exit(1)

GEMINI_TOKENS = [t.strip() for t in GEMINI_TOKENS_STR.split(",")]

# Применяем прокси глобально для работы Gemini
if PROXY_URL:
    os.environ['HTTP_PROXY'] = PROXY_URL
    os.environ['HTTPS_PROXY'] = PROXY_URL
    logging.info("Прокси для Google API применен.")

# Актуальные модели Gemini
GEMINI_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.0-flash"
]

# --- Инициализация ВК ---
vk_session = vk_api.VkApi(token=VK_TOKEN)

if PROXY_URL:
    vk_session.http.proxies = {
        'http': PROXY_URL,
        'https': PROXY_URL
    }
    logging.info("Прокси для vk_api применен.")

vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

# Хранилища (в идеале потом перевести на базу данных, например SQLite)
users_state = {} 
users_db = {}    

# --- КЛАВИАТУРЫ ---
def get_registration_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('⚙️ Сбросить', color=VkKeyboardColor.SECONDARY)
    return keyboard.get_keyboard()

def get_main_keyboard(user_id):
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('🔥 Новый день', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('📊 Итоги дня', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    
    is_water_on = users_db.get(user_id, {}).get('water_enabled', False)
    if is_water_on:
        keyboard.add_button('🔕 Выключить воду', color=VkKeyboardColor.NEGATIVE)
    else:
        keyboard.add_button('💧 Включить воду', color=VkKeyboardColor.PRIMARY)
        
    keyboard.add_button('🍽 Анализ еды', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('📝 Написать тренеру', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('⚙️ Сбросить', color=VkKeyboardColor.SECONDARY)
    return keyboard.get_keyboard()

def get_confirm_reset_keyboard():
    keyboard = VkKeyboard(one_time=True)
    keyboard.add_button('ДА', color=VkKeyboardColor.NEGATIVE)
    keyboard.add_button('НЕТ', color=VkKeyboardColor.PRIMARY)
    return keyboard.get_keyboard()

def get_cancel_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('❌ Отменить', color=VkKeyboardColor.NEGATIVE)
    return keyboard.get_keyboard()

def get_mood_keyboard():
    keyboard = VkKeyboard(one_time=True)
    keyboard.add_button('Хорошо', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('Нормально', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('Плохо', color=VkKeyboardColor.NEGATIVE)
    return keyboard.get_keyboard()

SURVEY_QUESTIONS = [
    "1. Выбери свою главную цель:\n1 - Убрать жир\n2 - Убрать живот\n3 - Сделать кубики пресса\n4 - Накачать руки (бицепс/трицепс)\n5 - Накачать широкую спину\n6 - Прокачать ноги и ягодицы\n7 - Улучшить выносливость\n8 - Набрать общую мышечную массу",
    "2. Какая у тебя цель в цифрах? Сколько кг ты хочешь убрать или набрать за месяц? (Напиши число, или '0', если вес не важен)",
    "3. Где ты будешь заниматься и с чем? (В спортзале, дома без инвентаря, дома с гантелями/резинками, на уличных турниках)",
    "4. Оцени свой текущий уровень подготовки. (Новичок, любитель, профи)",
    "5. Сколько дней в неделю готов(а) тренироваться?",
    "6. Есть ли проблемы со здоровьем, травмы спины, суставов? (Если нет, пиши 'Нет')",
    "7. Есть ли пищевые аллергии или продукты, которые ты терпеть не можешь?"
]

def send_message(user_id, text, keyboard=None):
    try:
        post = {'user_id': user_id, 'message': text, 'random_id': 0}
        if keyboard:
            post['keyboard'] = keyboard
        vk.messages.send(**post)
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")

def generate_ai_response(prompt_data):
    system_prompt = f"""
    СИСТЕМНЫЕ ИНСТРУКЦИИ:
    Ты — 'NEXUS-фитнес', ИИ-тренер. 
    ВАЖНОЕ ПРАВИЛО: НЕ ИСПОЛЬЗУЙ форматирование текста маркдауном. КАТЕГОРИЧЕСКИ запрещено использовать любые звездочки (*), решетки (#). Пиши обычным чистым текстом.
    ТЕКУЩАЯ ДАТА: {datetime.datetime.now().strftime("%Y-%m-%d")}
    """
    
    if isinstance(prompt_data, str):
        full_prompt = f"{system_prompt}\n\nЗАПРОС:\n{prompt_data}"
    else:
        full_prompt = [f"{system_prompt}\n\nЗАПРОС:\n{prompt_data[0]}", prompt_data[1]]

    for token in GEMINI_TOKENS:
        genai.configure(api_key=token)
        for model_name in GEMINI_MODELS:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(full_prompt)
                return response.text.replace("*", "").replace("#", "")
            except Exception as e:
                logging.warning(f"Ошибка модели {model_name} (токен {token[:8]}...): {e}")
                continue
                
    logging.error("Все ИИ-серверы недоступны или лимиты исчерпаны.")
    return "Произошла системная ошибка NEXUS: все ИИ-серверы временно недоступны."

def get_user_profile_text(user_data):
    return f"""
    Имя: {user_data.get('name')} | Возраст: {user_data.get('age')} | Рост: {user_data.get('height')} | Вес: {user_data.get('weight')}
    Цель: {user_data.get('q_0')} | Результат: {user_data.get('q_1')} кг
    Место: {user_data.get('q_2')} | Опыт: {user_data.get('q_3')} | Дней: {user_data.get('q_4')}
    Здоровье: {user_data.get('q_5')} | Аллергии: {user_data.get('q_6')}
    """

# --- ФОНОВЫЙ ПОТОК ВОДЫ ---
def water_reminder_loop():
    while True:
        time.sleep(7200)
        current_hour = datetime.datetime.now().hour
        if 9 <= current_hour <= 22:
            for user_id, data in users_db.items():
                if data.get('water_enabled') == True:
                    norm = data.get('water_norm', 'Ориентируйся на жажду.')
                    msg = f"💧 NEXUS-напоминание: Время выпить стакан воды!\n\nТвоя ИИ-норма на день: {norm}"
                    send_message(user_id, msg)

# --- ОСНОВНОЙ ПРОЦЕСС БОТА ---
def vk_bot_loop():
    while True:
        try:
            for event in longpoll.listen():
                if event.type == VkEventType.MESSAGE_NEW and event.to_me:
                    user_id = event.user_id
                    raw_text = event.text.strip()
                    text_lower = raw_text.lower()
                    
                    if text_lower == '❌ отменить':
                        if user_id in users_state:
                            del users_state[user_id]
                        send_message(user_id, "Действие отменено.", keyboard=get_main_keyboard(user_id) if user_id in users_db else get_registration_keyboard())
                        continue

                    if text_lower in ['⚙️ сбросить', 'сбросить']:
                        users_state[user_id] = {"step": "confirm_reset"}
                        send_message(user_id, "Вы точно хотите сбросить все данные?", keyboard=get_confirm_reset_keyboard())
                        continue
                        
                    if user_id in users_state and users_state[user_id].get("step") == "wait_food_photo":
                        try:
                            message_data = vk.messages.getById(message_ids=event.message_id)['items'][0]
                            attachments = message_data.get('attachments', [])
                            
                            photo_url = None
                            for att in attachments:
                                if att['type'] == 'photo':
                                    photo_url = att['photo']['sizes'][-1]['url']
                                    break
                            
                            if photo_url:
                                send_message(user_id, "Фото получено. Нейросеть NEXUS анализирует состав тарелки...")
                                req_proxies = {'http': PROXY_URL, 'https': PROXY_URL} if PROXY_URL else None
                                response = requests.get(photo_url, proxies=req_proxies)
                                response.raise_for_status()
                                
                                img = Image.open(BytesIO(response.content))
                                prompt = "Посмотри на фото. Скажи, что это за еда и напиши примерную калорийность (КБЖУ). Если еду видно плохо, так и скажи и попроси прислать фото лучше."
                                ai_answer = generate_ai_response([prompt, img])
                                send_message(user_id, ai_answer, keyboard=get_main_keyboard(user_id))
                                del users_state[user_id]
                            else:
                                send_message(user_id, "Я не вижу фото. Пожалуйста, прикрепи картинку или нажми 'Отменить'.", keyboard=get_cancel_keyboard())
                        except Exception as e:
                            logging.error(f"Ошибка при обработке фото еды: {e}")
                            send_message(user_id, "Не удалось загрузить или обработать фото. Попробуй еще раз.", keyboard=get_main_keyboard(user_id))
                            if user_id in users_state: del users_state[user_id]
                        continue

                    if user_id in users_state:
                        step = users_state[user_id].get("step")
                        
                        if step == "confirm_reset":
                            if text_lower == 'да':
                                if user_id in users_db: del users_db[user_id]
                                del users_state[user_id]
                                send_message(user_id, "✅ Данные удалены. Напиши 'Начать'.", keyboard=VkKeyboard.get_empty_keyboard())
                            elif text_lower == 'нет':
                                del users_state[user_id]
                                send_message(user_id, "Сброс отменен.", keyboard=get_main_keyboard(user_id) if user_id in users_db else get_registration_keyboard())
                            else:
                                send_message(user_id, "Нажми 'ДА' или 'НЕТ'.", keyboard=get_confirm_reset_keyboard())
                            continue

                        if step == "wait_trainer_msg":
                            users_db[user_id]["history"] = users_db[user_id].get("history", "") + f"\n[Сообщение тренеру от {datetime.datetime.now().strftime('%d.%m')}]: {raw_text}"
                            send_message(user_id, "Анализирую твое сообщение...")
                            
                            prompt = f"Пользователь написал своему ИИ-тренеру: '{raw_text}'. ДОСЬЕ: {get_user_profile_text(users_db[user_id])}. Ответь на вопрос или подтверди, что информация принята и будет учтена в следующих тренировках. Отвечай кратко и по делу."
                            ai_answer = generate_ai_response(prompt)
                            
                            send_message(user_id, ai_answer, keyboard=get_main_keyboard(user_id))
                            del users_state[user_id]
                            continue
                        
                        if step == "results_1":
                            users_state[user_id]["results"] = {"steps": raw_text}
                            users_state[user_id]["step"] = "results_2"
                            send_message(user_id, "Что из плана ты сегодня пропустил? Напиши честно.", keyboard=get_cancel_keyboard())
                            continue
                        elif step == "results_2":
                            users_state[user_id]["results"]["missed"] = raw_text
                            users_state[user_id]["step"] = "results_3"
                            send_message(user_id, "Как в целом прошел день?", keyboard=get_mood_keyboard())
                            continue
                        elif step == "results_3":
                            users_db[user_id]["history"] = users_db[user_id].get("history", "") + f"\n[Итоги от {datetime.datetime.now().strftime('%d.%m')}]: шаги {users_state[user_id]['results']['steps']}, пропуски: {users_state[user_id]['results']['missed']}, настроение: {raw_text}"
                            send_message(user_id, "Итоги дня сохранены! Учту это для плана на завтра.", keyboard=get_main_keyboard(user_id))
                            del users_state[user_id]
                            continue

                        data = users_state[user_id].get("data", {})
                        if step == "name":
                            data["name"] = raw_text
                            users_state[user_id]["step"] = "age"
                            send_message(user_id, f"Отлично, {raw_text}! Сколько тебе лет?", keyboard=get_registration_keyboard())
                        elif step == "age":
                            data["age"] = raw_text
                            users_state[user_id]["step"] = "height"
                            send_message(user_id, "Какой у тебя рост (в см)?", keyboard=get_registration_keyboard())
                        elif step == "height":
                            data["height"] = raw_text
                            users_state[user_id]["step"] = "weight"
                            send_message(user_id, "Какой у тебя вес (в кг)?", keyboard=get_registration_keyboard())
                        elif step == "weight":
                            data["weight"] = raw_text
                            users_state[user_id]["step"] = "q_0"
                            send_message(user_id, "Супер. Перейдем к целям.\n\n" + SURVEY_QUESTIONS[0], keyboard=get_registration_keyboard())
                        elif step.startswith("q_"):
                            q_index = int(step.split("_")[1])
                            data[f"q_{q_index}"] = raw_text
                            next_q_index = q_index + 1
                            
                            if next_q_index < len(SURVEY_QUESTIONS):
                                users_state[user_id]["step"] = f"q_{next_q_index}"
                                send_message(user_id, SURVEY_QUESTIONS[next_q_index], keyboard=get_registration_keyboard())
                            else:
                                send_message(user_id, "Составляю твой фитнес-план. Подожди 10 секунд...")
                                users_db[user_id] = data.copy()
                                users_db[user_id]["day_count"] = 0
                                users_db[user_id]["last_day_date"] = ""
                                users_db[user_id]["history"] = ""
                                
                                prompt = f"ДОСЬЕ: {get_user_profile_text(data)}. Напиши краткое приветствие, оцени реалистичность цели и дай пару базовых советов."
                                plan = generate_ai_response(prompt)
                                send_message(user_id, plan, keyboard=get_main_keyboard(user_id))
                                del users_state[user_id]
                        continue

                    if text_lower in ['начать', '/start', 'привет']:
                        if user_id in users_db:
                            send_message(user_id, "Я помню твои параметры! Если хочешь начать заново, нажми 'Сбросить'.", keyboard=get_main_keyboard(user_id))
                        else:
                            users_state[user_id] = {"step": "name", "data": {}}
                            send_message(user_id, "Привет! Я 'NEXUS-фитнес'. Давай заполним анкету.\n\nКак тебя зовут?", keyboard=get_registration_keyboard())
                        continue

                    if text_lower == '📝 написать тренеру':
                        if user_id not in users_db: continue
                        users_state[user_id] = {"step": "wait_trainer_msg"}
                        send_message(user_id, "Что ты хочешь рассказать? Опиши изменения в рационе, пропущенные упражнения или задай любой вопрос.", keyboard=get_cancel_keyboard())
                        continue

                    if text_lower == '💧 включить воду':
                        if user_id not in users_db: continue
                        ai_water_norm = generate_ai_response(f"Рассчитай суточную норму воды. Вес: {users_db[user_id].get('weight')} кг, Опыт: {users_db[user_id].get('q_3')}. Выдай ТОЛЬКО конкретный объем в литрах.")
                        users_db[user_id]['water_enabled'] = True
                        users_db[user_id]['water_norm'] = ai_water_norm
                        send_message(user_id, f"✅ Уведомления включены.\n{ai_water_norm}", keyboard=get_main_keyboard(user_id))
                        continue

                    if text_lower == '🔕 выключить воду':
                        if user_id in users_db:
                            users_db[user_id]['water_enabled'] = False
                            send_message(user_id, "❌ Вода отключена.", keyboard=get_main_keyboard(user_id))
                        continue

                    if text_lower == '🍽 анализ еды':
                        if user_id not in users_db: continue
                        users_state[user_id] = {"step": "wait_food_photo"}
                        send_message(user_id, "Отправь мне фото своей тарелки с едой!", keyboard=get_cancel_keyboard())
                        continue
                        
                    if text_lower == '📊 итоги дня':
                        if user_id not in users_db: continue
                        users_state[user_id] = {"step": "results_1"}
                        send_message(user_id, "Давай подведем итоги! Сколько шагов ты сегодня прошел?", keyboard=get_cancel_keyboard())
                        continue

                    if text_lower == '🔥 новый день':
                        if user_id not in users_db:
                            send_message(user_id, "Сначала пройди регистрацию! Напиши 'Начать'.", keyboard=get_registration_keyboard())
                            continue
                        
                        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
                        if users_db[user_id].get("last_day_date") == today_str:
                            send_message(user_id, "Новый день еще не начался! Следующий план будет доступен после 00:00.", keyboard=get_main_keyboard(user_id))
                            continue
                            
                        send_message(user_id, "Генерирую план на сегодня...")
                        users_db[user_id]["day_count"] = users_db[user_id].get("day_count", 0) + 1
                        users_db[user_id]["last_day_date"] = today_str
                        
                        daily_prompt = f"""
                        ДОСЬЕ: {get_user_profile_text(users_db[user_id])}
                        ИСТОРИЯ, ИТОГИ И ВОПРОСЫ ПОЛЬЗОВАТЕЛЯ (УЧТИ ЭТО ДЛЯ КОРРЕКЦИИ): {users_db[user_id].get("history", "")}
                        
                        Выдай ответ СТРОГО в следующем формате. Пиши ОЧЕНЬ коротко.
                        
                        День {users_db[user_id]["day_count"]}🔥 - {datetime.datetime.now().strftime("%d %B %Y")} год:

                        Питание:
                        завтрак:
                        - [еда, количество]
                        - [еда]
                        обед:
                        - [еда]
                        - [еда]
                        ужин:
                        - [еда]
                        - [еда]

                        Упражнения на сегодня:
                        1. [Название] [количество] раз
                        2. [Название] [количество] раз

                        прогулка:
                        пройти сегодня [количество] километров

                        Удачи!
                        """
                        response_text = generate_ai_response(daily_prompt)
                        send_message(user_id, response_text, keyboard=get_main_keyboard(user_id))
                        continue

                    if user_id in users_db:
                        send_message(user_id, "Используй кнопки меню ниже!", keyboard=get_main_keyboard(user_id))
                    else:
                        send_message(user_id, "Напиши 'Начать'.", keyboard=get_registration_keyboard())

        except requests.exceptions.RequestException as e:
            logging.error(f"Сетевая ошибка VK LongPoll (возможно, отвалился прокси): {e}")
            time.sleep(5)
        except Exception as e:
            logging.error(f"Непредвиденная ошибка в основном цикле LongPoll: {e}")
            time.sleep(5)

if __name__ == "__main__":
    logging.info("NEXUS BOT STARTED")
    
    # Фоновый поток для уведомлений о воде
    threading.Thread(target=water_reminder_loop, daemon=True).start()
    
    # Основной поток держит LongPoll (не daemon, чтобы скрипт не завершался)
    vk_bot_loop()

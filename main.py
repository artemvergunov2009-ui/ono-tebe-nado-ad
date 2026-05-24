import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import datetime
import threading
import time
import requests
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
PROXY_URL = os.getenv("PROXY_URL") # Прокси теперь нужен ТОЛЬКО для ВКонтакте (если сервер за границей)
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")

if not VK_TOKEN or not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
    logging.error("Не заданы обязательные переменные (VK_TOKEN, YANDEX_API_KEY, YANDEX_FOLDER_ID).")
    sys.exit(1)

# --- Инициализация ВК ---
vk_session = vk_api.VkApi(token=VK_TOKEN)

# Инъекция прокси только для ВК (Яндекс доступен глобально, ему прокси не нужен)
if PROXY_URL:
    vk_session.http.proxies = {
        'http': PROXY_URL,
        'https': PROXY_URL
    }
    logging.info("Прокси для vk_api применен.")

vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

# Хранилища
users_state = {} 
users_db = {}    

# --- КЛАВИАТУРЫ ---
def get_registration_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('⚙️ Сбросить', color=VkKeyboardColor.SECONDARY)
    return keyboard.get_keyboard()

def get_gender_keyboard():
    keyboard = VkKeyboard(one_time=True)
    keyboard.add_button('Мужской 👨', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('Женский 👩', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
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
    "2. Какая у тебя цель в цифрах? Сколько кг ты хочешь убрать/набрать за месяц? (Или '0')",
    "3. Где ты будешь заниматься и с чем? (В зале, дома без инвентаря, дома с гантелями, на турниках)",
    "4. Оцени свой текущий уровень подготовки. (Новичок, любитель, профи)",
    "5. Сколько дней в неделю готов(а) тренироваться?",
    "6. Есть ли проблемы со здоровьем, травмы? (Если нет, пиши 'Нет')",
    "7. Есть ли пищевые аллергии или продукты, которые ты терпеть не можешь?"
]

def send_message(user_id, text, keyboard=None):
    try:
        post = {'user_id': user_id, 'message': text, 'random_id': 0}
        if keyboard:
            post['keyboard'] = keyboard
        vk.messages.send(**post)
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения: {e}")

# --- ФУНКЦИЯ ЗАПРОСА К YANDEX GPT (АЛИСА) ---
def generate_ai_response(system_prompt, user_prompt):
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    
    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Используем модель yandexgpt (самую умную из доступных по умолчанию)
    data = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
        "completionOptions": {
            "stream": False,
            "temperature": 0.6,
            "maxTokens": "2000"
        },
        "messages": [
            {
                "role": "system",
                "text": system_prompt + "\nВАЖНОЕ ПРАВИЛО: НЕ ИСПОЛЬЗУЙ форматирование текста маркдауном. КАТЕГОРИЧЕСКИ запрещено использовать любые звездочки (*), решетки (#). Пиши обычным чистым текстом."
            },
            {
                "role": "user",
                "text": user_prompt
            }
        ]
    }
    
    try:
        # Для запроса к Яндексу прокси не применяем, чтобы не было конфликтов
        response = requests.post(url, headers=headers, json=data, timeout=20)
        response.raise_for_status()
        result = response.json()
        
        answer = result.get('result', {}).get('alternatives', [{}])[0].get('message', {}).get('text', '')
        return answer.replace("*", "").replace("#", "")
        
    except Exception as e:
        logging.error(f"Ошибка при обращении к YandexGPT: {e}")
        return "Произошла системная ошибка: серверы Яндекса (Алисы) временно недоступны."

def get_user_profile_text(user_data):
    return f"""
    Имя: {user_data.get('name')} | Пол: {user_data.get('gender')} | Возраст: {user_data.get('age')} | Рост: {user_data.get('height')} | Вес: {user_data.get('weight')}
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
                    msg = f"💧 NEXUS-напоминание: Время выпить стакан воды!\n\nТвоя норма на день: {norm}"
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
                        
                    # --- ИЗМЕНЕНИЕ ДЛЯ АЛИСЫ: Текстовый анализ еды вместо фото ---
                    if user_id in users_state and users_state[user_id].get("step") == "wait_food_text":
                        send_message(user_id, "Нейросеть Алиса анализирует твой прием пищи...")
                        
                        system_p = "Ты — нутрициолог. Тебе описывают прием пищи. Рассчитай примерную калорийность и КБЖУ (белки, жиры, углеводы) для этого блюда. Дай краткий и полезный совет."
                        ai_answer = generate_ai_response(system_p, raw_text)
                        
                        send_message(user_id, ai_answer, keyboard=get_main_keyboard(user_id))
                        del users_state[user_id]
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
                            send_message(user_id, "Алиса анализирует твое сообщение...")
                            
                            system_p = "Ты — 'NEXUS-фитнес', ИИ-тренер на базе Алисы. Отвечай кратко, по-доброму и по делу."
                            user_p = f"Пользователь написал своему тренеру: '{raw_text}'. ДОСЬЕ: {get_user_profile_text(users_db[user_id])}. Ответь на вопрос или дай совет."
                            ai_answer = generate_ai_response(system_p, user_p)
                            
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
                            send_message(user_id, "Итоги дня сохранены! Алиса учтет это для плана на завтра.", keyboard=get_main_keyboard(user_id))
                            del users_state[user_id]
                            continue

                        data = users_state[user_id].get("data", {})
                        
                        if step == "name":
                            data["name"] = raw_text
                            users_state[user_id]["step"] = "gender"
                            send_message(user_id, f"Отлично, {raw_text}! Укажи свой пол:", keyboard=get_gender_keyboard())
                        elif step == "gender":
                            clean_gender = raw_text.replace("👨", "").replace("👩", "").strip()
                            data["gender"] = clean_gender
                            users_state[user_id]["step"] = "age"
                            send_message(user_id, "Принято! Сколько тебе лет?", keyboard=get_registration_keyboard())
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
                                send_message(user_id, "Алиса составляет твой персональный фитнес-план. Подожди 5 секунд...")
                                users_db[user_id] = data.copy()
                                users_db[user_id]["day_count"] = 0
                                users_db[user_id]["last_day_date"] = ""
                                users_db[user_id]["history"] = ""
                                
                                system_p = "Ты — ИИ-тренер 'NEXUS-фитнес' на базе Яндекс Алисы. Напиши краткое приветствие, оцени цель и дай базу."
                                user_p = f"ДОСЬЕ: {get_user_profile_text(data)}. Учти пол пользователя ({data.get('gender')})."
                                plan = generate_ai_response(system_p, user_p)
                                
                                send_message(user_id, plan, keyboard=get_main_keyboard(user_id))
                                del users_state[user_id]
                        continue

                    if text_lower in ['начать', '/start', 'привет']:
                        if user_id in users_db:
                            send_message(user_id, "Я помню твои параметры! Если хочешь начать заново, нажми 'Сбросить'.", keyboard=get_main_keyboard(user_id))
                        else:
                            users_state[user_id] = {"step": "name", "data": {}}
                            send_message(user_id, "Привет! Я 'NEXUS-фитнес' (Powered by YandexGPT). Давай заполним анкету.\n\nКак тебя зовут?", keyboard=get_registration_keyboard())
                        continue

                    if text_lower == '📝 написать тренеру':
                        if user_id not in users_db: continue
                        users_state[user_id] = {"step": "wait_trainer_msg"}
                        send_message(user_id, "Что ты хочешь рассказать? Опиши изменения в рационе, задай вопрос или пожалуйся на усталость.", keyboard=get_cancel_keyboard())
                        continue

                    if text_lower == '💧 включить воду':
                        if user_id not in users_db: continue
                        system_p = "Ты нутрициолог. Выдай ТОЛЬКО конкретный объем воды в литрах (например: 2.2 л). Никакого лишнего текста."
                        user_p = f"Рассчитай суточную норму воды. Пол: {users_db[user_id].get('gender')}, Вес: {users_db[user_id].get('weight')} кг."
                        
                        ai_water_norm = generate_ai_response(system_p, user_p)
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
                        users_state[user_id] = {"step": "wait_food_text"}
                        # Изменение: Просим текст, а не картинку
                        send_message(user_id, "Напиши словами, что у тебя в тарелке (например: '200г вареной курицы, 150г риса и помидор'), и я посчитаю КБЖУ!", keyboard=get_cancel_keyboard())
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
                            
                        send_message(user_id, "Алиса генерирует персональный план на сегодня...")
                        users_db[user_id]["day_count"] = users_db[user_id].get("day_count", 0) + 1
                        users_db[user_id]["last_day_date"] = today_str
                        
                        system_p = "Ты профессиональный фитнес-тренер. Выдай строгий план."
                        user_p = f"""
                        ДОСЬЕ: {get_user_profile_text(users_db[user_id])}
                        ИСТОРИЯ, ИТОГИ И ВОПРОСЫ ПОЛЬЗОВАТЕЛЯ: {users_db[user_id].get("history", "")}
                        
                        ВНИМАНИЕ: Обязательно учитывай ПОЛ пользователя ({users_db[user_id].get('gender')}) при подборе упражнений (акценты на нужные группы мышц).
                        
                        Выдай ответ СТРОГО в следующем формате:
                        День {users_db[user_id]["day_count"]}🔥:
                        Питание (завтрак, обед, ужин):
                        - ...
                        Упражнения:
                        1. ...
                        Прогулка: ... км
                        """
                        response_text = generate_ai_response(system_p, user_p)
                        send_message(user_id, response_text, keyboard=get_main_keyboard(user_id))
                        continue

                    if user_id in users_db:
                        send_message(user_id, "Используй кнопки меню ниже!", keyboard=get_main_keyboard(user_id))
                    else:
                        send_message(user_id, "Напиши 'Начать'.", keyboard=get_registration_keyboard())

        except requests.exceptions.RequestException as e:
            logging.error(f"Сетевая ошибка VK LongPoll: {e}")
            time.sleep(5)
        except Exception as e:
            logging.error(f"Непредвиденная ошибка в основном цикле LongPoll: {e}")
            time.sleep(5)

if __name__ == "__main__":
    logging.info("NEXUS BOT STARTED (POWERED BY YANDEX GPT)")
    
    # Фоновый поток для уведомлений о воде
    threading.Thread(target=water_reminder_loop, daemon=True).start()
    
    # Основной поток держит LongPoll
    vk_bot_loop()

import asyncio
import sqlite3
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- НАСТРОЙКИ ---
TOKEN = "8513147127:AAEkzGMP5fcZvhq9Y7KZZRzK5WTe-2QkgjM"
ADMINS = [7070204958, 5704676381]

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("svahuilsk.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS citizens (user_id INTEGER PRIMARY KEY, name TEXT, username TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS passport_fields (user_id INTEGER, field_name TEXT, field_value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY, author TEXT, text TEXT, date TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS laws (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS marriages (id INTEGER PRIMARY KEY AUTOINCREMENT, user1_id INTEGER, user2_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS wanted (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, reason TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    conn.close()

def get_or_create_user(user_id, name, username=""):
    conn = sqlite3.connect("svahuilsk.db")
    cursor = conn.cursor()
    username_clean = username.replace("@", "") if username else ""
    
    cursor.execute("SELECT * FROM citizens WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO citizens (user_id, name, username) VALUES (?, ?, ?)", (user_id, name, username_clean))
    else:
        cursor.execute("UPDATE citizens SET username = ? WHERE user_id = ?", (username_clean, user_id))
    conn.commit()
    conn.close()

def resolve_user(username_or_id):
    conn = sqlite3.connect("svahuilsk.db")
    clean_input = str(username_or_id).replace("@", "").strip()
    res = conn.execute("SELECT user_id, name FROM citizens WHERE username = ? COLLATE NOCASE", (clean_input,)).fetchone()
    if not res and clean_input.isdigit():
        res = conn.execute("SELECT user_id, name FROM citizens WHERE user_id = ?", (int(clean_input),)).fetchone()
    conn.close()
    return res

def get_group_id():
    conn = sqlite3.connect("svahuilsk.db")
    res = conn.execute("SELECT value FROM settings WHERE key = 'group_id'").fetchone()
    conn.close()
    return int(res[0]) if res else None

def get_user_name(user_id):
    conn = sqlite3.connect("svahuilsk.db")
    fields = dict(conn.execute("SELECT field_name, field_value FROM passport_fields WHERE user_id = ?", (user_id,)).fetchall())
    tg_name_res = conn.execute("SELECT name FROM citizens WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()

    parts = []
    if "Фамилия" in fields: parts.append(fields["Фамилия"])
    if "Имя" in fields: parts.append(fields["Имя"])
    if "Отчество" in fields: parts.append(fields["Отчество"])

    tg_name = tg_name_res[0] if tg_name_res else f"ID {user_id}"
    return " ".join(parts) if parts else tg_name

# --- СОСТОЯНИЯ (FSM) ---
class AppFSM(StatesGroup):
    pass_target = State()
    pass_field_selection = State()
    pass_custom_field = State()
    pass_value = State()
    mod_target = State()
    recog_target = State()
    recog_status = State()
    wanted_target = State()
    wanted_reason = State()
    report_target = State()
    report_reason = State()
    fire_target = State()

def get_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])

@dp.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Действие отменено. 🔙")

def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪪 Мой паспорт", callback_data="passport"), 
         InlineKeyboardButton(text="📰 Новости", callback_data="news")],
        [InlineKeyboardButton(text="📜 Законы", callback_data="laws"), 
         InlineKeyboardButton(text="💼 Биржа труда", callback_data="jobs")],
        [InlineKeyboardButton(text="🚓 База розыска", callback_data="wanted_list"),
         InlineKeyboardButton(text="🚨 Пожаловаться", callback_data="report_user")]
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]])

# УМНАЯ КЛАВИАТУРА: Понимает, где находится пользователь
def get_reply_kb(user_id, chat_type):
    buttons = [[KeyboardButton(text="🏛 Меню Свахуильска")]]
    # Кнопка панели властей появляется ТОЛЬКО у админов и ТОЛЬКО в ЛС бота (private)
    if user_id in ADMINS and chat_type == "private":
        buttons.append([KeyboardButton(text="⚙️ Панель Властей")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# --- ИНТЕРФЕЙС ГРУППЫ ---
@dp.message(Command("start"))
async def start_cmd(message: Message):
    get_or_create_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    await message.answer("Свахуильск приветствует вас!", reply_markup=get_reply_kb(message.from_user.id, message.chat.type))

@dp.message(Command("menu"))
@dp.message(F.text == "🏛 Меню Свахуильска")
async def show_menu(message: Message):
    get_or_create_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    rp_name = get_user_name(message.from_user.id)
    mention = f'<a href="tg://user?id={message.from_user.id}">{rp_name}</a>'
    
    # Обновляем клавиатуру на случай, если у админа залагали кнопки из ЛС
    await message.answer(f"🏛 <b>Главное меню гражданина {mention}:</b>", reply_markup=main_menu_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    get_or_create_user(callback.from_user.id, callback.from_user.first_name, callback.from_user.username)
    rp_name = get_user_name(callback.from_user.id)
    mention = f'<a href="tg://user?id={callback.from_user.id}">{rp_name}</a>'
    await callback.message.edit_text(f"🏛 <b>Главное меню гражданина {mention}:</b>", reply_markup=main_menu_kb(), parse_mode="HTML")

# --- 🪪 ПАСПОРТ И РОЗЫСК ---
@dp.callback_query(F.data == "passport")
async def show_passport(callback: CallbackQuery):
    u_id = callback.from_user.id
    get_or_create_user(u_id, callback.from_user.first_name, callback.from_user.username)
    
    rp_name = get_user_name(u_id)
    conn = sqlite3.connect("svahuilsk.db")
    fields = conn.execute("SELECT field_name, field_value FROM passport_fields WHERE user_id = ?", (u_id,)).fetchall()
    conn.close()

    mention = f'<a href="tg://user?id={u_id}">{rp_name}</a>'
    text = f"🪪 <b>Паспорт Свахуильца</b>\n\n"
    text += f"👤 <b>ФИО:</b> {mention}\n"
    
    exclude_fields = ["Имя", "Фамилия", "Отчество"]
    added_any = False
    
    for f_name, f_val in fields:
        if f_name not in exclude_fields:
            text += f"🔹 <b>{f_name}:</b> {f_val}\n"
            added_any = True
            
    if not added_any and len(fields) <= len(exclude_fields):
        text += "<i>Остальные данные еще не заполнены властями.</i>"
    
    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "wanted_list")
async def show_wanted(callback: CallbackQuery):
    conn = sqlite3.connect("svahuilsk.db")
    criminals = conn.execute("SELECT username, reason FROM wanted").fetchall()
    conn.close()

    text = "🚓 <b>БАЗА ФЕДЕРАЛЬНОГО РОЗЫСКА:</b>\n\n"
    for w_name, w_reason in criminals:
        text += f"🔴 <b>{w_name}</b>\n<i>Причина: {w_reason}</i>\n\n"
    if not criminals:
        text += "✅ На данный момент преступников в розыске нет."

    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")

# --- 🚨 СИСТЕМА ЖАЛОБ (РЕПОРТЫ) ---
@dp.callback_query(F.data == "report_user")
async def report_start(callback: CallbackQuery, state: FSMContext):
    msg = await callback.message.edit_text("🚨 <b>Подача жалобы властям</b>\nВведите @ник или ID нарушителя:", reply_markup=get_cancel_kb(), parse_mode="HTML")
    await state.update_data(rep_msg_id=msg.message_id)
    await state.set_state(AppFSM.report_target)

@dp.message(AppFSM.report_target)
async def report_target_chosen(message: Message, state: FSMContext):
    target_user = resolve_user(message.text)
    data = await state.get_data()
    
    try: await bot.delete_message(message.chat.id, message.message_id)
    except: pass

    if not target_user:
        return await bot.edit_message_text("❌ Пользователь не найден. Введите верный @ник:", chat_id=message.chat.id, message_id=data['rep_msg_id'], reply_markup=get_cancel_kb())
    
    await state.update_data(target_id=target_user[0], target_name=target_user[1])
    await bot.edit_message_text(f"Опишите причину жалобы на <b>{target_user[1]}</b>:", chat_id=message.chat.id, message_id=data['rep_msg_id'], reply_markup=get_cancel_kb(), parse_mode="HTML")
    await state.set_state(AppFSM.report_reason)

@dp.message(AppFSM.report_reason)
async def report_send(message: Message, state: FSMContext):
    data = await state.get_data()
    try: await bot.delete_message(message.chat.id, message.message_id)
    except: pass

    rp_name_sender = get_user_name(message.from_user.id)
    sender_mention = f'<a href="tg://user?id={message.from_user.id}">{rp_name_sender}</a>'
    
    rp_name_target = get_user_name(data["target_id"])
    target_mention = f'<a href="tg://user?id={data["target_id"]}">{rp_name_target}</a>'
    reason = message.text

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔇 Мут 1 час", callback_data=f"fastmod_mute_{data['target_id']}"),
         InlineKeyboardButton(text="⛔️ Бан", callback_data=f"fastmod_ban_{data['target_id']}")],
        [InlineKeyboardButton(text="🟢 Закрыть жалобу", callback_data="fastmod_close")]
    ])

    for admin in ADMINS:
        try:
            await bot.send_message(admin, f"🚨 <b>НОВАЯ ЖАЛОБА!</b>\nОт: {sender_mention}\nНа: {target_mention}\n\n<b>Причина:</b> {reason}", reply_markup=kb, parse_mode="HTML")
        except: pass

    await bot.edit_message_text("✅ Ваша жалоба успешно отправлена Администрации Свахуильска.", chat_id=message.chat.id, message_id=data['rep_msg_id'], reply_markup=back_kb())
    await state.clear()

@dp.callback_query(F.data.startswith("fastmod_"))
async def fast_mod_action(callback: CallbackQuery):
    action = callback.data.split("_")[1]
    if action == "close":
        return await callback.message.edit_text(callback.message.html_text + "\n\n<i>✅ Жалоба закрыта/отклонена.</i>", parse_mode="HTML")

    target_id = int(callback.data.split("_")[2])
    group_id = get_group_id()
    if not group_id: return await callback.answer("❌ Бот не знает ID группы!", show_alert=True)

    try:
        if action == "mute":
            await bot.restrict_chat_member(group_id, target_id, permissions={}, until_date=int(time.time()) + 3600)
            await callback.message.edit_text(callback.message.html_text + "\n\n<i>✅ Выдан Мут на 1 час.</i>", parse_mode="HTML")
        elif action == "ban":
            await bot.ban_chat_member(group_id, target_id)
            await callback.message.edit_text(callback.message.html_text + "\n\n<i>✅ Пользователь забанен.</i>", parse_mode="HTML")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

# --- СВАДЬБЫ ---
@dp.message(F.text.lower() == "брак")
async def propose_marriage(message: Message):
    if not message.reply_to_message:
        return await message.answer("⚠️ Чтобы сделать предложение, ответьте на сообщение человека словом «брак»!")
    
    u1_id = message.from_user.id
    u2_id = message.reply_to_message.from_user.id

    if u1_id == u2_id: return await message.answer("Вы не можете жениться на самом себе!")

    get_or_create_user(u1_id, message.from_user.first_name, message.from_user.username)
    get_or_create_user(u2_id, message.reply_to_message.from_user.first_name, message.reply_to_message.from_user.username)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💍 Согласен(на)", callback_data=f"marryyes_{u1_id}_{u2_id}"),
         InlineKeyboardButton(text="💔 Отказ", callback_data=f"marryno_{u1_id}")]
    ])
    
    n2 = get_user_name(u2_id)
    n1 = get_user_name(u1_id)
    mention2 = f'<a href="tg://user?id={u2_id}">{n2}</a>'
    mention1 = f'<a href="tg://user?id={u1_id}">{n1}</a>'
    
    await message.answer(f"💍 Житель {mention2}, {mention1} предлагает вам вступить в брак! Вы согласны?", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("marryno_"))
async def marry_no(callback: CallbackQuery):
    await callback.message.edit_text("💔 Очень грустно... Поступил отказ от свадьбы.")

@dp.callback_query(F.data.startswith("marryyes_"))
async def marry_yes(callback: CallbackQuery):
    if str(callback.from_user.id) != callback.data.split("_")[2]:
        return await callback.answer("Это предложение не вам!", show_alert=True)
    
    _, u1_id, u2_id = callback.data.split("_")
    
    conn = sqlite3.connect("svahuilsk.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO marriages (user1_id, user2_id) VALUES (?, ?)", (u1_id, u2_id))
    m_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await callback.message.edit_text("💍 Согласие получено! Запрос отправлен властям на регистрацию.")

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏛 Одобрить брак", callback_data=f"adminmarry_{m_id}")]])
    for admin in ADMINS:
        try: await bot.send_message(admin, f"💍 <b>Запрос на брак!</b>\nЖители с ID {u1_id} и {u2_id} хотят пожениться.", reply_markup=kb, parse_mode="HTML")
        except: pass

@dp.callback_query(F.data.startswith("adminmarry_"))
async def admin_approve_marriage(callback: CallbackQuery):
    m_id = callback.data.split("_")[1]
    
    conn = sqlite3.connect("svahuilsk.db")
    m = conn.execute("SELECT user1_id, user2_id FROM marriages WHERE id = ?", (m_id,)).fetchone()
    if not m:
        conn.close()
        return await callback.answer("Брак не найден или уже зарегистрирован.")

    u1_id, u2_id = m
    conn.execute("DELETE FROM marriages WHERE id = ?", (m_id,))
    
    u1_name = get_user_name(u1_id)
    u2_name = get_user_name(u2_id)
    
    date = datetime.now().strftime("%d.%m.%Y")
    conn.execute("DELETE FROM passport_fields WHERE user_id = ? AND field_name = 'Брак'", (u1_id,))
    conn.execute("DELETE FROM passport_fields WHERE user_id = ? AND field_name = 'Брак'", (u2_id,))
    conn.execute("INSERT INTO passport_fields (user_id, field_name, field_value) VALUES (?, 'Брак', ?)", (u1_id, f"В браке с {u2_name} от {date}"))
    conn.execute("INSERT INTO passport_fields (user_id, field_name, field_value) VALUES (?, 'Брак', ?)", (u2_id, f"В браке с {u1_name} от {date}"))
    conn.commit()
    conn.close()

    await callback.message.edit_text("✅ Брак официально зарегистрирован!")
    group_id = get_group_id()
    if group_id:
        try: await bot.send_message(group_id, f"🎊 <b>ОФИЦИАЛЬНО!</b>\nВласть утвердила брак между <a href='tg://user?id={u1_id}'>{u1_name}</a> и <a href='tg://user?id={u2_id}'>{u2_name}</a>! Горько!", parse_mode="HTML")
        except: pass

# --- 📰 НОВОСТИ И ЗАКОНЫ ---
@dp.callback_query(F.data == "news")
async def show_news(callback: CallbackQuery):
    conn = sqlite3.connect("svahuilsk.db")
    news = conn.execute("SELECT author, text, date FROM news WHERE id = 1").fetchone()
    conn.close()
    
    text = f"📰 <b>ГЛАВНАЯ НОВОСТЬ</b>\n\n{news[1]}\n\n<i>✍️ Автор: {news[0]} | 📅 {news[2]}</i>" if news else "📰 Новостей нет."
    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "laws")
async def show_laws(callback: CallbackQuery):
    conn = sqlite3.connect("svahuilsk.db")
    laws = conn.execute("SELECT id, text FROM laws").fetchall()
    conn.close()
    
    text = "📜 <b>ЗАКОНЫ СВАХУИЛЬСКА:</b>\n\n"
    for law in laws:
        text += f"<b>Статья {law[0]}:</b> {law[1]}\n\n"
    if not laws: text = "📜 Законы пока не приняты."
        
    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")

# --- 💼 РАБОТА И УВОЛЬНЕНИЕ ---
@dp.callback_query(F.data == "jobs")
async def show_jobs(callback: CallbackQuery):
    get_or_create_user(callback.from_user.id, callback.from_user.first_name, callback.from_user.username)
    rp_name = get_user_name(callback.from_user.id)
    mention = f'<a href="tg://user?id={callback.from_user.id}">{rp_name}</a>'
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏ Шахтёр", callback_data="applyjob_Шахтёр"), InlineKeyboardButton(text="🌾 Фермер", callback_data="applyjob_Фермер")],
        [InlineKeyboardButton(text="🏗 Строитель", callback_data="applyjob_Строитель")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(f"💼 <b>Биржа труда</b>\n{mention}, выберите вакансию.", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("applyjob_"))
async def apply_job(callback: CallbackQuery):
    job = callback.data.split("_")[1]
    u_id = callback.from_user.id
    rp_name = get_user_name(u_id)

    for admin in ADMINS:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"jobok_{u_id}_{job}"), InlineKeyboardButton(text="❌ Отказать", callback_data=f"jobno_{u_id}_{job}")]
        ])
        try: await bot.send_message(admin, f"💼 <b>Заявка!</b>\nЖитель {rp_name} хочет стать: <b>{job}</b>", reply_markup=kb, parse_mode="HTML")
        except: pass
    
    await callback.message.edit_text("✅ Заявка отправлена властям! Ожидайте решения в группе.", reply_markup=back_kb())

@dp.callback_query(F.data.startswith("jobok_"))
async def accept_job(callback: CallbackQuery):
    _, u_id, job = callback.data.split("_")
    name = get_user_name(u_id)
    mention = f'<a href="tg://user?id={u_id}">{name}</a>'
    
    conn = sqlite3.connect("svahuilsk.db")
    conn.execute("DELETE FROM passport_fields WHERE user_id = ? AND field_name = 'Профессия'", (u_id,))
    conn.execute("INSERT INTO passport_fields (user_id, field_name, field_value) VALUES (?, 'Профессия', ?)", (u_id, job))
    conn.commit()
    conn.close()
    
    await callback.message.edit_text(f"✅ Вы устроили {name} на должность {job}.")
    group_id = get_group_id()
    if group_id:
        try: await bot.send_message(group_id, f"🎉 Власти официально утвердили {mention} на должность: <b>{job}</b>!", parse_mode="HTML")
        except: pass

@dp.callback_query(F.data.startswith("jobno_"))
async def reject_job(callback: CallbackQuery):
    _, u_id, job = callback.data.split("_")
    name = get_user_name(u_id)
    mention = f'<a href="tg://user?id={u_id}">{name}</a>'
    
    await callback.message.edit_text(f"❌ Заявка {name} отклонена.")
    group_id = get_group_id()
    if group_id:
        try: await bot.send_message(group_id, f"😔 Власти отклонили заявку {mention} на должность <b>{job}</b>.", parse_mode="HTML")
        except: pass

# --- ПАНЕЛЬ ВЛАСТЕЙ В ЛС ---
@dp.message(F.text == "⚙️ Панель Властей")
async def admin_panel(message: Message):
    if message.from_user.id not in ADMINS or message.chat.type != "private": return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪪 Изменить паспорт", callback_data="admin_edit_pass")],
        [InlineKeyboardButton(text="💼 Уволить с работы", callback_data="admin_fire")],
        [InlineKeyboardButton(text="📢 Официальное признание", callback_data="admin_recognize")],
        [InlineKeyboardButton(text="🚓 Управление розыском", callback_data="admin_wanted")],
        [InlineKeyboardButton(text="⚖️ Модерация (Мут/Бан)", callback_data="admin_mod")]
    ])
    await message.answer("⚙️ <b>Система управления:</b>", reply_markup=kb, parse_mode="HTML")

# --- 💼 УВОЛЬНЕНИЕ ---
@dp.callback_query(F.data == "admin_fire")
async def start_fire(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите @ник или ID жителя для увольнения:", reply_markup=get_cancel_kb())
    await state.set_state(AppFSM.fire_target)
    await callback.answer()

@dp.message(AppFSM.fire_target)
async def exec_fire(message: Message, state: FSMContext):
    user_data = resolve_user(message.text)
    if not user_data:
        return await message.answer("❌ Житель не найден. Введите другой @ник:", reply_markup=get_cancel_kb())

    target_id = user_data[0]
    rp_name = get_user_name(target_id)

    conn = sqlite3.connect("svahuilsk.db")
    job = conn.execute("SELECT field_value FROM passport_fields WHERE user_id = ? AND field_name = 'Профессия'", (target_id,)).fetchone()

    if not job:
        conn.close()
        return await message.answer(f"⚠️ <b>{rp_name}</b> нигде не работает.", reply_markup=get_cancel_kb(), parse_mode="HTML")

    job_title = job[0]
    conn.execute("DELETE FROM passport_fields WHERE user_id = ? AND field_name = 'Профессия'", (target_id,))
    conn.commit()
    conn.close()

    await message.answer(f"✅ Вы успешно уволили <b>{rp_name}</b> с должности: <b>{job_title}</b>.", parse_mode="HTML")
    
    group_id = get_group_id()
    if group_id:
        mention = f'<a href="tg://user?id={target_id}">{rp_name}</a>'
        try:
            await bot.send_message(group_id, f"📢 <b>ОФИЦИАЛЬНОЕ УВОЛЬНЕНИЕ</b>\n\nВласти расторгли трудовой договор! Гражданин {mention} освобожден от должности: <b>{job_title}</b>.", parse_mode="HTML")
        except: pass

    await state.clear()

# --- 📢 ОФИЦИАЛЬНОЕ ПРИЗНАНИЕ ---
@dp.callback_query(F.data == "admin_recognize")
async def start_recognize(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите @ник или ID жителя:", reply_markup=get_cancel_kb())
    await state.set_state(AppFSM.recog_target)
    await callback.answer()

@dp.message(AppFSM.recog_target)
async def ask_recognize_status(message: Message, state: FSMContext):
    user_data = resolve_user(message.text)
    if not user_data: return await message.answer("❌ Не найден. Введите другой @ник:", reply_markup=get_cancel_kb())
    
    await state.update_data(target_id=user_data[0], target_name=get_user_name(user_data[0]))
    await message.answer(f"Кем объявляем {get_user_name(user_data[0])}?:", reply_markup=get_cancel_kb())
    await state.set_state(AppFSM.recog_status)

@dp.message(AppFSM.recog_status)
async def finish_recognize(message: Message, state: FSMContext):
    data = await state.get_data()
    status = message.text
    group_id = get_group_id()

    if group_id:
        mention = f'<a href="tg://user?id={data["target_id"]}">{data["target_name"]}</a>'
        try:
            await bot.send_message(group_id, f"🏛 <b>ОФИЦИАЛЬНОЕ ЗАЯВЛЕНИЕ ВЛАСТЕЙ!</b>\n\nАдминистрация Свахуильска публично признаёт гражданина {mention} как: <b>{status}</b>!", parse_mode="HTML")
            await message.answer("✅ Успешно объявлено в группе!")
        except: await message.answer("❌ Ошибка отправки в группу.")
    else: await message.answer("❌ Бот не знает ID группы.")
    await state.clear()

# --- 🚓 УПРАВЛЕНИЕ РОЗЫСКОМ ---
@dp.callback_query(F.data == "admin_wanted")
async def wanted_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Объявить в розыск", callback_data="wanted_add")],
        [InlineKeyboardButton(text="🟢 Очистить весь розыск", callback_data="wanted_clear")]
    ])
    await callback.message.edit_text("Управление федеральным розыском:", reply_markup=kb)

@dp.callback_query(F.data == "wanted_clear")
async def clear_wanted(callback: CallbackQuery):
    conn = sqlite3.connect("svahuilsk.db")
    conn.execute("DELETE FROM wanted")
    conn.commit()
    conn.close()
    await callback.message.edit_text("✅ База розыска полностью очищена!")

@dp.callback_query(F.data == "wanted_add")
async def add_wanted_name(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите @ник или Имя преступника:", reply_markup=get_cancel_kb())
    await state.set_state(AppFSM.wanted_target)
    await callback.answer()

@dp.message(AppFSM.wanted_target)
async def add_wanted_reason(message: Message, state: FSMContext):
    await state.update_data(target_name=message.text)
    await message.answer("Укажите причину (статью) розыска:", reply_markup=get_cancel_kb())
    await state.set_state(AppFSM.wanted_reason)

@dp.message(AppFSM.wanted_reason)
async def finish_wanted(message: Message, state: FSMContext):
    data = await state.get_data()
    conn = sqlite3.connect("svahuilsk.db")
    conn.execute("INSERT INTO wanted (username, reason) VALUES (?, ?)", (data["target_name"], message.text))
    conn.commit()
    conn.close()
    await message.answer(f"✅ {data['target_name']} официально объявлен в розыск!")
    await state.clear()

# --- 🪪 ЦИКЛИЧНЫЙ ПАСПОРТ ---
def get_passport_edit_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Имя", callback_data="passbtn_Имя"), InlineKeyboardButton(text="Фамилия", callback_data="passbtn_Фамилия")],
        [InlineKeyboardButton(text="Отчество", callback_data="passbtn_Отчество"), InlineKeyboardButton(text="Район", callback_data="passbtn_Район")],
        [InlineKeyboardButton(text="Профессия", callback_data="passbtn_Профессия"), InlineKeyboardButton(text="Брак", callback_data="passbtn_Брак")],
        [InlineKeyboardButton(text="Награды", callback_data="passbtn_Награды"), InlineKeyboardButton(text="➕ Свое поле", callback_data="passbtn_custom")],
        [InlineKeyboardButton(text="✅ Завершить редактирование", callback_data="cancel")]
    ])

@dp.callback_query(F.data == "admin_edit_pass")
async def req_pass_target(callback: CallbackQuery, state: FSMContext):
    msg = await callback.message.answer("Введите @ник или ID пользователя:", reply_markup=get_cancel_kb())
    await state.update_data(msgs_to_del=[msg.message_id])
    await state.set_state(AppFSM.pass_target)
    await callback.answer()

@dp.message(AppFSM.pass_target)
async def show_pass_fields(message: Message, state: FSMContext):
    data = await state.get_data()
    msgs = data.get('msgs_to_del', [])
    msgs.append(message.message_id)

    user_data = resolve_user(message.text)
    if not user_data:
        msg = await message.answer("❌ Житель не найден. Введите @ник или ID снова:", reply_markup=get_cancel_kb())
        msgs.append(msg.message_id)
        return await state.update_data(msgs_to_del=msgs)

    rp_name = get_user_name(user_data[0])
    await state.update_data(target_id=user_data[0], target_name=rp_name)
    
    msg = await message.answer(f"Редактируем паспорт: <b>{rp_name}</b>\nВыберите поле:", reply_markup=get_passport_edit_kb(), parse_mode="HTML")
    msgs.append(msg.message_id)
    await state.update_data(msgs_to_del=msgs)
    await state.set_state(AppFSM.pass_field_selection)

@dp.callback_query(F.data.startswith("passbtn_"))
async def process_pass_btn(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[1]
    data = await state.get_data()
    msgs = data.get('msgs_to_del', [])

    if not data.get('target_id'): return await state.clear()

    if field == "custom":
        msg = await callback.message.answer("Введите НАЗВАНИЕ поля:", reply_markup=get_cancel_kb())
        msgs.append(msg.message_id)
        await state.set_state(AppFSM.pass_custom_field)
    else:
        await state.update_data(field=field)
        msg = await callback.message.answer(f"Введите ЗНАЧЕНИЕ для: <b>{field}</b>\n<i>(Напишите '-', чтобы удалить поле)</i>:", reply_markup=get_cancel_kb(), parse_mode="HTML")
        msgs.append(msg.message_id)
        await state.set_state(AppFSM.pass_value)
    
    await state.update_data(msgs_to_del=msgs)
    await callback.answer()

@dp.message(AppFSM.pass_custom_field)
async def custom_field_name(message: Message, state: FSMContext):
    data = await state.get_data()
    msgs = data.get('msgs_to_del', [])
    msgs.append(message.message_id)

    await state.update_data(field=message.text)
    msg = await message.answer(f"Введите ЗНАЧЕНИЕ для: <b>{message.text}</b>:", reply_markup=get_cancel_kb(), parse_mode="HTML")
    msgs.append(msg.message_id)
    await state.update_data(msgs_to_del=msgs)
    await state.set_state(AppFSM.pass_value)

@dp.message(AppFSM.pass_value)
async def save_pass(message: Message, state: FSMContext):
    data = await state.get_data()
    msgs = data.get('msgs_to_del', [])
    msgs.append(message.message_id)

    target_id = data.get('target_id')
    field = data.get('field')
    value = message.text

    conn = sqlite3.connect("svahuilsk.db")
    conn.execute("DELETE FROM passport_fields WHERE user_id = ? AND field_name = ?", (target_id, field))
    
    if value != "-":
        conn.execute("INSERT INTO passport_fields (user_id, field_name, field_value) VALUES (?, ?, ?)", (target_id, field, value))
        
    conn.commit()
    conn.close()

    for m_id in msgs:
        try: await bot.delete_message(message.chat.id, m_id)
        except: pass
        
    rp_name = get_user_name(target_id)
    msg = await message.answer(f"✅ Успешно {'удалено' if value == '-' else 'записано'}: <b>{field}</b>\n\nЧто еще заполним для <b>{rp_name}</b>?", reply_markup=get_passport_edit_kb(), parse_mode="HTML")
    await state.update_data(msgs_to_del=[msg.message_id], target_name=rp_name)
    await state.set_state(AppFSM.pass_field_selection)

# --- ⚖️ МОДЕРАЦИЯ (ПО НИКУ) ---
@dp.callback_query(F.data == "admin_mod")
async def req_mod_target(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите @ник или ID нарушителя:", reply_markup=get_cancel_kb())
    await state.set_state(AppFSM.mod_target)
    await callback.answer()

@dp.message(AppFSM.mod_target)
async def req_mod_action(message: Message, state: FSMContext):
    user_data = resolve_user(message.text)
    if not user_data: return await message.answer("❌ Житель не найден. Введите другой @ник:", reply_markup=get_cancel_kb())

    await state.update_data(target_id=user_data[0])
    rp_name = get_user_name(user_data[0])
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔇 Мут 15 мин", callback_data="domod_mute_900"), InlineKeyboardButton(text="🔇 Мут 1 час", callback_data="domod_mute_3600")],
        [InlineKeyboardButton(text="🔇 Мут 1 день", callback_data="domod_mute_86400")],
        [InlineKeyboardButton(text="⛔️ БАН", callback_data="domod_ban"), InlineKeyboardButton(text="🕊 Разбан", callback_data="domod_unban")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    await message.answer(f"Что делаем с {rp_name}?", reply_markup=kb)

@dp.callback_query(F.data.startswith("domod_"))
async def exec_mod(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    target_id = int(data['target_id'])
    action = callback.data.split("_")
    group_id = get_group_id()

    if not group_id: return await callback.message.answer("❌ Бот не знает ID группы!")

    try:
        if action[1] == "mute":
            duration = int(action[2])
            await bot.restrict_chat_member(group_id, target_id, permissions={}, until_date=int(time.time()) + duration)
            await callback.message.edit_text(f"✅ Пользователь замучен на {duration // 60} минут.")
        elif action[1] == "ban":
            await bot.ban_chat_member(group_id, target_id)
            await callback.message.edit_text("✅ Нарушитель депортирован (БАН).")
        elif action[1] == "unban":
            await bot.unban_chat_member(group_id, target_id, only_if_banned=True)
            await callback.message.edit_text("✅ Пользователь помилован (Разбан).")
    except Exception as e: await callback.message.answer(f"❌ Ошибка. Бот админ? Ошибка: {e}")
    await state.clear()

# --- СИСТЕМНОЕ ---
@dp.message()
async def catch_all(message: Message):
    if message.from_user and not message.from_user.is_bot:
        get_or_create_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    
    if message.chat.type in ["group", "supergroup"]:
        conn = sqlite3.connect("svahuilsk.db")
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('group_id', ?)", (str(message.chat.id),))
        conn.commit()
        conn.close()

async def main():
    init_db()
    print("Свахуильск V6.3 Запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

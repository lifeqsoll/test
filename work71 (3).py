import logging
import sqlite3
from random import choice
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Токен вашего бота от @BotFather
BOT_TOKEN = "8466230710:AAHcjNHexZeab-TKlm2p2_hQ0oqxL3ogXVA"

# ========== РАБОТА С БАЗОЙ ДАННЫХ ==========

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()

    # Таблица пользователей
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    ''')

    # Таблица артов
    cur.execute('''
        CREATE TABLE IF NOT EXISTS arts (
            art_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            file_id TEXT,
            caption TEXT,
            likes INTEGER DEFAULT 0,
            dislikes INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES users (user_id)
        )
    ''')

    # Таблица реакций (лайки/дизлайки)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reactions (
            reaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            art_id INTEGER,
            type TEXT, -- 'like' или 'dislike'
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (art_id) REFERENCES arts (art_id),
            UNIQUE(user_id, art_id) -- чтобы нельзя было лайкнуть дважды
        )
    ''')

    # Таблица комментариев
    cur.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            art_id INTEGER,
            text TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (art_id) REFERENCES arts (art_id)
        )
    ''')

    conn.commit()
    conn.close()

def add_user(user_id, username):
    """Добавление пользователя в базу"""
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute(
        'INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)',
        (user_id, username)
    )
    conn.commit()
    conn.close()

def add_art(user_id, file_id, caption=""):
    """Добавление арта в базу"""
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO arts (owner_id, file_id, caption) VALUES (?, ?, ?)',
        (user_id, file_id, caption)
    )
    art_id = cur.lastrowid
    conn.commit()
    conn.close()
    return art_id

def get_unseen_art(user_id):
    """Получение случайного арта, который пользователь еще не оценивал"""
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    
    # Ищем арты, на которые у пользователя нет реакции
    cur.execute('''
        SELECT art_id, file_id, caption, likes, dislikes 
        FROM arts 
        WHERE art_id NOT IN (
            SELECT art_id FROM reactions WHERE user_id = ?
        ) AND owner_id != ?
        ORDER BY RANDOM()
        LIMIT 1
    ''', (user_id, user_id))
    
    art = cur.fetchone()
    conn.close()
    return art

def add_reaction(user_id, art_id, reaction_type):
    """Добавление реакции (лайк/дизлайк)"""
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    
    # Добавляем реакцию
    cur.execute(
        'INSERT INTO reactions (user_id, art_id, type) VALUES (?, ?, ?)',
        (user_id, art_id, reaction_type)
    )
    
    # Обновляем счетчик в таблице arts
    if reaction_type == 'like':
        cur.execute('UPDATE arts SET likes = likes + 1 WHERE art_id = ?', (art_id,))
    else:
        cur.execute('UPDATE arts SET dislikes = dislikes + 1 WHERE art_id = ?', (art_id,))
    
    conn.commit()
    conn.close()

def add_comment(user_id, art_id, text):
    """Добавление комментария"""
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO comments (user_id, art_id, text) VALUES (?, ?, ?)',
        (user_id, art_id, text)
    )
    conn.commit()
    conn.close()

def get_user_arts(user_id):
    """Получение всех артов пользователя"""
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute('''
        SELECT art_id, file_id, caption, likes, dislikes 
        FROM arts 
        WHERE owner_id = ? 
        ORDER BY timestamp DESC
    ''', (user_id,))
    arts = cur.fetchall()
    conn.close()
    return arts

def get_user_stats(user_id):
    """Получение статистики пользователя"""
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    
    # Количество артов пользователя
    cur.execute('SELECT COUNT(*) FROM arts WHERE owner_id = ?', (user_id,))
    arts_count = cur.fetchone()[0]
    
    # Общее количество лайков
    cur.execute('SELECT SUM(likes) FROM arts WHERE owner_id = ?', (user_id,))
    total_likes = cur.fetchone()[0] or 0
    
    # Общее количество дизлайков
    cur.execute('SELECT SUM(dislikes) FROM arts WHERE owner_id = ?', (user_id,))
    total_dislikes = cur.fetchone()[0] or 0
    
    conn.close()
    return arts_count, total_likes, total_dislikes

async def send_art_to_user(chat_id, context, user_id, art_data=None):
    """Отправка арта пользователю (новый или следующий)"""
    if not art_data:
        art_data = get_unseen_art(user_id)
    
    if art_data:
        art_id, file_id, caption, likes, dislikes = art_data
        context.user_data['current_art_id'] = art_id
        
        text = f"Лайков: {likes} | Дизлайков: {dislikes}"
        if caption:
            text = f"{caption}\n\n{text}"
        
        keyboard = [
            [
                InlineKeyboardButton("❤️", callback_data='like'),
                InlineKeyboardButton("👎", callback_data='dislike')
            ],
            [InlineKeyboardButton("💬 Комментарий", callback_data='comment')],
            [InlineKeyboardButton("👤 Профиль", callback_data='profile')],
            [InlineKeyboardButton("➡️ Следующий арт", callback_data='next_art')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=file_id,
            caption=text,
            reply_markup=reply_markup
        )
        return True
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎉 Вы просмотрели все доступные арты! Загляните позже или загрузите свои работы."
        )
        return False

# ========== КОМАНДЫ БОТА ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    add_user(user.id, user.username)
    
    keyboard = [
        [InlineKeyboardButton("🎨 Загрузить арт", callback_data='upload_art')],
        [InlineKeyboardButton("👀 Смотреть арты", callback_data='view_arts')],
        [InlineKeyboardButton("👤 Мой профиль", callback_data='profile')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Привет, {user.mention_html()}! Добро пожаловать в арт-сообщество!\n\n"
        "Здесь ты можешь делиться своими работами и оценивать творчество других.",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == 'upload_art':
        await query.edit_message_text(
            "Отправь мне свое изображение (как фото или документ) с подписью (если хочешь)."
        )
        context.user_data['waiting_for_art'] = True
        
    elif data == 'view_arts':
        art = get_unseen_art(user_id)
        if art:
            await send_art_to_user(query.message.chat_id, context, user_id, art)
            await query.delete_message()  # Удаляем старое сообщение
        else:
            await query.edit_message_text("Пока нет артов для оценки! Попробуй позже.")
    
    elif data in ['like', 'dislike']:
        art_id = context.user_data.get('current_art_id')
        if art_id:
            add_reaction(user_id, art_id, data)
            
            # Автоматически показываем следующий арт
            next_art = get_unseen_art(user_id)
            if next_art:
                await send_art_to_user(query.message.chat_id, context, user_id, next_art)
                await query.delete_message()  # Удаляем старое сообщение
            else:
                await query.edit_message_text(
                    "🎉 Вы просмотрели все доступные арты! Загляните позже."
                )
        else:
            await query.edit_message_text("Ошибка! Попробуй другой арт.")
    
    elif data == 'comment':
        await query.edit_message_text("Напиши свой комментарий или совет:")
        context.user_data['waiting_for_comment'] = True
    
    elif data == 'next_art':
        art = get_unseen_art(user_id)
        if art:
            await send_art_to_user(query.message.chat_id, context, user_id, art)
            await query.delete_message()  # Удаляем старое сообщение
        else:
            await query.edit_message_text("Больше нет новых артов! Загляни позже.")
    
    elif data == 'profile':
        arts_count, total_likes, total_dislikes = get_user_stats(user_id)
        user_arts = get_user_arts(user_id)
        
        if user_arts:
            # Показываем последний арт пользователя с навигацией
            current_art_index = context.user_data.get('profile_art_index', 0)
            art_id, file_id, caption, likes, dislikes = user_arts[current_art_index]
            
            profile_text = (
                f"👤 Твой профиль:\n"
                f"📊 Артов: {arts_count}\n"
                f"❤️ Лайков: {total_likes}\n"
                f"👎 Дизлайков: {total_dislikes}\n\n"
                f"Арт {current_art_index + 1}/{len(user_arts)}"
            )
            
            if caption:
                profile_text += f"\n\n{caption}"
            
            keyboard = []
            if len(user_arts) > 1:
                keyboard.append([
                    InlineKeyboardButton("⬅️", callback_data='prev_art'),
                    InlineKeyboardButton(f"{current_art_index + 1}/{len(user_arts)}", callback_data='profile_stats'),
                    InlineKeyboardButton("➡️", callback_data='next_art_profile')
                ])
            
            keyboard.extend([
                [InlineKeyboardButton("👀 Смотреть арты", callback_data='view_arts')],
                [InlineKeyboardButton("🎨 Загрузить новый арт", callback_data='upload_art')],
                [InlineKeyboardButton("📊 Общая статистика", callback_data='profile_stats')]
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=file_id,
                caption=profile_text,
                reply_markup=reply_markup
            )
            await query.delete_message()
        else:
            await query.edit_message_text(
                f"👤 Твой профиль:\n"
                f"📊 Артов: 0\n"
                f"❤️ Лайков: 0\n"
                f"👎 Дизлайков: 0\n\n"
                "У тебя пока нет артов. Загрузи первый!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎨 Загрузить арт", callback_data='upload_art')],
                    [InlineKeyboardButton("👀 Смотреть арты", callback_data='view_arts')]
                ])
            )
    
    elif data in ['next_art_profile', 'prev_art']:
        user_arts = get_user_arts(user_id)
        if user_arts:
            current_index = context.user_data.get('profile_art_index', 0)
            
            if data == 'next_art_profile' and current_index < len(user_arts) - 1:
                current_index += 1
            elif data == 'prev_art' and current_index > 0:
                current_index -= 1
            
            context.user_data['profile_art_index'] = current_index
            art_id, file_id, caption, likes, dislikes = user_arts[current_index]
            
            arts_count, total_likes, total_dislikes = get_user_stats(user_id)
            profile_text = (
                f"👤 Твой профиль:\n"
                f"📊 Артов: {arts_count}\n"
                f"❤️ Лайков: {total_likes}\n"
                f"👎 Дизлайков: {total_dislikes}\n\n"
                f"Арт {current_index + 1}/{len(user_arts)}\n"
                f"❤️ {likes} | 👎 {dislikes}"
            )
            
            if caption:
                profile_text += f"\n\n{caption}"
            
            keyboard = []
            if len(user_arts) > 1:
                keyboard.append([
                    InlineKeyboardButton("⬅️", callback_data='prev_art'),
                    InlineKeyboardButton(f"{current_index + 1}/{len(user_arts)}", callback_data='profile_stats'),
                    InlineKeyboardButton("➡️", callback_data='next_art_profile')
                ])
            
            keyboard.extend([
                [InlineKeyboardButton("👀 Смотреть арты", callback_data='view_arts')],
                [InlineKeyboardButton("🎨 Загрузить новый арт", callback_data='upload_art')]
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_media(
                media=InputMediaPhoto(media=file_id, caption=profile_text),
                reply_markup=reply_markup
            )
    
    elif data == 'profile_stats':
        arts_count, total_likes, total_dislikes = get_user_stats(user_id)
        await query.edit_message_text(
            f"📊 Твоя статистика:\n\n"
            f"🎨 Артов: {arts_count}\n"
            f"❤️ Всего лайков: {total_likes}\n"
            f"👎 Всего дизлайков: {total_dislikes}\n"
            f"📈 Рейтинг: {total_likes - total_dislikes}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👈 Назад к профилю", callback_data='profile')],
                [InlineKeyboardButton("👀 Смотреть арты", callback_data='view_arts')]
            ])
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений и медиа"""
    user_id = update.effective_user.id
    
    if context.user_data.get('waiting_for_art'):
        # Пользователь загружает арт
        if update.message.photo or update.message.document:
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
            else:
                file_id = update.message.document.file_id
            
            caption = update.message.caption or ""
            art_id = add_art(user_id, file_id, caption)
            
            context.user_data['waiting_for_art'] = False
            await update.message.reply_text(
                "Твой арт успешно добавлен! 🎨\n"
                "Теперь другие пользователи смогут его оценить!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👀 Смотреть арты", callback_data='view_arts')],
                    [InlineKeyboardButton("👤 Мой профиль", callback_data='profile')]
                ])
            )
        else:
            await update.message.reply_text("Пожалуйста, отправь изображение!")
    
    elif context.user_data.get('waiting_for_comment'):
        # Пользователь пишет комментарий
        art_id = context.user_data.get('current_art_id')
        if art_id and update.message.text:
            add_comment(user_id, art_id, update.message.text)
            context.user_data['waiting_for_comment'] = False
            
            # После комментария показываем следующий арт
            next_art = get_unseen_art(user_id)
            if next_art:
                await send_art_to_user(update.message.chat_id, context, user_id, next_art)
            else:
                await update.message.reply_text(
                    "🎉 Вы просмотрели все арты! Загляните позже.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("👤 Мой профиль", callback_data='profile')],
                        [InlineKeyboardButton("🎨 Загрузить арт", callback_data='upload_art')]
                    ])
                )
        else:
            await update.message.reply_text("Ошибка! Попробуй снова.")

def main():
    """Запуск бота"""
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.ALL, handle_message))
    
    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
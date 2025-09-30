import logging
import sqlite3
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

def get_art_by_id(art_id):
    """Получение арта по ID"""
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute('''
        SELECT art_id, file_id, caption, likes, dislikes 
        FROM arts 
        WHERE art_id = ?
    ''', (art_id,))
    art = cur.fetchone()
    conn.close()
    return art

def get_user_arts(user_id):
    """Получение всех артов пользователя"""
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    
    # Общая статистика
    cur.execute('''
        SELECT 
            COUNT(*) as total_arts,
            SUM(likes) as total_likes,
            SUM(dislikes) as total_dislikes
        FROM arts 
        WHERE owner_id = ?
    ''', (user_id,))
    
    stats = cur.fetchone()
    
    # Список артов с детальной статистикой
    cur.execute('''
        SELECT art_id, file_id, caption, likes, dislikes, timestamp
        FROM arts 
        WHERE owner_id = ?
        ORDER BY timestamp DESC
    ''', (user_id,))
    
    arts = cur.fetchall()
    conn.close()
    
    return stats, arts

async def send_art_to_user(chat_id, context, user_id, art=None):
    """Отправка арта пользователю"""
    if not art:
        art = get_unseen_art(user_id)
    
    if art:
        art_id, file_id, caption, likes, dislikes = art
        context.user_data['current_art_id'] = art_id
        
        text = f"Лайков: {likes} | Дизлайков: {dislikes}"
        if caption:
            text = f"{caption}\n\n{text}"
        
        keyboard = [
            [
                InlineKeyboardButton("❤️ Лайк", callback_data=f'like_{art_id}'),
                InlineKeyboardButton("👎 Дизлайк", callback_data=f'dislike_{art_id}')
            ],
            [InlineKeyboardButton("💬 Комментарий", callback_data=f'comment_{art_id}')],
            [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]
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
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎉 Вы оценили все доступные арты! Загляните позже или загрузите свои работы.",
            reply_markup=reply_markup
        )
        return False

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str):
    """Показать профиль пользователя со статистикой и артами в одном сообщении"""
    stats, arts = get_user_arts(user_id)
    total_arts, total_likes, total_dislikes = stats
    
    if not arts:
        # Если артов нет
        profile_text = (
            f"👤 **Профиль пользователя** {username or 'Без имени'}\n\n"
            "🎨 У вас пока нет загруженных артов.\n"
            "Нажмите 'Загрузить арт', чтобы добавить первый!"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                profile_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                profile_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        return
    
    # Создаем медиагруппу с артами
    media_group = []
    
    # Добавляем первый арт с текстом статистики
    first_art_id, first_file_id, first_caption, first_likes, first_dislikes, first_timestamp = arts[0]
    
    profile_text = (
        f"👤 **Профиль пользователя** {username or 'Без имени'}\n\n"
        f"📊 **Общая статистика:**\n"
        f"• 🎨 Загружено артов: {total_arts}\n"
        f"• ❤️ Всего лайков: {total_likes or 0}\n"
        f"• 👎 Всего дизлайков: {total_dislikes or 0}\n\n"
        f"📁 **Ваши арты ({len(arts)}):**\n"
    )
    
    # Текст для первого арта (с статистикой)
    first_art_text = profile_text + f"\n🎨 **Арт #1** (ID: {first_art_id})\n"
    first_art_text += f"❤️ Лайков: {first_likes} | 👎 Дизлайков: {first_dislikes}\n"
    if first_caption:
        first_art_text += f"📝 Описание: {first_caption}"
    
    media_group.append(InputMediaPhoto(
        media=first_file_id,
        caption=first_art_text,
        parse_mode='Markdown'
    ))
    
    # Добавляем остальные арты
    for i, (art_id, file_id, caption, likes, dislikes, timestamp) in enumerate(arts[1:], 2):
        art_text = f"🎨 **Арт #{i}** (ID: {art_id})\n"
        art_text += f"❤️ Лайков: {likes} | 👎 Дизлайков: {dislikes}\n"
        if caption:
            art_text += f"📝 Описание: {caption}"
        
        media_group.append(InputMediaPhoto(
            media=file_id,
            caption=art_text,
            parse_mode='Markdown'
        ))
    
    # Клавиатура с кнопкой "Назад"
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        # Удаляем предыдущее сообщение и отправляем новое с медиагруппой
        try:
            await update.callback_query.message.delete()
        except:
            pass
        
        # Отправляем медиагруппу
        messages = await context.bot.send_media_group(
            chat_id=update.callback_query.message.chat_id,
            media=media_group
        )
        
        # Отправляем кнопку "Назад" отдельным сообщением
        await context.bot.send_message(
            chat_id=update.callback_query.message.chat_id,
            text="⬆️ **Все ваши арты выше** ⬆️",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        # Отправляем медиагруппу
        messages = await context.bot.send_media_group(
            chat_id=update.message.chat_id,
            media=media_group
        )
        
        # Отправляем кнопку "Назад" отдельным сообщением
        await update.message.reply_text(
            "⬆️ **Все ваши арты выше** ⬆️",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

# ========== КОМАНДЫ БОТА ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    add_user(user.id, user.username)
    
    # Очищаем состояние пользователя
    context.user_data.clear()
    
    keyboard = [
        [InlineKeyboardButton("🎨 Загрузить арт", callback_data='upload_art')],
        [InlineKeyboardButton("👀 Смотреть арты", callback_data='view_arts')],
        [InlineKeyboardButton("👤 Профиль", callback_data='profile')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Если сообщение уже есть (callback), редактируем его, иначе отправляем новое
    if update.callback_query:
        await update.callback_query.edit_message_text(
            f"Привет, {user.mention_html()}! Добро пожаловать в арт-сообщество!\n\n"
            "Здесь ты можешь делиться своими работами и оценивать творчество других.",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    else:
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
    username = query.from_user.username or query.from_user.first_name
    data = query.data
    
    if data == 'upload_art':
        await query.edit_message_text(
            "📤 Отправь мне свое изображение (как фото) с подписью (если хочешь).\n\n"
            "После загрузки ты вернешься в главное меню."
        )
        context.user_data['waiting_for_art'] = True
        
    elif data == 'view_arts':
        # Отправляем первый арт
        success = await send_art_to_user(query.message.chat_id, context, user_id)
        if not success:
            await query.edit_message_text("Пока нет артов для оценки! Попробуй позже.")
    
    elif data == 'profile':
        # Показываем профиль пользователя с артами
        await show_profile(update, context, user_id, username)
    
    elif data.startswith('like_') or data.startswith('dislike_'):
        # Обработка лайков/дизлайков
        art_id = int(data.split('_')[1])
        reaction_type = 'like' if data.startswith('like_') else 'dislike'
        
        # Проверяем, не оценивал ли пользователь уже этот арт
        conn = sqlite3.connect('database.db')
        cur = conn.cursor()
        cur.execute('SELECT * FROM reactions WHERE user_id = ? AND art_id = ?', (user_id, art_id))
        existing_reaction = cur.fetchone()
        conn.close()
        
        if existing_reaction:
            # Пользователь уже оценивал этот арт
            await query.answer("Вы уже оценили этот арт! ❌", show_alert=True)
        else:
            # Добавляем реакцию
            add_reaction(user_id, art_id, reaction_type)
            
            # Показываем подтверждение (но не удаляем сообщение с артом)
            reaction_text = "❤️ Лайк" if reaction_type == 'like' else "👎 Дизлайк"
            await query.answer(f"{reaction_text} засчитан! ✅")
            
            # Отправляем следующий арт в новом сообщении (не удаляя предыдущий)
            await send_art_to_user(query.message.chat_id, context, user_id)
    
    elif data.startswith('comment_'):
        art_id = int(data.split('_')[1])
        context.user_data['waiting_for_comment'] = True
        context.user_data['comment_art_id'] = art_id
        
        await query.edit_message_text(
            f"💬 Напиши комментарий для этого арта:\n\n"
            "Просто отправь текст сообщения сюда."
        )
    
    elif data == 'back_to_menu':
        await start(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений и медиа"""
    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    
    if context.user_data.get('waiting_for_art'):
        # Пользователь загружает арт
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            caption = update.message.caption or ""
            
            # Добавляем арт в базу
            art_id = add_art(user_id, file_id, caption)
            
            # Сбрасываем состояние
            context.user_data['waiting_for_art'] = False
            
            # Показываем подтверждение и возвращаем в меню
            keyboard = [[InlineKeyboardButton("🔙 В главное меню", callback_data='back_to_menu')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ Твой арт успешно добавлен! (ID: {art_id})\n"
                "Теперь другие пользователи смогут его оценить!",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text("❌ Пожалуйста, отправь изображение как фото (не как документ)!")
    
    elif context.user_data.get('waiting_for_comment'):
        # Пользователь пишет комментарий
        art_id = context.user_data.get('comment_art_id')
        if art_id and update.message.text:
            # Добавляем комментарий
            add_comment(user_id, art_id, update.message.text)
            
            # Сбрасываем состояние
            context.user_data['waiting_for_comment'] = False
            context.user_data['comment_art_id'] = None
            
            # Показываем подтверждение
            await update.message.reply_text("✅ Комментарий успешно добавлен! 📝")
            
            # Возвращаем к просмотру артов
            await send_art_to_user(chat_id, context, user_id)
        else:
            await update.message.reply_text("❌ Ошибка! Попробуй написать комментарий снова.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик фотографий (для загрузки артов)"""
    user_id = update.effective_user.id
    
    if context.user_data.get('waiting_for_art'):
        file_id = update.message.photo[-1].file_id
        caption = update.message.caption or ""
        
        # Добавляем арт в базу
        art_id = add_art(user_id, file_id, caption)
        
        # Сбрасываем состояние
        context.user_data['waiting_for_art'] = False
        
        # Показываем подтверждение и возвращаем в меню
        keyboard = [[InlineKeyboardButton("🔙 В главное меню", callback_data='back_to_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ Твой арт успешно добавлен! (ID: {art_id})\n"
            "Теперь другие пользователи смогут его оценить!",
            reply_markup=reply_markup
        )

def main():
    """Запуск бота"""
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
    
import telebot
import psycopg2
import re
import threading
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import BOT_TOKEN, ADMIN_IDS

bot = telebot.TeleBot(BOT_TOKEN)
bot.set_my_commands([
    telebot.types.BotCommand('/start', 'Botni ishga tushirish'),
    telebot.types.BotCommand('/admin', 'Admin panel'),
    telebot.types.BotCommand('/done', 'Qoshishni tugatish'),
    telebot.types.BotCommand('/stats', 'Statistika'),
    telebot.types.BotCommand('/addep', 'Animega qism qoshish'),
])

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        user_id BIGINT UNIQUE,
        username TEXT,
        full_name TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS anime (
        id SERIAL PRIMARY KEY,
        anime_id INTEGER,
        title TEXT,
        genre TEXT,
        season INTEGER DEFAULT 1,
        episode INTEGER,
        video TEXT,
        category TEXT DEFAULT 'anime',
        status TEXT DEFAULT 'ongoing',
        poster TEXT,
        views INTEGER DEFAULT 0,
        UNIQUE(anime_id, season, episode)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS search_logs (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        anime_id INTEGER,
        searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def add_user(uid, uname, fname):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT INTO users (user_id, username, full_name) VALUES (%s,%s,%s) ON CONFLICT (user_id) DO NOTHING',
              (uid, uname or '', fname or ''))
    conn.commit()
    conn.close()

def is_new_user(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE user_id=%s', (uid,))
    r = c.fetchone()
    conn.close()
    return r is None

def log_search(uid, aid):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT INTO search_logs (user_id, anime_id) VALUES (%s,%s)', (uid, aid))
    c.execute('UPDATE anime SET views=views+1 WHERE anime_id=%s', (aid,))
    conn.commit()
    conn.close()

def get_next_id():
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT MAX(anime_id) FROM anime')
    r = c.fetchone()
    conn.close()
    return (r[0] or 0) + 1

def extract_episode(caption):
    if not caption:
        return None
    patterns = [
        r'\{[^}]*\}\s*(\d+)\s*/\s*\d+',
        r'(\d+)\s*/\s*\d+',
        r'[Qq]ism[:\s-]*(\d+)',
        r'[Ee]p(?:isode)?[:\s-]*(\d+)',
        r'(\d+)-qism',
        r'qism\s*(\d+)',
        r'\[(\d+)-qism\]',
        r'\[(\d+)\]',
    ]
    for p in patterns:
        m = re.search(p, caption, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if val <= 9999:
                return val
    nums = re.findall(r'\b(\d+)\b', caption)
    for n in nums:
        val = int(n)
        if 1 <= val <= 999:
            return val
    return None

def main_menu():
    kb = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add('🔍 Anime qidiruv', '🎬 Anime & Filmlar')
    kb.add('📺 Ongoing Animelar', '✅ Tugallangan')
    kb.add('📡 Seriallar', '🔴 Shorts')
    kb.add('⭐ Tavsiya etilganlar', '📚 Barcha animelar')
    kb.add('📞 Murojaat')
    return kb

def welcome_new_user(msg):
    text = (
        '🎭 <b>Assalomu alaykum!</b> 🎭\n\n'
        '🎬 <b>Anime & Kino Bot</b> ga xush kelibsiz!\n\n'
        '━━━━━━━━━━━━━━━━━\n'
        '🤖 <b>Bot nima qila oladi?</b>\n\n'
        '🔍 Anime va filmlarni qidirish\n'
        '📺 Onlayn tomosha qilish\n'
        '🎞 Fasl va qismlar bo\'yicha ko\'rish\n'
        '⭐ Eng mashhur animeni topish\n'
        '━━━━━━━━━━━━━━━━━\n\n'
        '📢 Kanal: https://t.me/animelarr_uzbekcha\n'
        '👤 Admin: @g1yu_tamioka\n\n'
        '👇 Quyidagi menyudan foydalaning!'
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_menu(), parse_mode='HTML')

def show_anime_info(chat_id, anime_id, uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT title, genre, status, poster, views FROM anime WHERE anime_id=%s LIMIT 1', (anime_id,))
    row = c.fetchone()
    if not row:
        bot.send_message(chat_id, '❌ Anime topilmadi!')
        conn.close()
        return
    title, genre, status, poster, views = row
    c.execute('SELECT COUNT(*) FROM anime WHERE anime_id=%s', (anime_id,))
    total_eps = c.fetchone()[0]
    c.execute('SELECT DISTINCT season FROM anime WHERE anime_id=%s ORDER BY season', (anime_id,))
    seasons = c.fetchall()
    conn.close()
    log_search(uid, anime_id)

    st = '✅ Tugallangan' if status == 'completed' else '🔄 Ongoing'

    if len(seasons) == 1:
        show_episodes(chat_id, anime_id, seasons[0][0], title, genre, st, views, total_eps, poster)
        return

    kb = telebot.types.InlineKeyboardMarkup(row_width=3)
    btns = []
    for s in seasons:
        sn = s[0]
        lbl = '🎬 OVA' if sn == 0 else f'📺 {sn}-fasl'
        btns.append(telebot.types.InlineKeyboardButton(lbl, callback_data=f'season:{anime_id}:{sn}'))
    kb.add(*btns)

    text = (
        f'❀ ── ·  ·  ── ❀\n'
        f'        ✨ <b>{title}</b> ✨\n'
        f'❀ ── ·  ·  ── ❀\n\n'
        f'✏️ <b>Janr :</b> {genre or "Nomalum"}\n'
        f'📊 <b>Holat :</b> {st}\n'
        f'🎬 <b>Qismlar soni :</b> {total_eps}\n'
        f'👁 <b>Qidirishlar soni :</b> {views}\n\n'
        f'📂 <b>Faslni tanlang:</b>'
    )
    if poster:
        bot.send_photo(chat_id, poster, caption=text, reply_markup=kb, parse_mode='HTML')
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode='HTML')

def show_episodes(chat_id, anime_id, season, title=None, genre=None, st=None, views=None, total_eps=None, poster=None):
    conn = get_conn()
    c = conn.cursor()
    if not title:
        c.execute('SELECT title, genre, status, poster, views FROM anime WHERE anime_id=%s LIMIT 1', (anime_id,))
        info = c.fetchone()
        if not info:
            bot.send_message(chat_id, '❌ Topilmadi!')
            conn.close()
            return
        title, genre, status, poster, views = info
        st = '✅ Tugallangan' if status == 'completed' else '🔄 Ongoing'
        c.execute('SELECT COUNT(*) FROM anime WHERE anime_id=%s', (anime_id,))
        total_eps = c.fetchone()[0]

    c.execute('SELECT episode FROM anime WHERE anime_id=%s AND season=%s ORDER BY episode', (anime_id, season))
    eps = c.fetchall()
    conn.close()

    if not eps:
        bot.send_message(chat_id, '❌ Qismlar topilmadi!')
        return

    kb = telebot.types.InlineKeyboardMarkup(row_width=5)
    btns = [telebot.types.InlineKeyboardButton(
        str(e[0]), callback_data=f'ep:{anime_id}:{season}:{e[0]}') for e in eps]
    kb.add(*btns)
    kb.add(telebot.types.InlineKeyboardButton('📥 Yuklash (1-' + str(len(eps)) + ')', callback_data=f'dl:{anime_id}:{season}'))
    kb.add(telebot.types.InlineKeyboardButton('❌ Yopish', callback_data='close'))

    sl = 'OVA' if season == 0 else f'{season}-fasl'

    text = (
        f'❀ ── ·  ·  ── ❀\n'
        f'        ✨ <b>{title}</b> ✨\n'
        f'❀ ── ·  ·  ── ❀\n\n'
        f'✏️ <b>Janr :</b> {genre or "Nomalum"}\n'
        f'📊 <b>Holat :</b> {st}\n'
        f'🎬 <b>Qismlar soni :</b> {total_eps}\n'
        f'👁 <b>Qidirishlar soni :</b> {views}\n\n'
        f'📺 <b>{sl}</b> — Qismni tanlang:'
    )
    if poster:
        bot.send_photo(chat_id, poster, caption=text, reply_markup=kb, parse_mode='HTML')
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode='HTML')

def show_list(chat_id, header, rows):
    if not rows:
        bot.send_message(chat_id, '📭 Hozircha bu toifada kontent yoq.')
        return
    bot.send_message(chat_id, f'<b>{header}</b>', parse_mode='HTML')
    for row in rows:
        kb = telebot.types.InlineKeyboardMarkup()
        kb.add(telebot.types.InlineKeyboardButton('🎬 Tomosha qilish', callback_data=f'show:{row[0]}'))
        bot.send_message(chat_id, f'✨ <b>{row[1]}</b>\n🆔 Kod: {row[0]}',
                         reply_markup=kb, parse_mode='HTML')

def show_stats_msg(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    u = c.fetchone()[0]
    c.execute('SELECT COUNT(DISTINCT anime_id) FROM anime')
    a = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM anime')
    e = c.fetchone()[0]
    c.execute('''SELECT a.title, COUNT(s.id) as cnt FROM search_logs s
                 JOIN anime a ON s.anime_id=a.anime_id
                 GROUP BY s.anime_id, a.title ORDER BY cnt DESC LIMIT 5''')
    top = c.fetchall()
    conn.close()
    text = (
        f'📊 <b>Statistika</b>\n\n'
        f'👥 Foydalanuvchilar: {u}\n'
        f'🎬 Animelar: {a}\n'
        f'📺 Jami qismlar: {e}\n\n'
        f'🔥 Eng ko\'p ko\'rilgan:\n'
    )
    for i, (t, cnt) in enumerate(top, 1):
        text += f'{i}. {t} — {cnt} marta\n'
    bot.send_message(chat_id, text, parse_mode='HTML')

def send_channel_post(chat_id, aid, title, genre, status, poster):
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM anime WHERE anime_id=%s', (aid,))
        cnt = c.fetchone()[0]
        conn.close()
        username = bot.get_me().username
        st = '✅ Tugallangan' if status == 'completed' else '🔄 Ongoing'
        link = f'https://t.me/{username}?start={aid}'
        CHANNEL = '@animelarr_uzbekcha'
        kb = telebot.types.InlineKeyboardMarkup()
        kb.add(telebot.types.InlineKeyboardButton('✨ Tomosha qilish ✨', url=link))
        text = (
            f'✦ ──────────────── ✦\n'
            f'🎬 <b>{title}</b>\n'
            f'✦ ──────────────── ✦\n\n'
            f'✏️ <b>Janr:</b> {genre or "Nomalum"}\n'
            f'📊 <b>Holat:</b> {st}\n'
            f'🎞 <b>Qismlar soni:</b> {cnt}\n'
            f'🌐 <b>Tili:</b> O\'zbek tilida\n\n'
            f'✦ ──────────────── ✦\n'
            f'📢 @animelarr_uzbekcha'
        )
        if poster:
            bot.send_photo(CHANNEL, poster, caption=text, reply_markup=kb, parse_mode='HTML')
        else:
            bot.send_message(CHANNEL, text, reply_markup=kb, parse_mode='HTML')
    except Exception as e:
        bot.send_message(chat_id, f'⚠️ Kanalga post yuborilmadi: {e}')

# ─── HANDLERS ───────────────────────────────────────────────

@bot.message_handler(commands=['start'])
def start(msg):
    new = is_new_user(msg.from_user.id)
    add_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    args = msg.text.split()
    if len(args) > 1:
        try:
            show_anime_info(msg.chat.id, int(args[1]), msg.from_user.id)
            return
        except:
            pass
    if new:
        welcome_new_user(msg)
    else:
        bot.send_message(msg.chat.id,
                         f'🎬 Xush kelibsiz <b>{msg.from_user.first_name}</b>!\n\nMenyudan foydalaning:',
                         reply_markup=main_menu(), parse_mode='HTML')

@bot.message_handler(commands=['stats'])
def stats_cmd(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    show_stats_msg(msg.chat.id)

@bot.message_handler(commands=['addep'])
def addep_cmd(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    args = msg.text.split()
    if len(args) < 2:
        bot.send_message(msg.chat.id, '📝 Ishlatish: /addep <anime_id>\nMasalan: /addep 1')
        return
    try:
        aid = int(args[1])
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT title, genre, category, status FROM anime WHERE anime_id=%s LIMIT 1', (aid,))
        row = c.fetchone()
        conn.close()
        if not row:
            bot.send_message(msg.chat.id, '❌ Bu ID da anime topilmadi!')
            return
        title, genre, category, status = row
        user_states[msg.from_user.id] = {
            'step': 'addep_season',
            'anime_id': aid,
            'title': title,
            'genre': genre,
            'category': category,
            'status': status,
        }
        bot.send_message(msg.chat.id,
                         f'✅ <b>{title}</b> animesiga qism qo\'shish\n\n📺 Nechanchi faslga? (OVA uchun 0):',
                         parse_mode='HTML')
    except:
        bot.send_message(msg.chat.id, '❌ Faqat raqam kiriting!')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'addep_season')
def addep_season(msg):
    try:
        season = int(msg.text.strip())
        user_states[msg.from_user.id]['season'] = season
        user_states[msg.from_user.id]['step'] = 'waiting_video'
        sl = 'OVA' if season == 0 else f'{season}-fasl'
        bot.send_message(msg.chat.id, f'✅ {sl} tanlandi!\n\n📤 Videolarni yuboring!\nTugatgach /done yozing.')
    except:
        bot.send_message(msg.chat.id, '❌ Faqat raqam kiriting!')

@bot.callback_query_handler(func=lambda c: c.data.startswith('season:'))
def season_cb(call):
    _, aid, sn = call.data.split(':')
    show_episodes(call.message.chat.id, int(aid), int(sn))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('ep:'))
def ep_cb(call):
    parts = call.data.split(':')
    aid, sn, ep = int(parts[1]), int(parts[2]), int(parts[3])
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT title, video FROM anime WHERE anime_id=%s AND season=%s AND episode=%s', (aid, sn, ep))
    row = c.fetchone()
    conn.close()
    if row and row[1]:
        sl = 'OVA' if sn == 0 else f'{sn}-fasl'
        bot.send_video(call.message.chat.id, row[1],
                       caption=f'🎬 <b>{row[0]}</b>\n📺 {sl} {ep}-qism',
                       parse_mode='HTML')
        bot.answer_callback_query(call.id)
    else:
        bot.answer_callback_query(call.id, '❌ Video topilmadi!', show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith('dl:'))
def dl_cb(call):
    parts = call.data.split(':')
    aid, sn = int(parts[1]), int(parts[2])
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT episode, video FROM anime WHERE anime_id=%s AND season=%s ORDER BY episode', (aid, sn))
    rows = c.fetchall()
    conn.close()
    bot.answer_callback_query(call.id, '📥 Yuklanmoqda...', show_alert=False)
    for ep, vid in rows:
        sl = 'OVA' if sn == 0 else f'{sn}-fasl'
        try:
            bot.send_video(call.message.chat.id, vid,
                           caption=f'📥 {sl} {ep}-qism',
                           parse_mode='HTML')
            time.sleep(0.3)
        except:
            pass

@bot.callback_query_handler(func=lambda c: c.data == 'close')
def close_cb(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('show:'))
def show_cb(call):
    show_anime_info(call.message.chat.id, int(call.data.split(':')[1]), call.from_user.id)
    bot.answer_callback_query(call.id)

user_states = {}

@bot.message_handler(commands=['admin'])
def admin_panel(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    u = c.fetchone()[0]
    c.execute('SELECT COUNT(DISTINCT anime_id) FROM anime')
    a = c.fetchone()[0]
    conn.close()
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton('➕ Kontent qoshish', callback_data='add_anime'))
    kb.add(telebot.types.InlineKeyboardButton('🖼 Poster qoshish', callback_data='add_poster'))
    kb.add(telebot.types.InlineKeyboardButton('🗑 Kontent ochirish', callback_data='del_anime'))
    kb.add(telebot.types.InlineKeyboardButton('📊 Statistika', callback_data='stats'))
    bot.send_message(msg.chat.id,
                     f'👑 <b>Admin Panel</b>\n\n👥 Foydalanuvchilar: {u}\n🎬 Animelar: {a}',
                     reply_markup=kb, parse_mode='HTML')

@bot.callback_query_handler(func=lambda c: c.data == 'stats')
def stats_cb(call):
    if call.from_user.id not in ADMIN_IDS:
        return
    show_stats_msg(call.message.chat.id)
    bot.answer_callback_query(call.id)

# ─── KONTENT QO'SHISH — YANGI TARTIB ────────────────────────
# 1. Avval toifa tanlanadi
# 2. Keyin nom va janr so'raladi
# 3. Toifaga qarab fasl/OVA yoki yo'q
# 4. Poster ixtiyoriy so'raladi
# 5. Video yuboriladi

@bot.callback_query_handler(func=lambda c: c.data == 'add_anime')
def add_anime_cb(call):
    if call.from_user.id not in ADMIN_IDS:
        return
    user_states[call.from_user.id] = {'step': 'category', 'anime_id': get_next_id()}
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton('🎬 Film', callback_data='cat:film'))
    kb.add(telebot.types.InlineKeyboardButton('📺 Ongoing', callback_data='cat:ongoing'))
    kb.add(telebot.types.InlineKeyboardButton('✅ Tugallangan', callback_data='cat:completed'))
    kb.add(telebot.types.InlineKeyboardButton('📡 Serial', callback_data='cat:serial'))
    kb.add(telebot.types.InlineKeyboardButton('🔴 Shorts', callback_data='cat:shorts'))
    bot.send_message(call.message.chat.id, '📂 Avval toifani tanlang:', reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('cat:') and c.from_user.id in user_states and user_states[c.from_user.id].get('step') == 'category')
def get_category(call):
    cat = call.data.split(':')[1]
    status = 'completed' if cat in ['completed', 'film'] else 'ongoing'
    user_states[call.from_user.id]['category'] = cat
    user_states[call.from_user.id]['status'] = status

    if cat == 'shorts':
        # Shorts uchun faqat nom so'raladi
        user_states[call.from_user.id]['step'] = 'title'
        user_states[call.from_user.id]['shorts_mode'] = True
        bot.send_message(call.message.chat.id, '🔴 Shorts nomi kiriting (ixtiyoriy, o\'tkazib yuborish uchun - yozing):')
    else:
        user_states[call.from_user.id]['step'] = 'title'
        user_states[call.from_user.id]['shorts_mode'] = False
        bot.send_message(call.message.chat.id, '🔤 Anime/kontent nomini kiriting:')
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'title')
def get_title(msg):
    uid = msg.from_user.id
    d = user_states[uid]
    title = msg.text.strip() if msg.text.strip() != '-' else 'Shorts'
    user_states[uid]['title'] = title

    if d.get('shorts_mode'):
        # Shorts — poster so'rab video yuborishga o'tamiz
        user_states[uid]['step'] = 'ask_poster'
        user_states[uid]['genre'] = 'Shorts'
        user_states[uid]['season'] = 1
        kb = telebot.types.InlineKeyboardMarkup()
        kb.add(telebot.types.InlineKeyboardButton('✅ Ha', callback_data='poster:yes'))
        kb.add(telebot.types.InlineKeyboardButton('⏭ Yo\'q', callback_data='poster:no'))
        bot.send_message(msg.chat.id, '🖼 Poster qo\'shmoqchimisiz? (ixtiyoriy)', reply_markup=kb)
    else:
        user_states[uid]['step'] = 'genre'
        bot.send_message(msg.chat.id, '🎭 Janrini kiriting:')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'genre')
def get_genre(msg):
    uid = msg.from_user.id
    user_states[uid]['genre'] = msg.text.strip()
    d = user_states[uid]
    cat = d.get('category')

    if cat == 'film':
        # Film uchun fasl so'ralmasin, poster so'rasin
        user_states[uid]['season'] = 1
        user_states[uid]['step'] = 'ask_poster'
        kb = telebot.types.InlineKeyboardMarkup()
        kb.add(telebot.types.InlineKeyboardButton('✅ Ha', callback_data='poster:yes'))
        kb.add(telebot.types.InlineKeyboardButton('⏭ Yo\'q', callback_data='poster:no'))
        bot.send_message(msg.chat.id, '🖼 Poster qo\'shmoqchimisiz? (ixtiyoriy)', reply_markup=kb)
    else:
        # Ongoing, tugallangan, serial uchun fasl so'rasin
        user_states[uid]['step'] = 'season'
        bot.send_message(msg.chat.id, '📺 Nechanchi fasl? (raqam kiriting, OVA uchun 0):')

@bot.callback_query_handler(func=lambda c: c.data.startswith('poster:') and c.from_user.id in user_states and user_states[c.from_user.id].get('step') == 'ask_poster')
def ask_poster_cb(call):
    uid = call.from_user.id
    choice = call.data.split(':')[1]
    if choice == 'yes':
        user_states[uid]['step'] = 'inline_poster'
        bot.send_message(call.message.chat.id, '🖼 Poster rasmini yuboring:')
    else:
        user_states[uid]['step'] = 'waiting_video'
        d = user_states[uid]
        cat = d.get('category')
        if cat == 'shorts':
            bot.send_message(call.message.chat.id, '🔴 Shorts videosini yuboring!\n/done yozib tugatng.')
        elif cat == 'film':
            bot.send_message(call.message.chat.id, '🎬 Film videosini yuboring!\n/done yozib tugatng.')
        else:
            sl = 'OVA' if d.get('season') == 0 else f"{d.get('season')}-fasl"
            bot.send_message(call.message.chat.id, f'✅ {sl} tanlandi!\n\n📤 Videolarni yuboring!\nTugatgach /done yozing.')
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['photo'],
                     func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'inline_poster')
def get_inline_poster(msg):
    uid = msg.from_user.id
    user_states[uid]['poster'] = msg.photo[-1].file_id
    user_states[uid]['step'] = 'waiting_video'
    d = user_states[uid]
    cat = d.get('category')
    if cat == 'shorts':
        bot.send_message(msg.chat.id, '✅ Poster saqlandi!\n\n🔴 Shorts videosini yuboring!\n/done yozib tugatng.')
    elif cat == 'film':
        bot.send_message(msg.chat.id, '✅ Poster saqlandi!\n\n🎬 Film videosini yuboring!\n/done yozib tugatng.')
    else:
        sl = 'OVA' if d.get('season') == 0 else f"{d.get('season')}-fasl"
        bot.send_message(msg.chat.id, f'✅ Poster saqlandi!\n\n📤 {sl} videolarini yuboring!\nTugatgach /done yozing.')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'season')
def get_season(msg):
    try:
        season = int(msg.text.strip())
        user_states[msg.from_user.id]['season'] = season
        user_states[msg.from_user.id]['step'] = 'ask_poster'
        sl = 'OVA' if season == 0 else f'{season}-fasl'
        kb = telebot.types.InlineKeyboardMarkup()
        kb.add(telebot.types.InlineKeyboardButton('✅ Ha', callback_data='poster:yes'))
        kb.add(telebot.types.InlineKeyboardButton('⏭ Yo\'q', callback_data='poster:no'))
        bot.send_message(msg.chat.id, f'✅ {sl} tanlandi!\n\n🖼 Poster qo\'shmoqchimisiz? (ixtiyoriy)', reply_markup=kb)
    except:
        bot.send_message(msg.chat.id, '❌ Faqat raqam kiriting!')

@bot.callback_query_handler(func=lambda c: c.data == 'add_poster')
def add_poster_cb(call):
    if call.from_user.id not in ADMIN_IDS:
        return
    user_states[call.from_user.id] = {'step': 'poster_id'}
    bot.send_message(call.message.chat.id, '🆔 Poster qoshmoqchi anime ID sini kiriting:')
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == 'del_anime')
def del_anime_cb(call):
    if call.from_user.id not in ADMIN_IDS:
        return
    user_states[call.from_user.id] = {'step': 'del_id'}
    bot.send_message(call.message.chat.id, '🆔 Ochirmoqchi anime ID sini kiriting:')
    bot.answer_callback_query(call.id)

media_group_buffer = {}
media_group_timers = {}

def process_media_group(uid, group_id):
    time.sleep(1.5)
    if group_id not in media_group_buffer:
        return
    messages = media_group_buffer.pop(group_id, [])
    if not messages:
        return
    d = user_states.get(uid)
    if not d or d.get('step') != 'waiting_video':
        return

    saved = 0
    need_manual = []

    for msg in messages:
        file_id = msg.video.file_id if msg.video else msg.document.file_id
        episode = extract_episode(msg.caption or '')
        if episode:
            conn = get_conn()
            c = conn.cursor()
            c.execute('INSERT INTO anime (anime_id, title, genre, season, episode, video, category, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (anime_id, season, episode) DO UPDATE SET video=EXCLUDED.video',
                      (d['anime_id'], d['title'], d['genre'], d['season'], episode, file_id, d['category'], d['status']))
            conn.commit()
            conn.close()
            saved += 1
        else:
            need_manual.append(file_id)

    sl = 'OVA' if d['season'] == 0 else f"{d['season']}-fasl"

    if saved > 0:
        bot.send_message(messages[0].chat.id, f'✅ {sl} dan {saved} ta qism saqlandi!')

    if need_manual:
        user_states[uid]['pending_videos'] = need_manual
        user_states[uid]['pending_index'] = 0
        user_states[uid]['step'] = 'manual_ep_multi'
        bot.send_message(messages[0].chat.id,
                         f'⚠️ {len(need_manual)} ta videoning qism raqami aniqlanmadi.\n'
                         f'1-video uchun qism raqamini kiriting:')

@bot.message_handler(content_types=['video', 'document'],
                     func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'waiting_video')
def get_video(msg):
    uid = msg.from_user.id
    file_id = msg.video.file_id if msg.video else msg.document.file_id

    if msg.media_group_id:
        gid = msg.media_group_id
        if gid not in media_group_buffer:
            media_group_buffer[gid] = []
        media_group_buffer[gid].append(msg)
        if gid not in media_group_timers:
            t = threading.Timer(1.5, process_media_group, args=[uid, gid])
            media_group_timers[gid] = t
            t.start()
        return

    episode = extract_episode(msg.caption or '')
    d = user_states[uid]
    if not episode:
        user_states[uid]['cur_video'] = file_id
        user_states[uid]['step'] = 'manual_ep'
        bot.send_message(msg.chat.id, '⚠️ Qism raqamini aniqlay olmadim. Qo\'lda kiriting:')
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT INTO anime (anime_id, title, genre, season, episode, video, category, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (anime_id, season, episode) DO UPDATE SET video=EXCLUDED.video',
              (d['anime_id'], d['title'], d['genre'], d['season'], episode, file_id, d['category'], d['status']))
    conn.commit()
    conn.close()
    sl = 'OVA' if d['season'] == 0 else f"{d['season']}-fasl"
    bot.send_message(msg.chat.id, f'✅ {sl} {episode}-qism saqlandi! Davom eting yoki /done yozing.')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'manual_ep_multi')
def manual_ep_multi(msg):
    try:
        episode = int(msg.text.strip())
        uid = msg.from_user.id
        d = user_states[uid]
        pending = d['pending_videos']
        idx = d['pending_index']
        file_id = pending[idx]

        conn = get_conn()
        c = conn.cursor()
        c.execute('INSERT INTO anime (anime_id, title, genre, season, episode, video, category, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (anime_id, season, episode) DO UPDATE SET video=EXCLUDED.video',
                  (d['anime_id'], d['title'], d['genre'], d['season'], episode, file_id, d['category'], d['status']))
        conn.commit()
        conn.close()

        sl = 'OVA' if d['season'] == 0 else f"{d['season']}-fasl"
        bot.send_message(msg.chat.id, f'✅ {sl} {episode}-qism saqlandi!')

        idx += 1
        if idx < len(pending):
            user_states[uid]['pending_index'] = idx
            bot.send_message(msg.chat.id, f'{idx+1}-video uchun qism raqamini kiriting:')
        else:
            user_states[uid]['step'] = 'waiting_video'
            del user_states[uid]['pending_videos']
            del user_states[uid]['pending_index']
            bot.send_message(msg.chat.id, '✅ Barcha qismlar saqlandi! Davom eting yoki /done yozing.')
    except:
        bot.send_message(msg.chat.id, '❌ Faqat raqam kiriting!')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'manual_ep')
def manual_ep(msg):
    try:
        episode = int(msg.text.strip())
        d = user_states[msg.from_user.id]
        conn = get_conn()
        c = conn.cursor()
        c.execute('INSERT INTO anime (anime_id, title, genre, season, episode, video, category, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (anime_id, season, episode) DO UPDATE SET video=EXCLUDED.video',
                  (d['anime_id'], d['title'], d['genre'], d['season'], episode, d['cur_video'], d['category'], d['status']))
        conn.commit()
        conn.close()
        user_states[msg.from_user.id]['step'] = 'waiting_video'
        sl = 'OVA' if d['season'] == 0 else f"{d['season']}-fasl"
        bot.send_message(msg.chat.id, f'✅ {sl} {episode}-qism saqlandi! Davom eting yoki /done yozing.')
    except:
        bot.send_message(msg.chat.id, '❌ Faqat raqam kiriting!')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'del_id')
def del_anime(msg):
    try:
        aid = int(msg.text.strip())
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT title FROM anime WHERE anime_id=%s LIMIT 1', (aid,))
        row = c.fetchone()
        if row:
            c.execute('DELETE FROM anime WHERE anime_id=%s', (aid,))
            conn.commit()
            bot.send_message(msg.chat.id, f'✅ "{row[0]}" ochirildi!')
        else:
            bot.send_message(msg.chat.id, '❌ Bu ID da anime topilmadi!')
        conn.close()
        user_states.pop(msg.from_user.id)
    except:
        bot.send_message(msg.chat.id, '❌ Faqat raqam kiriting!')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'poster_id')
def get_poster_id(msg):
    try:
        user_states[msg.from_user.id]['poster_aid'] = int(msg.text.strip())
        user_states[msg.from_user.id]['step'] = 'poster_img'
        bot.send_message(msg.chat.id, '🖼 Rasm yoki video yuboring:')
    except:
        bot.send_message(msg.chat.id, '❌ Faqat raqam kiriting!')

@bot.message_handler(content_types=['photo', 'video'],
                     func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'poster_img')
def save_poster(msg):
    aid = user_states[msg.from_user.id]['poster_aid']
    conn = get_conn()
    c = conn.cursor()
    if msg.photo:
        fid = msg.photo[-1].file_id
        media_type = 'Poster (rasm)'
    else:
        fid = msg.video.file_id
        media_type = 'Poster (video)'
    c.execute('UPDATE anime SET poster=%s WHERE anime_id=%s', (fid, aid))
    affected = c.rowcount
    conn.commit()
    conn.close()
    user_states.pop(msg.from_user.id)
    if affected > 0:
        bot.send_message(msg.chat.id, f'✅ {media_type} muvaffaqiyatli qoshildi!')
    else:
        bot.send_message(msg.chat.id, '❌ Bu ID da anime topilmadi!')

@bot.message_handler(commands=['done'])
def done_cmd(msg):
    if msg.from_user.id not in user_states:
        return
    d = user_states.pop(msg.from_user.id)
    aid = d.get('anime_id')
    poster = d.get('poster')

    conn = get_conn()
    c = conn.cursor()

    # Posterni saqlash
    if poster and aid:
        c.execute('UPDATE anime SET poster=%s WHERE anime_id=%s', (poster, aid))

    c.execute('SELECT title, genre, status FROM anime WHERE anime_id=%s LIMIT 1', (aid,))
    row = c.fetchone()
    c.execute('SELECT COUNT(*) FROM anime WHERE anime_id=%s', (aid,))
    cnt = c.fetchone()[0]
    conn.commit()
    conn.close()

    title = row[0] if row else 'Nomalum'
    genre = row[1] if row else 'Nomalum'
    status = row[2] if row else 'ongoing'

    username = bot.get_me().username
    link = f't.me/{username}?start={aid}'

    bot.send_message(msg.chat.id,
                     f'✅ <b>{title}</b> uchun {cnt} ta qism saqlandi!\n\n'
                     f'🔗 Havola: {link}',
                     parse_mode='HTML')

    # Kanalga post yuborish
    send_channel_post(msg.chat.id, aid, title, genre, status, poster)

@bot.message_handler(func=lambda m: True)
def handle_text(msg):
    if not msg.text:
        return
    text = msg.text.strip()

    if text == '📞 Murojaat':
        bot.send_message(msg.chat.id,
                         '📞 <b>Murojaat</b>\n\n'
                         '👤 Admin: @g1yu_tamioka\n'
                         '📢 Kanal: https://t.me/animelarr_uzbekcha',
                         parse_mode='HTML')
        return

    if text == '🔴 Shorts':
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT video, title FROM anime WHERE category='shorts' AND video IS NOT NULL ORDER BY RANDOM() LIMIT 1")
        row = c.fetchone()
        conn.close()
        if row:
            bot.send_video(msg.chat.id, row[0], caption=f'🔴 <b>Shorts</b>: {row[1]}', parse_mode='HTML')
        else:
            bot.send_message(msg.chat.id, '📭 Hozircha Shorts yo\'q.')
        return

    cats = {
        '🎬 Anime & Filmlar': 'film',
        '📺 Ongoing Animelar': 'ongoing',
        '✅ Tugallangan': 'completed',
        '📡 Seriallar': 'serial',
    }
    if text in cats:
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT DISTINCT anime_id, title FROM anime WHERE category=%s', (cats[text],))
        rows = c.fetchall()
        conn.close()
        show_list(msg.chat.id, text, rows)
        return

    if text == '📚 Barcha animelar':
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT DISTINCT anime_id, title FROM anime ORDER BY anime_id DESC')
        rows = c.fetchall()
        conn.close()
        show_list(msg.chat.id, 'Barcha animelar', rows)
        return

    if text == '⭐ Tavsiya etilganlar':
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT DISTINCT anime_id, title FROM anime ORDER BY views DESC LIMIT 10')
        rows = c.fetchall()
        conn.close()
        show_list(msg.chat.id, '⭐ Tavsiya etilganlar', rows)
        return

    if text == '🔍 Anime qidiruv':
        user_states[msg.from_user.id] = {'step': 'searching'}
        bot.send_message(msg.chat.id, '🔍 Anime nomi yoki ID raqamini yozing:')
        return

    if msg.from_user.id in user_states and user_states[msg.from_user.id].get('step') == 'searching':
        user_states.pop(msg.from_user.id)
        try:
            show_anime_info(msg.chat.id, int(text), msg.from_user.id)
            return
        except:
            pass
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT DISTINCT anime_id, title FROM anime WHERE title ILIKE %s LIMIT 10', ('%' + text + '%',))
        rows = c.fetchall()
        conn.close()
        if rows:
            show_list(msg.chat.id, f'🔍 "{text}" natijalari:', rows)
        else:
            bot.send_message(msg.chat.id, '❌ Topilmadi. Boshqa nom yoki ID bilan urining.')
        return

    bot.send_message(msg.chat.id, '🔍 Anime qidiruv tugmasini bosing yoki menyudan foydalaning.')


# ─── HTTP SERVER ─────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running!')
    def log_message(self, format, *args):
        pass

def run_server():
    port = int(os.environ.get('PORT', 10000))
    HTTPServer(('0.0.0.0', port), Handler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()
@bot.message_handler(commands=['post'])
def post_cmd(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    args = msg.text.split()
    if len(args) < 2:
        bot.send_message(msg.chat.id, '📝 Ishlatish: /post <anime_id>\nMasalan: /post 1')
        return
    try:
        aid = int(args[1])
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT title, genre, status, poster FROM anime WHERE anime_id=%s LIMIT 1', (aid,))
        row = c.fetchone()
        conn.close()
        if not row:
            bot.send_message(msg.chat.id, '❌ Bu ID da anime topilmadi!')
            return
        title, genre, status, poster = row
        send_channel_post(msg.chat.id, aid, title, genre, status, poster)
        bot.send_message(msg.chat.id, f'✅ <b>{title}</b> kanalga joylandi!', parse_mode='HTML')
    except Exception as e:
        bot.send_message(msg.chat.id, f'❌ Xatolik: {e}')
init_db()
print('✅ Bot ishga tushdi!')
bot.infinity_polling(timeout=60, long_polling_timeout=60)

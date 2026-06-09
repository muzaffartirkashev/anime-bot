import telebot
import sqlite3
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import BOT_TOKEN, ADMIN_IDS

bot = telebot.TeleBot(BOT_TOKEN)
bot.set_my_commands([
    telebot.types.BotCommand('/start', 'Botni ishga tushirish'),
    telebot.types.BotCommand('/admin', 'Admin panel'),
    telebot.types.BotCommand('/done', 'Qoshishni tugatish'),
    telebot.types.BotCommand('/stats', 'Statistika'),
])

def init_db():
    conn = sqlite3.connect('anime.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, username TEXT, full_name TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS anime (id INTEGER PRIMARY KEY AUTOINCREMENT, anime_id INTEGER, title TEXT, genre TEXT, season INTEGER DEFAULT 1, episode INTEGER, video TEXT, category TEXT DEFAULT "anime", status TEXT DEFAULT "ongoing", poster TEXT, views INTEGER DEFAULT 0, UNIQUE(anime_id, season, episode))')
    c.execute('CREATE TABLE IF NOT EXISTS search_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, anime_id INTEGER, searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    conn.commit()
    conn.close()

def add_user(uid, uname, fname):
    conn = sqlite3.connect('anime.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?,?,?)', (uid, uname or '', fname or ''))
    conn.commit()
    conn.close()

def is_new_user(uid):
    conn = sqlite3.connect('anime.db')
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE user_id=?', (uid,))
    r = c.fetchone()
    conn.close()
    return r is None

def log_search(uid, aid):
    conn = sqlite3.connect('anime.db')
    c = conn.cursor()
    c.execute('INSERT INTO search_logs (user_id, anime_id) VALUES (?,?)', (uid, aid))
    c.execute('UPDATE anime SET views=views+1 WHERE anime_id=?', (aid,))
    conn.commit()
    conn.close()

def get_next_id():
    conn = sqlite3.connect('anime.db')
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
    ]
    for p in patterns:
        m = re.search(p, caption, re.IGNORECASE)
        if m:
            return int(m.group(1))
    nums = re.findall(r'\d+', caption)
    if nums:
        return int(nums[-1])
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
        '🎭 Assalomu alaykum! 🎭\n\n'
        '👤 Xush kelibsiz!\n\n'
        'Anime izlash uchun /start\n\n'
        '🔍 Anime izlash bosing va tanlang\n\n'
        'Kanal: @anilordtv | Admin: @tamioka_g1yu\n\n'
        '🔥 Anime dunyosiga xush kelibsiz!'
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_menu())

def show_seasons(chat_id, anime_id, uid):
    conn = sqlite3.connect('anime.db')
    c = conn.cursor()
    c.execute('SELECT title, genre, status, poster, views FROM anime WHERE anime_id=? LIMIT 1', (anime_id,))
    row = c.fetchone()
    if not row:
        bot.send_message(chat_id, 'Anime topilmadi!')
        conn.close()
        return
    title, genre, status, poster, views = row
    c.execute('SELECT DISTINCT season FROM anime WHERE anime_id=? ORDER BY season', (anime_id,))
    seasons = c.fetchall()
    conn.close()
    log_search(uid, anime_id)
    if len(seasons) == 1:
        show_episodes(chat_id, anime_id, seasons[0][0])
        return
    kb = telebot.types.InlineKeyboardMarkup(row_width=3)
    btns = []
    for s in seasons:
        sn = s[0]
        lbl = 'OVA' if sn == 0 else str(sn)+'-fasl'
        btns.append(telebot.types.InlineKeyboardButton(lbl, callback_data='season:'+str(anime_id)+':'+str(sn)))
    kb.add(*btns)
    st = 'Tugallangan' if status == 'completed' else 'Davom etmoqda'
    text = '🎬 <b>'+str(title)+'</b>\n🎭 Janri: '+str(genre or 'Nomalum')+'\n📍 Holati: '+st+'\n👁 Korishlar: '+str(views)+'\n\nFaslni tanlang:'
    if poster:
        bot.send_photo(chat_id, poster, caption=text, reply_markup=kb, parse_mode='HTML')
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode='HTML')

def show_episodes(chat_id, anime_id, season):
    conn = sqlite3.connect('anime.db')
    c = conn.cursor()
    c.execute('SELECT title, genre, status, poster, views FROM anime WHERE anime_id=? LIMIT 1', (anime_id,))
    info = c.fetchone()
    c.execute('SELECT episode FROM anime WHERE anime_id=? AND season=? ORDER BY episode', (anime_id, season))
    eps = c.fetchall()
    conn.close()
    if not info or not eps:
        bot.send_message(chat_id, 'Qismlar topilmadi!')
        return
    title, genre, status, poster, views = info
    kb = telebot.types.InlineKeyboardMarkup(row_width=5)
    btns = [telebot.types.InlineKeyboardButton(str(e[0]), callback_data='ep:'+str(anime_id)+':'+str(season)+':'+str(e[0])) for e in eps]
    kb.add(*btns)
    sl = 'OVA' if season == 0 else str(season)+'-fasl'
    st = 'Tugallangan' if status == 'completed' else 'Davom etmoqda'
    text = '🎬 <b>'+str(title)+'</b>\n🎭 Janri: '+str(genre or 'Nomalum')+'\n📍 Holati: '+st+'\n👁 Korishlar: '+str(views)+'\n\n📺 '+sl+' — Qismni tanlang:'
    if poster:
        bot.send_photo(chat_id, poster, caption=text, reply_markup=kb, parse_mode='HTML')
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode='HTML')

def show_list(chat_id, header, rows):
    if not rows:
        bot.send_message(chat_id, 'Hozircha bu toifada kontent yoq.')
        return
    bot.send_message(chat_id, '<b>'+header+'</b>', parse_mode='HTML')
    for row in rows:
        kb = telebot.types.InlineKeyboardMarkup()
        kb.add(telebot.types.InlineKeyboardButton('Batafsil', callback_data='show:'+str(row[0])))
        bot.send_message(chat_id, '🎬 <b>'+str(row[1])+'</b>\nID: '+str(row[0]), reply_markup=kb, parse_mode='HTML')

def show_stats_msg(chat_id):
    conn = sqlite3.connect('anime.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    u = c.fetchone()[0]
    c.execute('SELECT COUNT(DISTINCT anime_id) FROM anime')
    a = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM anime')
    e = c.fetchone()[0]
    c.execute('SELECT a.title, COUNT(s.id) as cnt FROM search_logs s JOIN anime a ON s.anime_id=a.anime_id GROUP BY s.anime_id ORDER BY cnt DESC LIMIT 5')
    top = c.fetchall()
    conn.close()
    text = '📊 <b>Statistika</b>\n\n👥 Foydalanuvchilar: '+str(u)+'\n🎬 Animelar: '+str(a)+'\n📺 Qismlar: '+str(e)+'\n\n🔥 Eng kop qidirilgan:\n'
    for i, (t, cnt) in enumerate(top, 1):
        text += str(i)+'. '+str(t)+' — '+str(cnt)+' marta\n'
    bot.send_message(chat_id, text, parse_mode='HTML')

@bot.message_handler(commands=['start'])
def start(msg):
    new = is_new_user(msg.from_user.id)
    add_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    args = msg.text.split()
    if len(args) > 1:
        try:
            show_seasons(msg.chat.id, int(args[1]), msg.from_user.id)
            return
        except:
            pass
    if new:
        welcome_new_user(msg)
    else:
        bot.send_message(msg.chat.id, '🎬 Xush kelibsiz <b>'+msg.from_user.first_name+'</b>!\n\nMenyudan foydalaning:', reply_markup=main_menu(), parse_mode='HTML')

@bot.message_handler(commands=['stats'])
def stats_cmd(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    show_stats_msg(msg.chat.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('season:'))
def season_cb(call):
    _, aid, sn = call.data.split(':')
    show_episodes(call.message.chat.id, int(aid), int(sn))

@bot.callback_query_handler(func=lambda c: c.data.startswith('ep:'))
def ep_cb(call):
    parts = call.data.split(':')
    aid, sn, ep = int(parts[1]), int(parts[2]), int(parts[3])
    conn = sqlite3.connect('anime.db')
    c = conn.cursor()
    c.execute('SELECT title, video FROM anime WHERE anime_id=? AND season=? AND episode=?', (aid, sn, ep))
    row = c.fetchone()
    conn.close()
    if row and row[1]:
        sl = 'OVA' if sn == 0 else str(sn)+'-fasl'
        bot.send_video(call.message.chat.id, row[1], caption='🎬 <b>'+str(row[0])+'</b>\n📺 '+sl+' '+str(ep)+'-qism', parse_mode='HTML')
    else:
        bot.answer_callback_query(call.id, 'Video topilmadi!', show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith('show:'))
def show_cb(call):
    show_seasons(call.message.chat.id, int(call.data.split(':')[1]), call.from_user.id)

user_states = {}

@bot.message_handler(commands=['admin'])
def admin_panel(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    conn = sqlite3.connect('anime.db')
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
    bot.send_message(msg.chat.id, '👑 <b>Admin Panel</b>\n\n👥 Foydalanuvchilar: '+str(u)+'\n🎬 Animelar: '+str(a), reply_markup=kb, parse_mode='HTML')

@bot.callback_query_handler(func=lambda c: c.data == 'stats')
def stats_cb(call):
    if call.from_user.id not in ADMIN_IDS:
        return
    show_stats_msg(call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == 'add_anime')
def add_anime_cb(call):
    if call.from_user.id not in ADMIN_IDS:
        return
    user_states[call.from_user.id] = {'step': 'title', 'anime_id': get_next_id()}
    bot.send_message(call.message.chat.id, '🔤 Anime nomini kiriting:')

@bot.callback_query_handler(func=lambda c: c.data == 'add_poster')
def add_poster_cb(call):
    if call.from_user.id not in ADMIN_IDS:
        return
    user_states[call.from_user.id] = {'step': 'poster_id'}
    bot.send_message(call.message.chat.id, '🆔 Poster qoshmoqchi anime ID sini kiriting:')

@bot.callback_query_handler(func=lambda c: c.data == 'del_anime')
def del_anime_cb(call):
    if call.from_user.id not in ADMIN_IDS:
        return
    user_states[call.from_user.id] = {'step': 'del_id'}
    bot.send_message(call.message.chat.id, '🆔 Ochirmoqchi anime ID sini kiriting:')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'title')
def get_title(msg):
    user_states[msg.from_user.id]['title'] = msg.text.strip()
    user_states[msg.from_user.id]['step'] = 'genre'
    bot.send_message(msg.chat.id, '🎭 Janrini kiriting:')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'genre')
def get_genre(msg):
    user_states[msg.from_user.id]['genre'] = msg.text.strip()
    user_states[msg.from_user.id]['step'] = 'category'
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton('🎬 Film', callback_data='cat:film'))
    kb.add(telebot.types.InlineKeyboardButton('📺 Ongoing', callback_data='cat:ongoing'))
    kb.add(telebot.types.InlineKeyboardButton('✅ Tugallangan', callback_data='cat:completed'))
    kb.add(telebot.types.InlineKeyboardButton('📡 Serial', callback_data='cat:serial'))
    kb.add(telebot.types.InlineKeyboardButton('🔴 Shorts', callback_data='cat:shorts'))
    bot.send_message(msg.chat.id, '📂 Toifani tanlang:', reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('cat:') and c.from_user.id in user_states and user_states[c.from_user.id].get('step') == 'category')
def get_category(call):
    cat = call.data.split(':')[1]
    status = 'completed' if cat in ['completed', 'film'] else 'ongoing'
    user_states[call.from_user.id]['category'] = cat
    user_states[call.from_user.id]['status'] = status
    user_states[call.from_user.id]['step'] = 'season'
    bot.send_message(call.message.chat.id, '📺 Nechanchi fasl? (raqam, OVA uchun 0):')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'season')
def get_season(msg):
    try:
        season = int(msg.text.strip())
        user_states[msg.from_user.id]['season'] = season
        user_states[msg.from_user.id]['step'] = 'waiting_video'
        sl = 'OVA' if season == 0 else str(season)+'-fasl'
        bot.send_message(msg.chat.id, '✅ '+sl+'\n\n📤 Videolarni forward qiling!\nTugatgach /done yozing.')
    except:
        bot.send_message(msg.chat.id, '❌ Faqat raqam kiriting!')

@bot.message_handler(content_types=['video', 'document'], func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'waiting_video')
def get_video(msg):
    file_id = msg.video.file_id if msg.video else msg.document.file_id
    episode = extract_episode(msg.caption or '')
    d = user_states[msg.from_user.id]
    if not episode:
        user_states[msg.from_user.id]['cur_video'] = file_id
        user_states[msg.from_user.id]['step'] = 'manual_ep'
        bot.send_message(msg.chat.id, '⚠️ Qism raqamini aniqladim olmadim. Yozing:')
        return
    conn = sqlite3.connect('anime.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO anime (anime_id, title, genre, season, episode, video, category, status) VALUES (?,?,?,?,?,?,?,?)',
              (d['anime_id'], d['title'], d['genre'], d['season'], episode, file_id, d['category'], d['status']))
    conn.commit()
    conn.close()
    sl = 'OVA' if d['season'] == 0 else str(d['season'])+'-fasl'
    bot.send_message(msg.chat.id, '✅ '+sl+' '+str(episode)+'-qism saqlandi! Davom eting yoki /done yozing.')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'manual_ep')
def manual_ep(msg):
    try:
        episode = int(msg.text.strip())
        d = user_states[msg.from_user.id]
        conn = sqlite3.connect('anime.db')
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO anime (anime_id, title, genre, season, episode, video, category, status) VALUES (?,?,?,?,?,?,?,?)',
                  (d['anime_id'], d['title'], d['genre'], d['season'], episode, d['cur_video'], d['category'], d['status']))
        conn.commit()
        conn.close()
        user_states[msg.from_user.id]['step'] = 'waiting_video'
        sl = 'OVA' if d['season'] == 0 else str(d['season'])+'-fasl'
        bot.send_message(msg.chat.id, '✅ '+sl+' '+str(episode)+'-qism saqlandi! Davom eting yoki /done yozing.')
    except:
        bot.send_message(msg.chat.id, '❌ Faqat raqam kiriting!')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'del_id')
def del_anime(msg):
    try:
        aid = int(msg.text.strip())
        conn = sqlite3.connect('anime.db')
        c = conn.cursor()
        c.execute('SELECT title FROM anime WHERE anime_id=? LIMIT 1', (aid,))
        row = c.fetchone()
        if row:
            c.execute('DELETE FROM anime WHERE anime_id=?', (aid,))
            conn.commit()
            bot.send_message(msg.chat.id, '✅ '+str(row[0])+' ochirildi!')
        else:
            bot.send_message(msg.chat.id, '❌ Topilmadi!')
        conn.close()
        user_states.pop(msg.from_user.id)
    except:
        bot.send_message(msg.chat.id, '❌ Faqat raqam kiriting!')

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'poster_id')
def get_poster_id(msg):
    try:
        user_states[msg.from_user.id]['poster_aid'] = int(msg.text.strip())
        user_states[msg.from_user.id]['step'] = 'poster_img'
        bot.send_message(msg.chat.id, '🖼 Rasm yuboring:')
    except:
        bot.send_message(msg.chat.id, '❌ Faqat raqam kiriting!')

@bot.message_handler(content_types=['photo'], func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('step') == 'poster_img')
def save_poster(msg):
    aid = user_states[msg.from_user.id]['poster_aid']
    fid = msg.photo[-1].file_id
    conn = sqlite3.connect('anime.db')
    c = conn.cursor()
    c.execute('UPDATE anime SET poster=? WHERE anime_id=?', (fid, aid))
    affected = c.rowcount
    conn.commit()
    conn.close()
    user_states.pop(msg.from_user.id)
    if affected > 0:
        bot.send_message(msg.chat.id, '✅ Poster muvaffaqiyatli qoshildi!')
    else:
        bot.send_message(msg.chat.id, '❌ Bu ID da anime topilmadi!')

@bot.message_handler(commands=['done'])
def done_cmd(msg):
    if msg.from_user.id not in user_states:
        return
    d = user_states.pop(msg.from_user.id)
    aid = d.get('anime_id')
    conn = sqlite3.connect('anime.db')
    c = conn.cursor()
    c.execute('SELECT title FROM anime WHERE anime_id=? LIMIT 1', (aid,))
    row = c.fetchone()
    c.execute('SELECT COUNT(*) FROM anime WHERE anime_id=?', (aid,))
    cnt = c.fetchone()[0]
    conn.close()
    title = row[0] if row else 'Nomalum'
    bot.send_message(msg.chat.id, '✅ <b>'+title+'</b> uchun '+str(cnt)+' ta qism saqlandi!\n\n🔗 Havola: t.me/'+bot.get_me().username+'?start='+str(aid), parse_mode='HTML')

@bot.message_handler(func=lambda m: True)
def handle_text(msg):
    text = msg.text.strip()
    if text == '📞 Murojaat':
        bot.send_message(msg.chat.id, '📞 Murojaat uchun: @tamioka_g1yu\n📢 Kanal: @anilordtv')
        return
    cats = {
        '🎬 Anime & Filmlar': 'film',
        '📺 Ongoing Animelar': 'ongoing',
        '✅ Tugallangan': 'completed',
        '📡 Seriallar': 'serial',
        '🔴 Shorts': 'shorts',
    }
    if text in cats:
        conn = sqlite3.connect('anime.db')
        c = conn.cursor()
        c.execute('SELECT DISTINCT anime_id, title FROM anime WHERE category=?', (cats[text],))
        rows = c.fetchall()
        conn.close()
        show_list(msg.chat.id, text, rows)
        return
    if text == '📚 Barcha animelar':
        conn = sqlite3.connect('anime.db')
        c = conn.cursor()
        c.execute('SELECT DISTINCT anime_id, title FROM anime')
        rows = c.fetchall()
        conn.close()
        show_list(msg.chat.id, 'Barcha animelar', rows)
        return
    if text == '⭐ Tavsiya etilganlar':
        conn = sqlite3.connect('anime.db')
        c = conn.cursor()
        c.execute('SELECT DISTINCT anime_id, title FROM anime ORDER BY views DESC LIMIT 10')
        rows = c.fetchall()
        conn.close()
        show_list(msg.chat.id, 'Tavsiya etilganlar', rows)
        return
    if text == '🔍 Anime qidiruv':
        user_states[msg.from_user.id] = {'step': 'searching'}
        bot.send_message(msg.chat.id, '🔍 Anime nomi yoki ID raqamini yozing:')
        return
    if msg.from_user.id in user_states and user_states[msg.from_user.id].get('step') == 'searching':
        user_states.pop(msg.from_user.id)
        try:
            show_seasons(msg.chat.id, int(text), msg.from_user.id)
            return
        except:
            pass
        conn = sqlite3.connect('anime.db')
        c = conn.cursor()
        c.execute('SELECT DISTINCT anime_id, title FROM anime WHERE title LIKE ? LIMIT 10', ('%'+text+'%',))
        rows = c.fetchall()
        conn.close()
        if rows:
            show_list(msg.chat.id, 'Qidiruv natijalari:', rows)
        else:
            bot.send_message(msg.chat.id, '❌ Topilmadi. Boshqa nom yoki ID bilan urining.')
        return
    bot.send_message(msg.chat.id, 'Menyudan foydalaning 🔍 Anime qidiruv tugmasini bosing.')


# Render.com uchun HTTP server
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, format, *args):
        pass

def run_server():
    HTTPServer(('0.0.0.0', 10000), Handler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()

init_db()
print('Bot ishga tushdi!')
bot.polling(none_stop=True)


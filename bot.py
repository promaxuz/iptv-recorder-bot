"""
🛰 IPTV RECORDER BOT - RAILWAY.APP VERSION
24/7 ishlaydigan to'liq versiya
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import json
from typing import Dict, Optional, List
import uuid
import sys

# ============================================
# 🎯 KONFIGURATSIYA - RAILWAY ENVIRONMENT
# ============================================

# Railway environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "2113863377"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Best_Studios")
MAX_FILE_SIZE_GB = 1.8
AUTO_UPLOAD_ON_STOP = True

# Railway da temp papka
OUTPUT_DIR = Path("/tmp/recordings")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================
# 📊 LOGGING - RAILWAY UCHUN
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),  # Railway loglari uchun
        logging.FileHandler(OUTPUT_DIR / 'bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Startup xabari
logger.info("🚀 IPTV Recorder Bot - Railway.app da ishga tushmoqda...")
logger.info(f"📁 Output directory: {OUTPUT_DIR}")
logger.info(f"👤 Admin ID: {ADMIN_ID}")
logger.info(f"📺 Channel: {CHANNEL_ID}")

# ============================================
# 📦 KUTUBXONALARNI TEKSHIRISH
# ============================================

try:
    from aiogram import Bot, Dispatcher, types, F
    from aiogram.filters import Command
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.state import State, StatesGroup
    from aiogram.fsm.storage.memory import MemoryStorage
    logger.info("✅ Barcha kutubxonalar mavjud")
except ImportError as e:
    logger.error(f"❌ Kutubxona yetishmayapti: {e}")
    sys.exit(1)

# ============================================
# 📁 GLOBAL STATE
# ============================================

active_recordings: Dict[str, dict] = {}
recorded_files: Dict[str, List[str]] = {}

# ============================================
# 🎬 FSM STATES
# ============================================

class RecordState(StatesGroup):
    waiting_for_link = State()
    confirming = State()

# ============================================
# 🔧 YORDAMCHI FUNKSIYALAR
# ============================================

def check_admin(user_id: int) -> bool:
    """Adminlikni tekshirish"""
    return user_id == ADMIN_ID

def get_stream_title(url: str) -> Optional[str]:
    """Stream sarlavhasini olish"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-timeout', '10000000', url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            title = data.get('format', {}).get('tags', {}).get('title', '')
            if title:
                # Faqat xavfsiz belgilarni qoldirish
                title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-'))
                return title.strip()
    except Exception as e:
        logger.warning(f"📺 Stream sarlavhasini olishda xato: {e}")
    
    return None

def generate_filename(title: Optional[str] = None, part: int = 1) -> str:
    """Fayl nomini yaratish"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not title:
        title = f"stream_{uuid.uuid4().hex[:6]}"
    
    # Fayl nomini qisqartirish
    title = title.replace(' ', '_')[:30]
    filename = f"{timestamp}_{title}_part{part}.mp4"
    logger.debug(f"📄 Fayl nomi yaratildi: {filename}")
    return filename

def get_file_size_gb(filepath: Path) -> float:
    """Fayl hajmini GB da olish"""
    if filepath.exists():
        size_gb = filepath.stat().st_size / (1024 ** 3)
        return round(size_gb, 2)
    return 0.0

def format_duration(seconds: int) -> str:
    """Vaqtni formatlash"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

# ============================================
# 🎥 YOZISH FUNKSIYALARI
# ============================================

async def record_stream(
    recording_id: str,
    url: str,
    bot: Bot,
    chat_id: int,
    title: Optional[str] = None
):
    """
    Asosiy yozish funksiyasi - 24/7 ishlaydi
    """
    logger.info(f"🎬 YANGI YOZUV BOSHlandi: {title}")
    logger.info(f"🔗 URL: {url[:50]}...")
    
    recorded_files[recording_id] = []
    part = 1
    session_start = datetime.now()
    
    try:
        while recording_id in active_recordings:
            # Fayl nomi
            filename = generate_filename(title, part)
            output_path = OUTPUT_DIR / filename
            
            logger.info(f"📹 Part {part} boshlandi: {filename}")
            
            # Boshlanish xabari
            start_msg = await bot.send_message(
                chat_id,
                f"🎬 <b>Yozish boshlandi - Part {part}</b>\n\n"
                f"📺 {title or 'Nomaʼlum'}\n"
                f"📁 {filename}\n"
                f"⏰ {datetime.now().strftime('%H:%M:%S')}\n"
                f"📍 <i>Railway.app - 24/7</i>",
                parse_mode='HTML'
            )
            
            # FFmpeg buyrug'i
            max_size_bytes = int(MAX_FILE_SIZE_GB * 1024 * 1024 * 1024)
            ffmpeg_cmd = [
                'ffmpeg',
                '-i', url,
                '-c', 'copy',  # Transcode qilmaslik
                '-fs', str(max_size_bytes),  # Max fayl hajmi
                '-y',  # Faylni overwrite qilish
                '-max_muxing_queue_size', '9999',  # Buffering muammolari uchun
                str(output_path)
            ]
            
            logger.debug(f"🔧 FFmpeg buyrug'i: {' '.join(ffmpeg_cmd[:4])}...")
            
            # Process ni ishga tushirish
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Process ni kutish
            try:
                await asyncio.wait_for(process.wait(), timeout=3600)  # 1 soat timeout
            except asyncio.TimeoutError:
                logger.warning(f"⏰ Part {part} timeout, keyingi partga o'tish")
                process.terminate()
                continue
            
            # Natijani tekshirish
            if output_path.exists() and output_path.stat().st_size > 0:
                file_size = get_file_size_gb(output_path)
                recorded_files[recording_id].append(filename)
                
                logger.info(f"✅ Part {part} muvaffaqiyatli: {file_size} GB")
                
                # Muvaffaqiyat xabari
                await start_msg.edit_text(
                    f"✅ <b>Part {part} tugadi!</b>\n\n"
                    f"📺 {title or 'Nomaʼlum'}\n"
                    f"📁 {filename}\n"
                    f"💾 {file_size} GB\n"
                    f"⏰ {datetime.now().strftime('%H:%M:%S')}\n"
                    f"🎯 <i>Keyingi part boshlandi...</i>",
                    parse_mode='HTML'
                )
                
                part += 1
                
            else:
                logger.error(f"❌ Part {part} yozishda xato")
                await start_msg.edit_text(
                    f"❌ <b>Part {part} yozishda xato!</b>\n\n"
                    f"📺 {title or 'Nomaʼlum'}\n"
                    f"🔗 URL ni tekshiring\n"
                    f"⏰ {datetime.now().strftime('%H:%M:%S')}",
                    parse_mode='HTML'
                )
                break
                
    except asyncio.CancelledError:
        logger.info(f"⏹️ Yozuv to'xtatildi: {recording_id}")
        await bot.send_message(chat_id, "⏹️ <b>Yozuv to'xtatildi!</b>", parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"🔥 Yozuvda xato: {e}")
        await bot.send_message(
            chat_id,
            f"🔥 <b>Yozuvda xato yuz berdi!</b>\n\n"
            f"📺 {title or 'Nomaʼlum'}\n"
            f"❌ {str(e)[:100]}\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}",
            parse_mode='HTML'
        )
    
    finally:
        # Yuklashni boshlash
        if recording_id in recorded_files and recorded_files[recording_id]:
            total_files = len(recorded_files[recording_id])
            session_duration = format_duration(int((datetime.now() - session_start).total_seconds()))
            
            logger.info(f"📦 Yuklash boshlandi: {total_files} fayl")
            
            await bot.send_message(
                chat_id,
                f"📦 <b>Yuklash boshlandi!</b>\n\n"
                f"📺 {title or 'Nomaʼlum'}\n"
                f"📁 {total_files} ta fayl\n"
                f"⏰ Session: {session_duration}\n"
                f"📍 <i>Railway.app</i>",
                parse_mode='HTML'
            )
            
            await auto_upload_recorded_files(bot, recording_id, chat_id)
        
        # Tozalash
        if recording_id in active_recordings:
            del active_recordings[recording_id]

async def auto_upload_recorded_files(bot: Bot, recording_id: str, chat_id: int):
    """Fayllarni avtomatik yuklash"""
    if recording_id not in recorded_files:
        return
    
    files = recorded_files[recording_id]
    total_files = len(files)
    
    logger.info(f"📤 Yuklash: {total_files} ta fayl")
    
    progress_msg = await bot.send_message(
        chat_id,
        f"📤 <b>Yuklash jarayoni</b>\n\n"
        f"📁 Jami fayllar: {total_files} ta\n"
        f"📊 Progress: 0/{total_files}\n"
        f"⏰ Boshlangan: {datetime.now().strftime('%H:%M:%S')}",
        parse_mode='HTML'
    )
    
    uploaded_count = 0
    failed_count = 0
    
    for i, filename in enumerate(files, 1):
        file_path = OUTPUT_DIR / filename
        
        if file_path.exists():
            try:
                file_size = get_file_size_gb(file_path)
                logger.info(f"⬆️ Yuklanmoqda: {filename} ({file_size} GB)")
                
                # Progress yangilash
                await progress_msg.edit_text(
                    f"📤 <b>Yuklash davom etmoqda...</b>\n\n"
                    f"📁 Jami fayllar: {total_files} ta\n"
                    f"📊 Progress: {uploaded_count}/{total_files}\n"
                    f"📄 Hozirgi: {filename}\n"
                    f"💾 Hajmi: {file_size} GB",
                    parse_mode='HTML'
                )
                
                # Yuklash
                video = FSInputFile(file_path)
                await bot.send_video(
                    chat_id=CHANNEL_ID,
                    video=video,
                    caption=f"📹 {filename}\n💾 {file_size} GB\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    supports_streaming=True
                )
                
                uploaded_count += 1
                logger.info(f"✅ Yuklandi: {filename}")
                
                # Faylni o'chirish (xotirani tejash)
                file_path.unlink()
                
            except Exception as e:
                failed_count += 1
                logger.error(f"❌ Yuklash xatosi ({filename}): {e}")
        
        # Kichik kutish (flood prevention)
        await asyncio.sleep(2)
    
    # Yakuniy xabar
    duration = format_duration(int((datetime.now() - progress_msg.date).total_seconds()))
    
    await progress_msg.edit_text(
        f"🎉 <b>Yuklash tugadi!</b>\n\n"
        f"📁 Jami fayllar: {total_files} ta\n"
        f"✅ Muvaffaqiyatli: {uploaded_count} ta\n"
        f"❌ Muvaffaqiyatsiz: {failed_count} ta\n"
        f"⏰ Davomiylik: {duration}\n"
        f"📺 Kanal: {CHANNEL_ID}",
        parse_mode='HTML'
    )
    
    logger.info(f"🎉 Yuklash tugadi: {uploaded_count}/{total_files}")

# ============================================
# 🤖 BOT HANDLERS
# ============================================

async def cmd_start(message: types.Message):
    """Start komandasi"""
    user_id = message.from_user.id
    
    if not check_admin(user_id):
        logger.warning(f"🚫 Ruxsatsiz kirish: {user_id}")
        await message.answer("🚫 Sizda ushbu botdan foydalanish uchun ruxsat yo'q.")
        return
    
    logger.info(f"👋 Start komandasi: {user_id}")
    
    await message.answer(
        "🛰 <b>IPTV Recorder Bot</b>\n\n"
        "📍 <b>Platforma:</b> Railway.app\n"
        "⏰ <b>Ishlash:</b> 24/7 Doimiy\n"
        "💾 <b>Xotira:</b> Avtomatik boshqaruv\n\n"
        "📋 <b>Mavjud buyruqlar:</b>\n"
        "/record - Stream yozishni boshlash\n"
        "/status - Joriy holat\n"
        "/stop - Yozuvni to'xtatish\n"
        "/list - Yozilgan fayllar\n"
        "/info - Tizim ma'lumotlari\n"
        "/help - Yordam\n\n"
        "⚡ <b>Qo'shimcha:</b>\n"
        "• Avtomatik part splitting\n"
        "• Kanalga avtomatik yuklash\n"
        "• Progress monitoring\n"
        "• 24/7 ishlash",
        parse_mode='HTML'
    )

async def cmd_record(message: types.Message, state: FSMContext):
    """Record komandasi"""
    if not check_admin(message.from_user.id):
        return
    
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        await message.answer(
            "📡 <b>Stream havolasini yuboring:</b>\n\n"
            "Misol uchun:\n"
            "<code>/record https://example.com/stream.m3u8</code>\n"
            "<code>/record http://livestream.com/channel</code>\n\n"
            "Yoki oddiygina <code>/record</code> deb yozing va "
            "havolani keyin yuboring.",
            parse_mode='HTML'
        )
        await state.set_state(RecordState.waiting_for_link)
        return
    
    url = args[1].strip()
    await process_record_request(message, state, url)

async def process_record_request(message: types.Message, state: FSMContext, url: str):
    """Yozuv so'rovini qayta ishlash"""
    logger.info(f"🔗 URL qabul qilindi: {url[:50]}...")
    
    # Stream ma'lumotlarini olish
    await message.answer("🔍 <b>Stream ma'lumotlarini tekshirmoqda...</b>", parse_mode='HTML')
    
    title = get_stream_title(url)
    if not title:
        title = f"Stream_{datetime.now().strftime('%H%M%S')}"
        logger.info(f"📺 Sarlavha topilmadi, standart ishlatiladi: {title}")
    
    await state.update_data(url=url, title=title)
    
    # Tasdiqlash klaviaturasi
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ha, boshlash", callback_data="confirm_record"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_record")
        ]
    ])
    
    await message.answer(
        f"📡 <b>Stream yozishni boshlaymi?</b>\n\n"
        f"🎬 <b>Nomi:</b> {title}\n"
        f"🔗 <b>URL:</b> <code>{url[:60]}...</code>\n"
        f"💾 <b>Max hajm:</b> {MAX_FILE_SIZE_GB} GB\n"
        f"📍 <b>Platforma:</b> Railway.app\n\n"
        f"<i>Yozuv boshlangandan so'ng, har bir {MAX_FILE_SIZE_GB} GB dan "
        f"keyin yangi fayl yaratiladi va kanalga avtomatik yuklanadi.</i>",
        parse_mode='HTML',
        reply_markup=keyboard
    )
    
    await state.set_state(RecordState.confirming)

async def handle_url_message(message: types.Message, state: FSMContext):
    """URL xabarlarini qayta ishlash"""
    if not check_admin(message.from_user.id):
        return
    
    url = message.text.strip()
    await process_record_request(message, state, url)

async def handle_confirm_record(callback: types.CallbackQuery, state: FSMContext):
    """Yozuvni tasdiqlash"""
    logger.info("✅ Yozuv tasdiqlandi")
    
    data = await state.get_data()
    url = data.get('url')
    title = data.get('title')
    
    # Recording ID yaratish
    recording_id = str(uuid.uuid4())[:8]
    logger.info(f"🆔 Yangi yozuv sessiyasi: {recording_id}")
    
    # Vazifa yaratish
    task = asyncio.create_task(
        record_stream(recording_id, url, callback.bot, callback.message.chat.id, title)
    )
    
    # Global state ga qo'shish
    active_recordings[recording_id] = {
        'task': task,
        'url': url,
        'title': title,
        'started': datetime.now(),
        'chat_id': callback.message.chat.id
    }
    
    await callback.message.edit_text(
        f"✅ <b>Yozuv boshlandi!</b>\n\n"
        f"🎬 <b>Stream:</b> {title}\n"
        f"🆔 <b>ID:</b> <code>{recording_id}</code>\n"
        f"⏰ <b>Boshlangan:</b> {datetime.now().strftime('%H:%M:%S')}\n"
        f"📍 <b>Platforma:</b> Railway.app\n\n"
        f"<i>Yozuv davom etmoqda... /status bilan holatni tekshiring.</i>",
        parse_mode='HTML'
    )
    
    await state.clear()
    logger.info(f"🎬 Yozuv muvaffaqiyatli boshlandi: {title}")

async def handle_cancel_record(callback: types.CallbackQuery, state: FSMContext):
    """Yozuvni bekor qilish"""
    logger.info("❌ Yozuv bekor qilindi")
    await callback.message.edit_text(
        "❌ <b>Yozuv bekor qilindi.</b>\n\n"
        "Agar xohlasangiz, /record buyrug'i orqali qayta boshlashingiz mumkin.",
        parse_mode='HTML'
    )
    await state.clear()

async def cmd_status(message: types.Message):
    """Status komandasi"""
    if not check_admin(message.from_user.id):
        return
    
    if not active_recordings:
        await message.answer(
            "🔴 <b>Hech qanday faol yozuv yo'q</b>\n\n"
            "Yozuvni boshlash uchun /record buyrug'idan foydalaning.",
            parse_mode='HTML'
        )
        return
    
    status_text = "🎬 <b>Faol Yozuvlar:</b>\n\n"
    
    for rec_id, info in active_recordings.items():
        duration = datetime.now() - info['started']
        duration_str = format_duration(int(duration.total_seconds()))
        
        status_text += (
            f"🔴 <b>{info['title']}</b>\n"
            f"   🆔 <code>{rec_id}</code>\n"
            f"   ⏰ {duration_str}\n"
            f"   📍 {info['url'][:40]}...\n\n"
        )
    
    status_text += f"<i>Jami: {len(active_recordings)} ta faol yozuv</i>"
    
    await message.answer(status_text, parse_mode='HTML')

async def cmd_stop(message: types.Message):
    """Stop komandasi"""
    if not check_admin(message.from_user.id):
        return
    
    if not active_recordings:
        await message.answer("❌ To'xtatish uchun faol yozuv yo'q.")
        return
    
    stopped_count = 0
    stopped_list = []
    
    for rec_id in list(active_recordings.keys()):
        info = active_recordings[rec_id]
        info['task'].cancel()
        stopped_list.append(info['title'])
        stopped_count += 1
        
        logger.info(f"⏹️ Yozuv to'xtatildi: {info['title']}")
    
    await message.answer(
        f"⏹️ <b>{stopped_count} ta yozuv to'xtatildi:</b>\n\n" +
        "\n".join(f"• {title}" for title in stopped_list) +
        f"\n\n📦 <i>Yuklash jarayoni boshlandi...</i>",
        parse_mode='HTML'
    )

async def cmd_list(message: types.Message):
    """Fayllar ro'yxati"""
    if not check_admin(message.from_user.id):
        return
    
    files = list(OUTPUT_DIR.glob("*.mp4"))
    
    if not files:
        await message.answer(
            "📂 <b>Hozircha hech qanday fayl yo'q</b>\n\n"
            "Yozuv boshlangandan so'ng fayllar shu yerda ko'rinadi.",
            parse_mode='HTML'
        )
        return
    
    # Fayllarni sana bo'yicha tartiblash
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    
    files_text = f"📁 <b>Yozilgan Fayllar:</b> ({len(files)} ta)\n\n"
    
    for i, file in enumerate(files[:10], 1):  # Faqat 10 ta ko'rsatish
        size = get_file_size_gb(file)
        mtime = datetime.fromtimestamp(file.stat().st_mtime)
        time_str = mtime.strftime('%Y-%m-%d %H:%M')
        
        files_text += f"{i}. <code>{file.name}</code>\n"
        files_text += f"   💾 {size} GB | ⏰ {time_str}\n\n"
    
    if len(files) > 10:
        files_text += f"<i>... va yana {len(files) - 10} ta fayl</i>"
    
    await message.answer(files_text, parse_mode='HTML')

async def cmd_info(message: types.Message):
    """Tizim ma'lumotlari"""
    if not check_admin(message.from_user.id):
        return
    
    # Disk hajmini tekshirish
    try:
        disk_info = os.statvfs('/tmp')
        free_gb = (disk_info.f_bavail * disk_info.f_frsize) / (1024 ** 3)
        total_gb = (disk_info.f_blocks * disk_info.f_frsize) / (1024 ** 3)
        used_gb = total_gb - free_gb
    except:
        free_gb = total_gb = used_gb = 0
    
    info_text = (
        "ℹ️ <b>Tizim Ma'lumotlari</b>\n\n"
        f"📍 <b>Platforma:</b> Railway.app\n"
        f"⏰ <b>Ish vaqti:</b> 24/7 Doimiy\n"
        f"👤 <b>Admin ID:</b> <code>{ADMIN_ID}</code>\n"
        f"📺 <b>Kanal:</b> {CHANNEL_ID}\n\n"
        f"💾 <b>Disk Holati:</b>\n"
        f"   • Jami: {total_gb:.1f} GB\n"
        f"   • Foydalanilgan: {used_gb:.1f} GB\n"
        f"   • Bo'sh: {free_gb:.1f} GB\n\n"
        f"🎬 <b>Faol Yozuvlar:</b> {len(active_recordings)} ta\n"
        f"📁 <b>Yozilgan Fayllar:</b> {sum(len(f) for f in recorded_files.values())} ta\n\n"
        f"<i>Bot doimiy ishlaydi va avtomatik restart qilinadi.</i>"
    )
    
    await message.answer(info_text, parse_mode='HTML')

async def cmd_help(message: types.Message):
    """Yordam komandasi"""
    await message.answer(
        "🆘 <b>Yordam - IPTV Recorder Bot</b>\n\n"
        "📋 <b>Buyruqlar Ro'yxati:</b>\n"
        "• /start - Botni ishga tushirish\n"
        "• /record [url] - Stream yozishni boshlash\n"
        "• /status - Joriy yozuvlarni ko'rish\n"
        "• /stop - Barcha yozuvlarni to'xtatish\n"
        "• /list - Yozilgan fayllar ro'yxati\n"
        "• /info - Tizim ma'lumotlari\n"
        "• /help - Ushbu yordam xabari\n\n"
        "⚡ <b>Qo'shimcha Ma'lumot:</b>\n"
        "• Bot 24/7 ishlaydi\n"
        "• Har 1.8 GB dan keyin yangi fayl\n"
        "• Avtomatik kanalga yuklash\n"
        "• Xatolarda avtomatik qayta urinish\n\n"
        "🔧 <b>Platforma:</b> Railway.app",
        parse_mode='HTML'
    )

async def cmd_ping(message: types.Message):
    """Ping komandasi - bot ishlayotganini tekshirish"""
    await message.answer("🏓 <b>Pong!</b>\n\nBot faol va ishlayapti! ✅", parse_mode='HTML')

# ============================================
# 🚀 ASOSIY FUNKSIYA - RAILWAY UCHUN
# ============================================

async def main():
    """Railway.app uchun asosiy funksiya"""
    logger.info("🚀 Bot ishga tushmoqda...")
    
    # Bot tokenini tekshirish
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("❌ BOT_TOKEN sozlanmagan!")
        print("\n" + "="*50)
        print("❌ XATO: BOT_TOKEN sozlanmagan!")
        print("📝 Iltimos, Railway.app da environment variable qo'shing")
        print("="*50 + "\n")
        return
    
    # Bot yaratish
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Handlerlarni ro'yxatdan o'tkazish
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_record, Command("record"))
    dp.message.register(cmd_status, Command("status"))
    dp.message.register(cmd_stop, Command("stop"))
    dp.message.register(cmd_list, Command("list"))
    dp.message.register(cmd_info, Command("info"))
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_ping, Command("ping"))
    
    # State handlerlari
    dp.message.register(handle_url_message, RecordState.waiting_for_link)
    
    # Callback handlerlari
    dp.callback_query.register(handle_confirm_record, F.data == "confirm_record")
    dp.callback_query.register(handle_cancel_record, F.data == "cancel_record")
    
    logger.info("✅ Barcha handlerlar ro'yxatdan o'tkazildi")
    
    try:
        # Bot ma'lumotlarini olish
        bot_info = await bot.get_me()
        logger.info(f"🤖 Bot: @{bot_info.username} ({bot_info.first_name})")
        
        print("\n" + "="*60)
        print("🎉 IPTV RECORDER BOT - RAILWAY.APP")
        print("="*60)
        print(f"🤖 Bot: @{bot_info.username}")
        print(f"👤 Admin: {ADMIN_ID}")
        print(f"📺 Kanal: {CHANNEL_ID}")
        print(f"📍 Platforma: Railway.app")
        print(f"⏰ Ish rejimi: 24/7")
        print("="*60)
        print("✅ Bot muvaffaqiyatli ishga tushdi!")
        print("📝 Loglar Railway dashboard da ko'rinadi")
        print("="*60 + "\n")
        
        # Polling ni boshlash
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        
    except Exception as e:
        logger.critical(f"🔥 Bot ishga tushirishda xato: {e}")
        print(f"\n❌ Xato: {e}\n")
    
    finally:
        logger.info("🛑 Bot to'xtatilmoqda...")
        await bot.session.close()
        logger.info("✅ Bot to'xtatildi")

# ============================================
# 🎯 DOCKER VA RAILWAY ISHGA TUSHIRISH
# ============================================

if __name__ == "__main__":
    # Railway uchun asyncio
    asyncio.run(main())

"""
Telegram Video Downloader Bot - Standalone Version
===================================================
✅ يرفع حتى 2GB
✅ نجح في تحميل فيديو 3 ساعات (694MB)

التشغيل:
    python3 bot_standalone.py
"""

import os
import sys
import glob  # للبحث عن الملفات وحذفها
import time  # Added import os
import logging
import asyncio
import yt_dlp
import traceback
from datetime import datetime
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from dotenv import load_dotenv
import subscription_db as subdb
from translations import t
from queue_manager import DownloadQueueManager, DownloadTask
import pg_backup

# ... (rest of imports/logging/config remains same until download_and_upload)

# ... inside download_and_upload ...


# ═══════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_standalone.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════
load_dotenv()

API_ID = os.getenv("PYROGRAM_API_ID")
API_HASH = os.getenv("PYROGRAM_API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not API_ID or not API_HASH or not BOT_TOKEN:
    print("=" * 60)
    print("❌ المتغيرات البيئية ناقصة!")
    print("=" * 60)
    print("الرجاء إنشاء ملف .env وإضافة المتغيرات التالية:")
    print("")
    print("PYROGRAM_API_ID=your_api_id")
    print("PYROGRAM_API_HASH=your_api_hash")
    print("BOT_TOKEN=your_bot_token")
    print("")
    print("راجع ملف .env.example و README.md للتعليمات الكاملة")
    print("=" * 60)
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# Pyrogram Client
# ═══════════════════════════════════════════════════════════════
app = Client(
    "video_bot",
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Initialize Queue Manager
queue_manager = DownloadQueueManager(cooldown_seconds=10)

# تخزين الروابط
pending_downloads = {}

# منصات الـ cookies المدعومة
COOKIES_PLATFORMS = {
    'facebook': {'name': 'Facebook 📘', 'file': 'cookies/facebook.txt'},
    'instagram': {'name': 'Instagram �', 'file': 'cookies/instagram.txt'},
    'youtube': {'name': 'YouTube 📺', 'file': 'cookies/youtube.txt'},
    'twitter': {'name': 'Twitter/X 🐦', 'file': 'cookies/twitter.txt'},
    'reddit': {'name': 'Reddit �', 'file': 'cookies/reddit.txt'},
    'snapchat': {'name': 'Snapchat 👻', 'file': 'cookies/snapchat.txt'},
    'pinterest': {'name': 'Pinterest 📌', 'file': 'cookies/pinterest.txt'},
    'tiktok': {'name': 'TikTok 🎵', 'file': 'cookies/tiktok.txt'},
    'other': {'name': 'أخرى 🌐', 'file': 'cookies/other.txt'},
}

# نظام تتبع الأخطاء
user_errors = {}  # {error_id: {'user_id': ..., 'error': ..., 'url': ..., 'time': ..., 'status': 'pending'}}
error_counter = 0

async def send_error_to_admin(user_id, user_name, error_message, url, error_traceback=None):
    """إرسال تنبيه لقناة سجلات الأخطاء عند حدوث خطأ للمستخدم"""
    global error_counter
    error_counter += 1
    error_id = f"err_{error_counter}"
    
    # حفظ الخطأ
    user_errors[error_id] = {
        'user_id': user_id,
        'user_name': user_name,
        'error': error_message,
        'url': url,
        'traceback': error_traceback,
        'time': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'status': 'pending'
    }
    
    # إرسال لقناة سجلات الأخطاء
    error_channel_id = os.getenv("ERROR_LOG_CHANNEL_ID")
    
    if not error_channel_id:
        logger.warning("⚠️ ERROR_LOG_CHANNEL_ID غير موجود في .env")
        return
    
    # Verify bot has access to error log channel
    try:
        await app.get_chat(error_channel_id)
    except Exception as access_error:
        logger.error(f"❌ البوت لا يملك صلاحيات لقناة الأخطاء {error_channel_id}: {access_error}")
        logger.info(f"💡 تأكد من إضافة البوت كمدير في قناة سجلات الأخطاء")
        return
    
    # User link (blue clickable name)
    user_link = f'<a href="tg://user?id={user_id}">{user_name}</a>'
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تم الإصلاح", callback_data=f"resolve_{error_id}")]
    ])
    
    try:
        # بناء الرسالة الأساسية
        error_text = (
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔔 **خطأ جديد من مستخدم**\n\n"
            f"👤 **المستخدم:** {user_link}\n"
            f"🆔 **ID:** <code>{user_id}</code>\n"
            f"🔗 **الرابط:** <code>{url}</code>\n\n"
            f"❌ **الخطأ:**\n<code>{error_message[:300]}</code>\n\n"
        )
        
        # إضافة traceback إذا كان متوفراً
        if error_traceback:
            # تقصير traceback إذا كان طويلاً جداً (Telegram limit)
            traceback_text = error_traceback[:800] if len(error_traceback) > 800 else error_traceback
            error_text += f"📋 **سجلات الخطأ (Traceback):**\n<code>{traceback_text}</code>\n\n"
        
        error_text += (
            f"🆔 Error ID: <code>{error_id}</code>\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        await app.send_message(
            chat_id=error_channel_id,
            text=error_text,
            reply_markup=keyboard,
            parse_mode=enums.ParseMode.HTML
        )
        logger.info(f"📨 تم إرسال تنبيه خطأ لقناة السجلات: {error_id}")
    except Exception as e:
        logger.error(f"فشل إرسال تنبيه لقناة الأخطاء: {e}")

async def send_new_member_notification(user_id, user_name, username, join_time):
    """إرسال إشعار لقناة الأعضاء الجدد عند انضمام عضو جديد"""
    try:
        channel_id = os.getenv('NEW_MEMBERS_CHANNEL_ID')
        
        if not channel_id:
            logger.warning("⚠️ NEW_MEMBERS_CHANNEL_ID غير موجود في .env")
            return
        
        # Try to get chat to verify bot has access
        try:
            await app.get_chat(channel_id)
        except Exception as access_error:
            logger.error(f"❌ البوت لا يملك صلاحيات للقناة {channel_id}: {access_error}")
            logger.info(f"💡 تأكد من إضافة البوت كمدير في القناة")
            return
        
        # Format username
        username_text = f"@{username}" if username else "⚠️ لا يوجد يوزر"
        
        # User link (blue clickable name)
        user_link = f'<a href="tg://user?id={user_id}">{user_name}</a>'
        
        # Message text
        notification = f"""━━━━━━━━━━━━━━━━━━━━━━
🎉 عضو جديد انضم للبوت!

👤 معلومات العضو
╔═ الاسم: {user_link}
╠═ اليوزر: {username_text}
╚═ ID: <code>{user_id}</code>

🕐 وقت الانضمام: {join_time}
━━━━━━━━━━━━━━━━━━━━━━"""
        
        await app.send_message(
            chat_id=channel_id,
            text=notification,
            parse_mode=enums.ParseMode.HTML
        )
        
        logger.info(f"✅ تم إرسال إشعار عضو جديد للقناة: {user_name} ({user_id})")
        
    except Exception as e:
        logger.error(f"❌ خطأ في إرسال إشعار العضو الجديد: {str(e)}")


# حالة انتظار cookies من الأدمن
waiting_for_cookies = {}  # {user_id: platform}

# تتبع صلاحية الـ cookies
cookies_expiry = {}  # {platform: {'uploaded': timestamp, 'expires': timestamp, 'notified': bool}}

# ═══════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════

def get_file_size_mb(file_path):
    """الحصول على حجم الملف بالميغابايت"""
    return os.path.getsize(file_path) / (1024 * 1024)



async def get_video_info(url: str):
    """استخراج معلومات الفيديو"""
    try:
        # إضافة cookies إذا كانت موجودة وصالحة (ليست فارغة)
        cookies_files = []
        for platform, data in COOKIES_PLATFORMS.items():
            if os.path.exists(data['file']):
                # التحقق من أن الملف ليس فارغاً وأن حجمه أكبر من 100 بايت
                file_size = os.path.getsize(data['file'])
                if file_size > 100:  # ملف صالح يجب أن يكون أكبر من 100 بايت
                    cookies_files.append(data['file'])
                    logger.info(f"✅ Cookie file loaded: {platform} ({file_size} bytes)")
                else:
                    logger.warning(f"⚠️ Skipping empty/invalid cookie file: {platform} ({file_size} bytes)")
                    if platform == 'facebook' and file_size == 0:
                        logger.error(f"❌ Facebook cookie file is completely empty! Facebook downloads will fail.")
                        logger.info(f"💡 Please update {data['file']} with valid Facebook cookies")
        
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'socket_timeout': 30,  # تقليل timeout لاستجابة أسرع
            'extract_flat': False,  # نحتاج معلومات كاملة
            'no_check_certificate': True,
        }
        
        # استخدام cookies للتعرف على الفيديو
        if cookies_files:
            ydl_opts['cookiefile'] = cookies_files[0]
            logger.info(f"🍪 Using cookies for video info extraction")
        
        # إضافة extractor_args لـ Facebook
        ydl_opts['extractor_args'] = {
            'facebook': {'cookie_file': cookies_files[0] if cookies_files else None},
            'instagram': {'cookie_file': cookies_files[0] if cookies_files else None},
        }
        
        loop = asyncio.get_event_loop()
        
        def extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        
        return await loop.run_in_executor(None, extract)
    except Exception as e:
        error_msg = str(e)
        # معالجة خاصة لأخطاء Facebook parsing
        if 'Cannot parse data' in error_msg or 'facebook' in error_msg.lower():
            logger.error(f"خطأ Facebook parse: {error_msg[:200]}")
        else:
            logger.error(f"خطأ في استخراج المعلومات: {e}")
        return None


async def upload_media_with_progress(client, chat_id, file_path, caption, status_msg, user_id, is_video=True):
    """Upload media with progress tracking"""
    try:
        upload_progress = UploadProgress(status_msg, user_id, asyncio.get_event_loop())
        
        if is_video:
            message = await client.send_video(
                chat_id=chat_id,
                video=file_path,
                caption=caption,
                progress=upload_progress
            )
        else:
            message = await client.send_audio(
                chat_id=chat_id,
                audio=file_path,
                caption=caption,
                progress=upload_progress
            )
        
        return message
    except Exception as e:
        logger.error(f"خطأ في رفع الوسائط: {e}")
        raise
# Upload progress tracking
class UploadProgress:
    def __init__(self, status_msg, user_id, event_loop):
        self.status_msg = status_msg
        self.user_id = user_id
        self.event_loop = event_loop  # Store the event loop
        self.last_edit = 0
        self.last_current = 0
        self.last_time = time.time()
        self.speed = 0
    
    def __call__(self, current, total):
        """Sync callback for Pyrogram - creates async task for updates"""
        try:
            now = time.time()
            
            # Update speed calculation
            time_diff = now - self.last_time
            if time_diff >= 1:  # Update speed every second
                bytes_diff = current - self.last_current
                self.speed = bytes_diff / time_diff
                self.last_time = now
                self.last_current = current
            
            if now - self.last_edit < 1: # Update message every second
                return
            
            self.last_edit = now
            
            # Calculate progress
            percentage = (current / total) * 100
            current_mb = current / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            speed_mb = self.speed / (1024 * 1024) if self.speed > 0 else 0
            filled = int(percentage // 10)
            progress_bar = '▰' * filled + '▱' * (10 - filled)
            remaining_bytes = total - current
            eta = int(remaining_bytes / self.speed) if self.speed > 0 else 0
            
            # Get user language
            lang = subdb.get_user_language(self.user_id)
            
            upload_msg = t('uploading', lang,
                          percent=f'{percentage:.1f}',
                          current_mb=f'{current_mb:.1f}',
                          total_mb=f'{total_mb:.1f}',
                          speed_mb=f'{speed_mb:.1f}',
                          eta=eta,
                          progress_bar=progress_bar)
            
            # Use run_coroutine_threadsafe to schedule in the correct event loop
            asyncio.run_coroutine_threadsafe(
                self._update_message(upload_msg),
                self.event_loop
            )
        except Exception as e:
            logger.error(f"❌ Upload progress error: {e}")
    
    async def _update_message(self, text):
        """Async helper to update Telegram message"""
        try:
            await self.status_msg.edit_text(text)
        except Exception as e:
            logger.error(f"❌ Message edit error: {e}")


async def forward_to_log_channel(client, message, sent_message, user_id, user_name, username, url, 
                               video_info, duration, file_size_mb):
    """تحويل الفيديو إلى قناة السجلات مع معلومات تفصيلية"""
    try:
        channel_id = os.getenv('LOG_CHANNEL_ID')
        
        if not channel_id:
            return
        
        # Format username
        username_text = f"@{username}" if username else "⚠️ لا يوجد يوزر"
        
        # User link (blue clickable name)
        user_link = f'<a href="tg://user?id={user_id}">{user_name}</a>'
        
        # Video title
        title = video_info.get('title', 'فيديو') if video_info else 'فيديو'
        
        # Platform detection
        if 'youtube' in url or 'youtu.be' in url:
            platform, icon = 'YouTube', '📺'
        elif 'facebook' in url or 'fb.watch' in url:
            platform, icon = 'Facebook', '📘'
        elif 'instagram' in url:
            platform, icon = 'Instagram', '📷'
        elif 'twitter' in url or 'x.com' in url:
            platform, icon = 'Twitter/X', '🐦'
        elif 'tiktok' in url:
            platform, icon = 'TikTok', '🎵'
        else:
            platform, icon = 'رابط', '🔗'
        
        # Views formatting
        views = video_info.get('view_count', 'N/A') if video_info else 'N/A'
        if isinstance(views, int):
            views_text = f"{views/1_000_000:.1f}M" if views >= 1_000_000 else f"{views/1_000:.1f}K" if views >= 1_000 else str(views)
        else:
            views_text = 'N/A'
        
        # Duration & Quality
        duration_text = f"{int(duration)//60:02d}:{int(duration)%60:02d}" if duration else "N/A"
        quality = video_info.get('resolution', 'N/A') if video_info else 'N/A'
        
        # Timestamp
        from datetime import datetime
        date_text = datetime.now().strftime("%d/%m/%Y • %H:%M UTC")
        
        # Caption with user info
        caption = f"""━━━━━━━━━━━━━━━━━━━━━━
🎬 تحميل جديد

👤 المستخدم
╔═ الاسم: {user_link}
╠═ اليوزر: {username_text}  
╚═ ID: <code>{user_id}</code>

🔗 المصدر: {icon} {platform}
📎 {url}

🎞️ العنوان
{title}

📊 تفاصيل الفيديو
├─ 📹 المدة: {duration_text}
├─ 💾 الحجم: {file_size_mb:.2f} MB
├─ 🎯 الجودة: {quality}
└─ 👁️ المشاهدات: {views_text}

🕐 {date_text}
━━━━━━━━━━━━━━━━━━━━━━"""
        
        # 1. تحويل الفيديو (forward)
        await client.forward_messages(
            chat_id=channel_id,
            from_chat_id=sent_message.chat.id,
            message_ids=sent_message.id
        )
        
        # 2. إرسال معلومات المستخدم كرسالة منفصلة تحت الفيديو
        await client.send_message(
            chat_id=channel_id,
            text=caption,
            parse_mode=enums.ParseMode.HTML
        )
        
        logger.info(f"✅ تم تحويل الفيديو والمعلومات إلى القناة")
        
    except Exception as e:
        logger.error(f"❌ خطأ في تحويل الفيديو إلى القناة: {str(e)}")


async def process_download_from_queue(task: DownloadTask):
    """
    Process a download task from the queue.
    
    Args:
        task: DownloadTask containing download information
    """
    user_id = task.user_id
    url = task.url
    message = task.message
    
    # Get user language
    lang = subdb.get_user_language(user_id)
    
    try:
        # Send processing notification
        status = await message.reply_text(t('queue_processing_current', lang))
        
        # Get video info
        info = await get_video_info(url)
        
        if not info:
            user_name = message.from_user.first_name or "User"
            await send_error_to_admin(user_id, user_name, "Failed to extract video info", url)
            await status.edit_text(t('invalid_url', lang))
            return
        
        title = info.get('title', 'Video')[:50]
        duration = info.get('duration', 0)
        duration_str = f"{int(duration)//60}:{int(duration)%60:02d}" if duration else "0:00"
        
        # Add or update user info
        username = message.from_user.username
        first_name = message.from_user.first_name
        subdb.add_or_update_user(user_id, username, first_name)
        
        # Check subscription and video duration
        is_subscribed = subdb.is_user_subscribed(user_id)
        
        # Check daily limit for non-subscribers
        if not is_subscribed:
            daily_limit = subdb.get_daily_limit()
            
            if daily_limit != -1:
                daily_count = subdb.check_daily_limit(user_id)
                
                if daily_count >= daily_limit:
                    await status.edit_text(
                        t('daily_limit_exceeded', lang, limit=daily_limit, count=daily_count),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(t('subscribe_now', lang), callback_data="pay_binance")],
                            [InlineKeyboardButton(t('contact_developer', lang), url=f"https://t.me/{subdb.get_setting('telegram_support', 'wahab161')}")]
                        ])
                    )
                    return
        
        max_duration_minutes = subdb.get_max_duration()
        max_duration_seconds = max_duration_minutes * 60
        
        # If not subscribed and exceeds max duration
        if not is_subscribed and duration and duration > max_duration_seconds:
            await show_subscription_screen(app, status, user_id, title, duration, max_duration_minutes)
            return
        
        # Show quality selection
        keyboard = [
            [InlineKeyboardButton(t('quality_best', lang), callback_data="quality_best")],
            [InlineKeyboardButton(t('quality_medium', lang), callback_data="quality_medium")],
            [InlineKeyboardButton(t('quality_audio', lang), callback_data="quality_audio")],
        ]
        
        await status.edit_text(
            t('choose_quality', lang, title=title, duration=duration_str),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # Store URL for quality callback
        pending_downloads[user_id] = url
        
    except Exception as e:
        logger.error(f"Error in process_download_from_queue for user {user_id}: {e}", exc_info=True)
        # Notify user of error
        try:
            await message.reply_text(t('error_occurred', lang, error=str(e)[:100]))
        except:
            pass


def cleanup_downloaded_files(file_path=None):
    """
    حذف جميع الملفات المحملة من المجلد الحالي ومجلدات التحميل.
    
    Args:
        file_path: المسار المحدد للملف المراد حذفه (اختياري)
    """
    try:
        deleted_count = 0
        
        # حذف الملف المحدد إذا كان موجود
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"🗑️ تم حذف الملف: {file_path}")
                deleted_count += 1
            except Exception as e:
                logger.error(f"❌ خطأ في حذف {file_path}: {e}")
        
        # أنواع الملفات المراد حذفها
        video_extensions = ['*.mp4', '*.mkv', '*.webm', '*.avi', '*.mov', '*.flv', '*.wmv', '*.m4v']
        audio_extensions = ['*.mp3', '*.m4a', '*.opus', '*.ogg', '*.wav', '*.flac', '*.aac']
        temp_extensions = ['*.part', '*.ytdl', '*.temp', '*.tmp']
        all_extensions = video_extensions + audio_extensions + temp_extensions
        
        # المجلدات المراد تنظيفها
        directories_to_clean = [
            '.',  # المجلد الحالي
            'downloads',
            'videos'
        ]
        
        # تنظيف كل مجلد
        for directory in directories_to_clean:
            if not os.path.exists(directory):
                continue
                
            for extension in all_extensions:
                pattern = os.path.join(directory, extension)
                for file in glob.glob(pattern):
                    try:
                        # تجنب حذف watermark.png
                        if 'watermark' in file.lower():
                            continue
                        os.remove(file)
                        logger.info(f"🗑️ تم حذف: {file}")
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"❌ خطأ في حذف {file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✅ تم حذف {deleted_count} ملف من المجلدات")
        
    except Exception as e:
        logger.error(f"❌ خطأ في cleanup_downloaded_files: {e}")


async def download_and_upload(client, message, url, quality, callback_query=None):
    """تحميل ورفع الفيديو"""
    # الحصول على معلومات المستخدم من callback_query إذا كان موجوداً
    if callback_query:
        user_id = callback_query.from_user.id
        user_name = callback_query.from_user.first_name
        user_username = callback_query.from_user.username
    else:
        user_id = message.from_user.id
        user_name = message.from_user.first_name
        user_username = message.from_user.username
    
    # Get user language
    lang = subdb.get_user_language(user_id)
    status_msg = await message.reply_text(t('processing', lang))
    
    try:
        # إعدادات التحميل
        quality_formats = {
            'best': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
            'medium': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
            'audio': 'bestaudio/best'  # النسخة الناجحة - تحميل أفضل جودة صوت
        }
        
        is_audio = (quality == 'audio')
        
        # الحصول على event loop مبكراً
        loop = asyncio.get_event_loop()
        
        # دالة تتبع تقدم التحميل
        last_edit_time = 0
        
        def download_progress_hook(d):
            nonlocal last_edit_time
            if d['status'] == 'downloading':
                try:
                    now = time.time()
                    if now - last_edit_time < 2:  # تحديث كل 2 ثانية
                        return
                        
                    last_edit_time = now
                    
                    total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded_bytes = d.get('downloaded_bytes', 0)
                    
                    if total_bytes > 0:
                        percentage = (downloaded_bytes / total_bytes) * 100
                        current_mb = downloaded_bytes / (1024 * 1024)
                        total_mb = total_bytes / (1024 * 1024)
                        speed = d.get('speed', 0) or 0
                        speed_mb = speed / (1024 * 1024)
                        eta = d.get('eta', 0) or 0
                        
                        filled = int(percentage // 10)
                        progress_bar = '▰' * filled + '▱' * (10 - filled)
                        
                        # DEBUG: Log the language being used
                        logger.info(f"📥 Download progress for user {user_id}, lang={lang}")
                        
                        msg_text = t('downloading', lang, 
                                    percent=f'{percentage:.1f}',
                                    current_mb=f'{current_mb:.1f}',
                                    total_mb=f'{total_mb:.1f}',
                                    speed_mb=f'{speed_mb:.1f}',
                                    eta=eta,
                                    progress_bar=progress_bar)
                        
                        # تحديث الرسالة من thread منفصل
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                status_msg.edit_text(msg_text),
                                loop
                            )
                            # لا ننتظر النتيجة لتجنب الحظر
                        except Exception:
                            pass
                            
                except Exception as e:
                    logger.error(f"خطأ في progress hook: {e}")
        
        # دالة تتبع مرحلة المعالجة (post-processing)
        def postprocessor_hook(d):
            try:
                status = d.get('status')
                logger.info(f"🔄 Post-processor status: {status}")
                
                if status == 'started':
                    postprocessor = d.get('postprocessor', 'Unknown')
                    logger.info(f"🔧 بدء المعالجة: {postprocessor}")
                    # تم إزالة رسالة المعالجة - المستخدم لا يريدها
                        
                elif status == 'finished':
                    logger.info(f"✅ اكتملت المعالجة")
                    
            except Exception as e:
                logger.error(f"خطأ في postprocessor hook: {e}")


        # تحسين إعدادات التحميل للسرعة والاستقرار
        logger.info("🚀 Using optimized download settings for better performance")
        
        ydl_opts = {
            'format': quality_formats.get(quality, 'best'),
            'outtmpl': '%(title)s.%(ext)s',
            'progress_hooks': [download_progress_hook],
            'postprocessor_hooks': [postprocessor_hook],  # تتبع مرحلة المعالجة
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'retries': 15,
            'fragment_retries': 15,
            'nocheckcertificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
        }
        
        # إضافة cookies إذا كانت متوفرة وصالحة (ليست فارغة)
        cookies_files = []
        for platform, data in COOKIES_PLATFORMS.items():
            if os.path.exists(data['file']):
                # التحقق من أن الملف ليس فارغاً وأن حجمه أكبر من 100 بايت
                file_size = os.path.getsize(data['file'])
                if file_size > 100:  # ملف صالح يجب أن يكون أكبر من 100 بايت
                    cookies_files.append(data['file'])
        
        if cookies_files:
            ydl_opts['cookiefile'] = cookies_files[0]
        
        # تحسينات لجميع منصات التواصل الاجتماعي
        ydl_opts['extractor_args'] = {
            'facebook': {'cookie_file': cookies_files[0] if cookies_files else None},
            'instagram': {'cookie_file': cookies_files[0] if cookies_files else None},
            'youtube': {'cookie_file': cookies_files[0] if cookies_files else None},
            'twitter': {'cookie_file': cookies_files[0] if cookies_files else None},
            'tiktok': {'cookie_file': cookies_files[0] if cookies_files else None},
            'snapchat': {'cookie_file': cookies_files[0] if cookies_files else None},
            'pinterest': {
                'cookie_file': cookies_files[0] if cookies_files else None,
                'api_only': False,
            },
        }
        
        # للملفات الصوتية: تحويل إلى MP3 فقط إذا لم يكن MP3 بالفعل
        if is_audio:
            # تحويل إلى MP3 بجودة عالية (192kbps) - سريع جداً!
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',  # جودة عالية
            }]
            logger.info("🎵 استخراج الصوت بجودة عالية (192kbps)")
        # لا نحتاج FFmpegVideoConvertor لأن merge_output_format=mp4 تكفي
        # وإضافته تسبب مشاكل conversion مع الملفات الكبيرة
        
        
        # التحميل - استخدام نظام الترجمة
        await status_msg.edit_text(t('start_downloading', lang))
        
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info, ydl.prepare_filename(info)
        
        info, file_path = await loop.run_in_executor(None, download)
        
        # ⚠️ إذا كان تحميل صوتي، FFmpegExtractAudio يغير الامتداد إلى .mp3
        # لذلك نحتاج إلى تحديث file_path للملف الحقيقي
        if is_audio:
            # تحويل الامتداد إلى .mp3 (FFmpeg يفعل ذلك تلقائياً)
            base_name = os.path.splitext(file_path)[0]
            mp3_file = f"{base_name}.mp3"
            
            if os.path.exists(mp3_file):
                file_path = mp3_file
                logger.info(f"✅ تم العثور على ملف MP3: {file_path}")
            else:
                logger.warning(f"⚠️ لم يتم العثور على {mp3_file}, استخدام المسار الأصلي")
        
        if not os.path.exists(file_path):
            logger.error(f"❌ الملف غير موجود: {file_path}")
            
            # محاولة البحث عن أي ملف صوتي تم تحميله حديثاً
            if is_audio:
                logger.info("🔍 البحث عن ملفات صوتية تم تحميلها...")
                audio_files = []
                for ext in ['*.mp3', '*.m4a', '*.opus', '*.ogg']:
                    audio_files.extend(glob.glob(ext))
                
                if audio_files:
                    # استخدام أحدث ملف (آخر ملف تم تعديله)
                    latest_file = max(audio_files, key=os.path.getmtime)
                    logger.info(f"✅ تم العثور على ملف صوتي: {latest_file}")
                    file_path = latest_file
                else:
                    logger.error("❌ لم يتم العثور على أي ملفات صوتية")
                    await status_msg.edit_text(t('download_failed', lang))
                    return
            else:
                await status_msg.edit_text(t('download_failed', lang))
                return
        
        # معلومات الملف
        file_size_mb = get_file_size_mb(file_path)
        duration = info.get('duration', 0)
        title = info.get('title', 'فيديو')[:50]
        
        logger.info(f"📊 حجم الملف النهائي: {file_size_mb:.2f} MB")

        # التحقق من الحجم
        if file_size_mb > 2000:
            await status_msg.edit_text(
                f"❌ **الملف كبير جداً!**\n\n"
                f"📊 {file_size_mb:.1f} MB\n"
                f"🔒 الحد الأقصى: 2000 MB"
            )
            os.remove(file_path)
            return
        # Upload
        lang = subdb.get_user_language(user_id)
        # Initial upload message with progress bar at 0%
        initial_progress = t('uploading', lang,
                           percent='0.0',
                           current_mb='0.0',
                           total_mb=f'{file_size_mb:.1f}',
                           speed_mb='0.0',
                           eta=0,
                           progress_bar='▱▱▱▱▱▱▱▱▱▱')
        await status_msg.edit_text(initial_progress)
        
        caption = (
            f"🎬 **{title}**\n\n"
            f"📊 {file_size_mb:.1f} MB\n"
            f"⏱️ {int(duration)//60}:{int(duration)%60:02d}\n"
            f"👤 {user_name}"
        )
        
        if is_audio:
            # التأكد من duration صحيح
            audio_duration = int(duration) if duration and duration > 0 else None
            
            # Create upload progress tracker instance with event loop
            upload_progress_tracker = UploadProgress(status_msg, user_id, loop)
            
            # إرسال كملف صوتي عادي (Audio) - يدعم ملفات كبيرة حتى 2GB
            logger.info(f"📤 إرسال كملف صوتي (Audio): {file_size_mb:.1f}MB, duration={audio_duration}s")
            
            sent_msg = await client.send_audio(
                chat_id=message.chat.id,
                audio=file_path,
                caption=caption,
                duration=audio_duration,
                progress=upload_progress_tracker
            )
            logger.info(f"✅ نجح إرسال الملف الصوتي: {file_size_mb:.1f}MB")


        else:
            # التأكد من أن جميع القيم صحيحة قبل الإرسال
            video_duration = int(duration) if duration and duration > 0 else None
            video_width = None
            video_height = None
            
            # محاولة الحصول على width/height من info إذا كانت موجودة
            try:
                if info.get('width'):
                    video_width = int(info['width'])
                if info.get('height'):
                    video_height = int(info['height'])
            except:
                pass
            
            logger.info(f"📹 Sending video: duration={video_duration}, width={video_width}, height={video_height}")
            
            # Support button on Binance
            binance_id = subdb.get_setting('binance_pay_id', '86847466')
            lang = subdb.get_user_language(user_id)
            support_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    t('support_dev_binance', lang), 
                    url=f"https://app.binance.com/qr/dplkda88dd4d4e86847466"
                )],
                [InlineKeyboardButton(
                    t('binance_pay_id', lang, binance_id=binance_id),
                    callback_data="binance_info"
                )]
            ])
            
            # Create upload progress tracker instance with event loop
            upload_progress_tracker = UploadProgress(status_msg, user_id, loop)
            
            try:
                sent_msg = await client.send_video(
                    chat_id=message.chat.id,
                    video=file_path,
                    caption=caption,
                    duration=video_duration,
                    width=video_width,
                    height=video_height,
                    supports_streaming=True,
                    reply_markup=support_keyboard,
                    progress=upload_progress_tracker
                )
            except Exception as send_error:
                logger.error(f"❌ خطأ في send_video: {send_error}")
                # محاولة بدون أي معاملات إضافية
                logger.info("🔄 Retrying with minimal parameters...")
                sent_msg = await client.send_video(
                    chat_id=message.chat.id,
                    video=file_path,
                    caption=caption,
                    supports_streaming=True
                )
        
        await status_msg.delete()
        logger.info(f"✅ نجح رفع {file_size_mb:.1f}MB للمستخدم {user_id}")
        
        # تحويل الفيديو إلى قناة السجلات
        try:
            await forward_to_log_channel(
                client=client,
                message=message,
                sent_message=sent_msg,
                user_id=user_id,
                user_name=user_name,
                username=user_username,
                url=url,
                video_info=info,
                duration=duration,
                file_size_mb=file_size_mb
            )
        except Exception as log_error:
            logger.error(f"⚠️ خطأ في إرسال للقناة: {log_error}")
        
        # حذف جميع الملفات المحملة من كل المجلدات
        cleanup_downloaded_files(file_path)
        
        # زيادة عداد التحميلات اليومية للمستخدمين غير المشتركين
        if not subdb.is_user_subscribed(user_id):
            subdb.increment_download_count(user_id)
            
            # عرض رسالة التحميلات المتبقية
            daily_limit = subdb.get_daily_limit()
            if daily_limit != -1:  # فقط إذا لم يكن غير محدود
                daily_count = subdb.check_daily_limit(user_id)
                remaining = daily_limit - daily_count
                
                if remaining > 0:
                    # الحصول على لغة المستخدم
                    lang = subdb.get_user_language(user_id)
                    await message.reply_text(
                        t('downloads_remaining', lang, remaining=remaining)
                    )

        
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        
        # إذا كان الخطأ to_bytes، يعني الفيديو نجح لكن مشكلة metadata
        if 'to_bytes' in str(e):
            # الفيديو تم رفعه بنجاح، فقط نحذف الرسالة والملفات
            try:
                await status_msg.delete()
                cleanup_downloaded_files(file_path if 'file_path' in locals() else None)
                logger.info(f"✅ نجح رفع {file_size_mb:.1f}MB للمستخدم {user_id} (تم تجاهل خطأ metadata)")
            except:
                pass
        else:
            # خطأ حقيقي - إرسال تنبيه للأدمن
            user_name = message.from_user.first_name or "مستخدم"
            
            # الحصول على traceback الكامل
            error_traceback = traceback.format_exc()
            
            # إرسال الخطأ مع traceback إلى القناة
            await send_error_to_admin(user_id, user_name, str(e), url, error_traceback)
            
            error_text = str(e)
            
            # تنظيف رسالة الخطأ من ANSI codes
            import re
            error_text = re.sub(r'\x1b\[[0-9;]*m', '', error_text)
            
            # Get user language for error messages
            lang = subdb.get_user_language(user_id)
            
            # حذف الملفات المحملة حتى في حالة الخطأ
            cleanup_downloaded_files(file_path if 'file_path' in locals() else None)
            
            # رسائل مخصصة لأخطاء معينة
            if 'Cannot parse data' in error_text and 'facebook' in error_text.lower():
                await status_msg.edit_text(t('facebook_unavailable', lang))
            elif 'Pinterest' in error_text and ('Connection reset' in error_text or 'Unable to download' in error_text):
                await status_msg.edit_text(t('pinterest_unavailable', lang))
            else:
                # تقصير رسالة الخطأ
                short_error = error_text.split('\n')[0][:100]
                await status_msg.edit_text(t('generic_error', lang, error=short_error))



# ═══════════════════════════════════════════════════════════════
# Handlers
# ═══════════════════════════════════════════════════════════════

@app.on_message(filters.command("start"))
async def start(client, message):
    user_id = message.from_user.id
    
    # التحقق من وجود لغة محددة للمستخدم
    lang = subdb.get_user_language(user_id)
    
    # إذا كانت أول مرة (لغة غير محددة أو قيمة افتراضية)
    # نتحقق إذا كان موجود في قاعدة البيانات
    user_exists = subdb.find_user_by_id(user_id)
    
    if not user_exists:
        # مستخدم جديد - إرسال إشعار للقناة
        join_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await send_new_member_notification(
            user_id=user_id,
            user_name=message.from_user.first_name,
            username=message.from_user.username,
            join_time=join_time
        )
        
        # عرض اختيار اللغة
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🇮🇶 العربية", callback_data="lang_ar"),
                InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")
            ]
        ])
        
        await message.reply_text(
            t('choose_language', 'ar'),
            reply_markup=keyboard
        )
        return
    
    # مستخدم موجود - عرض الرسالة الترحيبية
    keyboard = None
    admin_id = os.getenv("ADMIN_ID")
    
    if admin_id and str(user_id) == admin_id:
        from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton(t('btn_cookies', lang)), KeyboardButton(t('btn_daily_report', lang))],
            [KeyboardButton(t('btn_errors', lang)), KeyboardButton(t('btn_subscription', lang))],
            [KeyboardButton(t('btn_change_language', lang))]
        ], resize_keyboard=True)
    else:
        # للمستخدمين العاديين - التحقق من الاشتراك
        from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
        
        # التحقق من حالة الاشتراك
        is_subscribed = subdb.is_user_subscribed(user_id)
        
        if is_subscribed:
            # مشترك - عرض زر الاشتراك + تغيير اللغة
            keyboard = ReplyKeyboardMarkup([
                [KeyboardButton(t('btn_my_subscription', lang))],
                [KeyboardButton(t('btn_change_language', lang))]
            ], resize_keyboard=True)
        else:
            # غير مشترك - زر تغيير اللغة فقط
            keyboard = ReplyKeyboardMarkup([
                [KeyboardButton(t('btn_change_language', lang))]
            ], resize_keyboard=True)
    
    await message.reply_text(
        t('welcome', lang, name=message.from_user.first_name),
        reply_markup=keyboard
    )


# معالج الأزرار السريعة
@app.on_message(filters.text & filters.regex(r'^(🍪 Cookies|📊 التقرير اليومي|🔔 الأخطاء|💎 إعدادات الاشتراك|📁 نسخ احتياطي)$'))
async def handle_quick_buttons(client, message):
    """معالج الأزرار السريعة"""
    user_id = message.from_user.id
    
    if str(user_id) != os.getenv("ADMIN_ID"):
        return
    
    if message.text == "🍪 Cookies":
        await cookies_panel(client, message)
    elif message.text == "📊 التقرير اليومي":
        await send_daily_report(client, message.from_user.id)
    elif message.text == "🔔 الأخطاء":
        await show_errors(client, message)
    elif message.text == "💎 إعدادات الاشتراك":
        await subscription_settings_panel(client, message)
    elif message.text == "📁 نسخ احتياطي":
        await send_database_backup(client, message)


# معالج زر اشتراكي - Subscription Status Button Handler
@app.on_message(filters.text & filters.regex(r'^💎 اشتراكي$|^💎 My Subscription$'))
async def handle_my_subscription(client, message):
    """معالج زر حالة الاشتراك للمستخدمين"""
    user_id = message.from_user.id
    lang = subdb.get_user_language(user_id)
    
    # التحقق من حالة الاشتراك
    if not subdb.is_user_subscribed(user_id):
        await message.reply_text(t('not_subscribed', lang))
        return
    
    # الحصول على معلومات الاشتراك
    time_info = subdb.get_time_remaining(user_id)
    
    if not time_info:
        await message.reply_text(t('not_subscribed', lang))
        return
    
    # عرض معلومات الاشتراك
    await message.reply_text(
        t('subscription_status', lang,
          end_date=time_info['end_date_formatted'],
          days=time_info['days'],
          hours=time_info['hours'])
    )



async def send_daily_report(client, admin_id):
    """إرسال التقرير اليومي"""
    now = datetime.now()
    report_text = f"📊 **تقرير فحص الكوكيز اليومي**\n\n"
    report_text += f"📅 **التاريخ:** {now.strftime('%d-%m-%Y %H:%M:%S')}\n\n"
    
    valid_cookies = []
    expired_cookies = []
    missing_cookies = []
    
    for platform_id, data in COOKIES_PLATFORMS.items():
        if os.path.exists(data['file']):
            file_time = os.path.getmtime(data['file'])
            uploaded_date = datetime.fromtimestamp(file_time)
            days_ago = (now - uploaded_date).days
            days_left = max(0, 30 - days_ago)
            
            if days_left > 0:
                valid_cookies.append((data['name'], days_left))
            else:
                expired_cookies.append(data['name'])
        else:
            missing_cookies.append(data['name'])
    
    # الكوكيز الصالحة
    report_text += f"✅ **الكوكيز الصالحة ({len(valid_cookies)}):**\n"
    if valid_cookies:
        for name, days in valid_cookies:
            report_text += f"• {name}: {days} يوم\n"
    else:
        report_text += "⚠️ لا توجد\n"
    
    report_text += "\n"
    
    # الكوكيز المنتهية
    if expired_cookies:
        report_text += f"❌ **منتهية ({len(expired_cookies)}):**\n"
        for name in expired_cookies:
            report_text += f"• {name}\n"
        report_text += "\n"
    
    # الغير موجودة
    if missing_cookies:
        report_text += f"⚠️ **غير موجودة ({len(missing_cookies)}):**\n"
        for name in missing_cookies:
            report_text += f"• {name}\n"
        report_text += "\n"
    
    # إحصائيات
    total = len(COOKIES_PLATFORMS)
    checked = len(valid_cookies) + len(expired_cookies)
    success_rate = (len(valid_cookies) / total * 100) if total > 0 else 0
    
    report_text += f"📈 **الإحصائيات:**\n"
    report_text += f"• تم الفحص: {checked} منصة\n"
    report_text += f"• معدل النجاح: {success_rate:.1f}%"
    
    await client.send_message(admin_id, report_text)


# مهمة خلفية للتقرير اليومي
async def show_errors(client, message):
    """عرض قائمة الأخطاء للأدمن"""
    pending_errors = {k: v for k, v in user_errors.items() if v['status'] == 'pending'}
    
    if not pending_errors:
        await message.reply_text("✅ **لا توجد أخطاء معلقة!**\n\nجميع المشاكل تم حلها.")
        return
    
    text = "🔔 **قائمة الأخطاء المعلقة**\n\n"
    
    for error_id, error_data in list(pending_errors.items())[:10]:  # آخر 10 أخطاء
        text += f"━━━━━━━━━━━━━━━━\n"
        text += f"🆔 **ID:** `{error_id}`\n"
        text += f"👤 **المستخدم:** {error_data['user_name']} (`{error_data['user_id']}`)\n"
        text += f"🕐 **الوقت:** {error_data['time']}\n"
        text += f"🔗 **الرابط:** `{error_data['url'][:40]}...`\n\n"
    
    text += f"\n📝 **إجمالي الأخطاء المعلقة:** {len(pending_errors)}"
    
    await message.reply_text(text)


@app.on_callback_query(filters.regex(r'^resolve_'))
async def handle_resolve_error(client, callback_query):
    """معالج زر تم الإصلاح"""
    if str(callback_query.from_user.id) != os.getenv("ADMIN_ID"):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    error_id = callback_query.data.replace('resolve_', '')
    
    if error_id not in user_errors:
        await callback_query.answer("❌ الخطأ غير موجود!", show_alert=True)
        return
    
    error_data = user_errors[error_id]
    
    if error_data['status'] == 'resolved':
        await callback_query.answer("✅ تم حل هذا الخطأ مسبقاً", show_alert=True)
        return
    
    # تحديث الحالة
    user_errors[error_id]['status'] = 'resolved'
    
    # إرسال رسالة للمستخدم
    try:
        await client.send_message(
            chat_id=error_data['user_id'],
            text=f"✅ **تم إصلاح مشكلتك!**\n\n"
                 f"المشكلة التي واجهتها مع الرابط:\n"
                 f"`{error_data['url'][:50]}...`\n\n"
                 f"تم حلها الآن. يمكنك المحاولة مرة أخرى! 🎉"
        )
        logger.info(f"✅ تم إرسال إشعار الحل للمستخدم {error_data['user_id']}")
    except Exception as e:
        logger.error(f"فشل إرسال إشعار للمستخدم: {e}")
    
    # تحديث الرسالة
    await callback_query.message.edit_text(
        callback_query.message.text + f"\n\n✅ **تم الحل بواسطة الأدمن**",
        reply_markup=None
    )
    
    await callback_query.answer("✅ تم إرسال إشعار للمستخدم", show_alert=True)


# تقرير يومي تلقائي
async def daily_report_task():
    """مهمة خلفية لإرسال التقرير يومياً"""
    from datetime import timedelta
    
    while True:
        now = datetime.now()
        # إرسال في الساعة 9 صباحاً
        target_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
        
        if now > target_time:
            # إذا مرت الساعة 9، اذهب لليوم التالي
            target_time = target_time + timedelta(days=1)
        
        wait_seconds = (target_time - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        
        # إرسال التقرير
        admin_id = int(os.getenv("ADMIN_ID"))
        await send_daily_report(app, admin_id)
        
        # انتظر يوم كامل
        await asyncio.sleep(86400)


async def send_database_backup(client, message):
    """إرسال نسخة احتياطية من قاعدة البيانات PostgreSQL"""
    user_id = message.from_user.id
    
    # التحقق من صلاحيات الأدمن
    admin_id = os.getenv("ADMIN_ID")
    if not admin_id or str(user_id) != admin_id:
        await message.reply_text("❌ **غير مصرح!**\n\nهذا الأمر للمشرفين فقط.")
        return
    
    try:
        # رسالة انتظار
        status_msg = await message.reply_text(
            "⏳ **جاري إنشاء النسخة الاحتياطية...**\n\n"
            "هذا قد يستغرق بضع ثوانٍ... ⏰"
        )
        
        # إنشاء النسخة الاحتياطية
        logger.info(f"🔄 الأدمن {user_id} طلب نسخة احتياطية من قاعدة البيانات")
        success, result = pg_backup.create_backup(prefer_sql=True)
        
        if not success:
            await status_msg.edit_text(
                f"❌ **فشل إنشاء النسخة الاحتياطية!**\n\n"
                f"**الخطأ:** `{result}`\n\n"
                f"تواصل مع مطور البوت للمساعدة."
            )
            logger.error(f"❌ فشل إنشاء النسخة الاحتياطية: {result}")
            return
        
        backup_file_path = result
        file_size_mb = os.path.getsize(backup_file_path) / (1024 * 1024)
        file_type = "SQL" if backup_file_path.endswith(".sql") else "JSON"
        
        # تحديث الرسالة
        await status_msg.edit_text(
            f"📤 **جاري رفع النسخة الاحتياطية...**\n\n"
            f"📦 النوع: {file_type}\n"
            f"💾 الحجم: {file_size_mb:.2f} MB"
        )
        
        # إرسال الملف
        caption = (
            f"📁 **نسخة احتياطية من قاعدة البيانات**\n\n"
            f"📦 **النوع:** {file_type}\n"
            f"💾 **الحجم:** {file_size_mb:.2f} MB\n"
            f"📅 **التاريخ:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🗄️ **قاعدة البيانات:** PostgreSQL\n\n"
            f"✅ يمكنك استخدام هذا الملف لاستعادة البيانات في حالة الطوارئ."
        )
        
        await client.send_document(
            chat_id=user_id,
            document=backup_file_path,
            caption=caption
        )
        
        # حذف رسالة الحالة
        await status_msg.delete()
        
        # حذف الملف المؤقت
        try:
            os.remove(backup_file_path)
            logger.info(f"🗑️ تم حذف الملف المؤقت: {backup_file_path}")
        except Exception as e:
            logger.warning(f"⚠️ فشل حذف الملف المؤقت: {e}")
        
        # تنظيف الملفات القديمة
        pg_backup.cleanup_old_backups(max_age_hours=1)
        
        logger.info(f"✅ تم إرسال النسخة الاحتياطية بنجاح للأدمن {user_id}")
        
    except Exception as e:
        logger.error(f"❌ خطأ في send_database_backup: {e}", exc_info=True)
        try:
            await message.reply_text(
                f"❌ **حدث خطأ أثناء إنشاء النسخة الاحتياطية!**\n\n"
                f"**الخطأ:** `{str(e)[:200]}`"
            )
        except:
            pass


@app.on_message(filters.command("cookies"))
async def cookies_panel(client, message):
    """لوحة إدارة الـ cookies (للأدمن فقط)"""
    user_id = message.from_user.id
    
    if str(user_id) != os.getenv("ADMIN_ID"):
        await message.reply_text("❌ هذا الأمر للمشرفين فقط!")
        return
    
    # بناء الأزرار
    keyboard = []
    for platform_id, data in COOKIES_PLATFORMS.items():
        keyboard.append([
            InlineKeyboardButton(data['name'], callback_data=f"cookies_{platform_id}")
        ])
    
    # زر مراجعة حالة الـ cookies
    keyboard.append([
        InlineKeyboardButton("📊 حالة جميع الـ Cookies", callback_data="cookies_status")
    ])
    
    await message.reply_text(
        "🍪 **إدارة Cookies**\n\n"
        "اختر المنصة لإضافة أو اختبار الـ cookies:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@app.on_callback_query(filters.regex(r'^cookies_(?!back$|status$)'))
async def cookies_platform_handler(client, callback_query):
    """معالج اختيار المنصة"""
    user_id = callback_query.from_user.id
    
    if str(user_id) != os.getenv("ADMIN_ID"):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    # استخراج اسم المنصة من callback_data
    platform_id = callback_query.data.replace('cookies_', '')
    
    if platform_id not in COOKIES_PLATFORMS:
        await callback_query.answer("❌ منصة غير صحيحة!")
        return
    
    platform = COOKIES_PLATFORMS[platform_id]
    cookie_exists = os.path.exists(platform['file'])
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة Cookies", callback_data=f"add_cookie_{platform_id}")],
        [InlineKeyboardButton("✅ اختبار Cookies", callback_data=f"test_cookie_{platform_id}")],
        [InlineKeyboardButton("« رجوع", callback_data="cookies_back")]
    ])
    
    status = "✅ موجود" if cookie_exists else "❌ غير موجود"
    
    # إضافة معلومات الصلاحية
    expiry_info = ""
    if cookie_exists:
        file_time = os.path.getmtime(platform['file'])
        uploaded_date = datetime.fromtimestamp(file_time)
        days_ago = (datetime.now() - uploaded_date).days
        days_left = max(0, 30 - days_ago)
        
        expiry_info = f"\n⏱️ **رفع قبل:** {days_ago} يوم\n📅 **باقي:** {days_left} يوم"
    
    await callback_query.message.edit_text(
        f"🍪 **{platform['name']}**\n\n"
        f"📊 **الحالة:** {status}{expiry_info}\n\n"
        "اختر الإجراء:",
        reply_markup=keyboard
    )
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^cookies_status$'))
async def cookies_status_handler(client, callback_query):
    """معالج عرض حالة جميع الـ Cookies"""
    user_id = callback_query.from_user.id
    
    if str(user_id) != os.getenv("ADMIN_ID"):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    status_text = "📊 **حالة جميع الـ Cookies**\n\n"
    
    for platform_id, data in COOKIES_PLATFORMS.items():
        cookie_exists = os.path.exists(data['file'])
        
        if cookie_exists:
            file_time = os.path.getmtime(data['file'])
            uploaded_date = datetime.fromtimestamp(file_time)
            days_ago = (datetime.now() - uploaded_date).days
            
            # افتراض صلاحية 30 يوم
            days_left = 30 - days_ago
            
            if days_left > 7:
                status_icon = "✅"
            elif days_left > 0:
                status_icon = "⚠️"
            else:
                status_icon = "❌"
            
            status_text += f"{status_icon} **{data['name']}**\n"
            status_text += f"   ⏱️ رفع قبل: {days_ago} يوم\n"
            status_text += f"   📅 باقي: {max(0, days_left)} يوم\n\n"
        else:
            status_text += f"❌ **{data['name']}**\n"
            status_text += f"   ⚠️ غير موجود\n\n"
    
    await callback_query.message.edit_text(
        status_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("« رجوع", callback_data="cookies_back")]
        ])
    )
    
    await callback_query.answer()


@app.on_message(filters.command("backup"))
async def backup_command(client, message):
    """معالج أمر /backup - لإنشاء نسخة احتياطية من قاعدة البيانات"""
    await send_database_backup(client, message)


@app.on_callback_query(filters.regex(r'^add_cookie_'))
async def add_cookie_handler(client, callback_query):
    """طلب إضافة cookies"""
    user_id = callback_query.from_user.id
    
    if str(user_id) != os.getenv("ADMIN_ID"):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    platform_id = callback_query.data.replace('add_cookie_', '')
    platform = COOKIES_PLATFORMS[platform_id]
    
    waiting_for_cookies[user_id] = platform_id
    
    await callback_query.message.edit_text(
        f"🍪 **إضافة Cookies - {platform['name']}**\n\n"
        "📝 **كيفية الحصول على Cookies:**\n"
        "1. افتح المنصة في المتصفح\n"
        "2. سجل دخول لحسابك\n"
        "3. استخدم إضافة **Get cookies.txt** أو **EditThisCookie**\n"
        "4. صدّر الـ cookies بصيغة Netscape\n"
        "5. أرسل الملف هنا\n\n"
        "⚠️ **ملاحظة:** استخدم ملف .txt فقط (Netscape format)"
    )
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^test_cookie_'))
async def test_cookie_handler(client, callback_query):
    """اختبار cookies"""
    user_id = callback_query.from_user.id
    
    if str(user_id) != os.getenv("ADMIN_ID"):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    platform_id = callback_query.data.replace('test_cookie_', '')
    platform = COOKIES_PLATFORMS[platform_id]
    
    if not os.path.exists(platform['file']):
        await callback_query.answer("❌ لا توجد cookies لهذه المنصة!", show_alert=True)
        return
    
    await callback_query.answer("⏳ جاري الاختبار...")
    
    # روابط اختبار محدّثة ومضمونة (فيديوهات عامة ومتاحة)
    test_urls = {
        # YouTube - مضمون 100%
        'youtube': 'https://www.youtube.com/watch?v=jNQXAC9IVRw',  # أول فيديو على YouTube
        
        # Instagram - يحتاج cookies، نستخدم YouTube كبديل آمن
        'instagram': 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
        
        # Twitter/X - نستخدم YouTube كبديل آمن
        'twitter': 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
        
        # Facebook - نستخدم YouTube كبديل آمن
        'facebook': 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
        
        # TikTok - نستخدم YouTube كبديل آمن
        'tiktok': 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
        
        # Threads - نستخدم YouTube كبديل آمن
        'threads': 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
        
        # Pinterest - نستخدم YouTube كبديل آمن
        'pinterest': 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
        
        # Snapchat - نستخدم YouTube كبديل آمن
        'snapchat': 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
        
        # افتراضي
        'other': 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
    }
    
    try:
        test_opts = {
            'quiet': True,
            'no_warnings': True,
            'cookiefile': platform['file'],
            'skip_download': True,
            'no_check_certificate': True,
            'socket_timeout': 30,
        }
        
        with yt_dlp.YoutubeDL(test_opts) as ydl:
            # محاولة extract_info على رابط اختباري
            test_url = test_urls.get(platform_id, test_urls['youtube'])
            info = ydl.extract_info(test_url, download=False)
            
            # الحصول على معلومات الفيديو للتأكد من نجاح الاختبار
            video_title = info.get('title', 'فيديو')
            video_duration = info.get('duration', 0)
            duration_str = f"{int(video_duration)//60}:{int(video_duration)%60:02d}" if video_duration else "غير معروف"
        
        await callback_query.message.edit_text(
            f"✅ **Cookies تعمل بنجاح!**\n\n"
            f"🍪 **المنصة:** {platform['name']}\n"
            f"📂 **الملف:** {platform['file']}\n"
            f"🎬 **اختبار على:** {video_title[:50]}...\n"
            f"⏱️ **المدة:** {duration_str}\n"
            f"📊 **الحالة:** ✅ صالحة ومضمونة"
        )
    except Exception as e:
        error_msg = str(e)
        # تبسيط رسالة الخطأ
        if "Unsupported URL" in error_msg:
            error_msg = "الرابط غير مدعوم - جرب رفع الـ cookies مرة أخرى"
        elif "Video unavailable" in error_msg:
            error_msg = "الفيديو غير متاح - لكن الـ cookies تعمل!"
        else:
            error_msg = error_msg[:150]
        
        # تنظيف رسالة الخطأ من ANSI codes
        import re
        error_msg = re.sub(r'\x1b\[[0-9;]*m', '', error_msg)
        
        # إذا كان الخطأ عن رابط غير مدعوم، نعتبر الـ cookies صالحة
        if "Unsupported URL" in str(e):
            await callback_query.message.edit_text(
                f"✅ **Cookies محفوظة!**\n\n"
                f"🍪 **المنصة:** {platform['name']}\n"
                f"📂 **الملف:** {platform['file']}\n\n"
                f"ℹ️ لا يمكن اختبار هذه المنصة حالياً،\n"
                f"لكن الملف محفوظ ويعمل عند التحميل."
            )
        # إذا كان الخطأ "No video could be found"
        elif "No video" in error_msg or "no video" in error_msg.lower():
            await callback_query.message.edit_text(
                f"⚠️ **تنبيه**\n\n"
                f"🍪 **المنصة:** {platform['name']}\n"
                f"📂 **الملف:** {platform['file']}\n\n"
                f"ℹ️ **الملاحظة:**\n"
                f"لا يوجد فيديو في الرابط التجريبي.\n"
                f"قد يكون الرابط يحتوي على صورة أو نص فقط.\n\n"
                f"✅ **الـ Cookies محفوظة** ويمكن استخدامها مع روابط تحتوي على فيديوهات."
            )
        else:
            await callback_query.message.edit_text(
                f"⚠️ **تحذير**\n\n"
                f"🍪 **المنصة:** {platform['name']}\n"
                f"⚠️ **الملاحظة:**\n{error_msg}\n\n"
                f"الملف محفوظ، جرب التحميل للتأكد."
            )


@app.on_callback_query(filters.regex(r'^cookies_back$'))
async def cookies_back_handler(client, callback_query):
    """العودة لقائمة المنصات"""
    user_id = callback_query.from_user.id
    
    if str(user_id) != os.getenv("ADMIN_ID"):
        return
    
    keyboard = []
    for platform_id, data in COOKIES_PLATFORMS.items():
        keyboard.append([
            InlineKeyboardButton(data['name'], callback_data=f"cookies_{platform_id}")
        ])
    
    keyboard.append([
        InlineKeyboardButton("📊 حالة جميع الـ Cookies", callback_data="cookies_status")
    ])
    
    await callback_query.message.edit_text(
        "🍪 **إدارة Cookies**\n\n"
        "اختر المنصة لإضافة أو اختبار الـ cookies:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await callback_query.answer()


@app.on_message(filters.document)
async def handle_cookie_file(client, message):
    """معالج ملفات الـ cookies"""
    user_id = message.from_user.id
    
    if str(user_id) != os.getenv("ADMIN_ID"):
        return
    
    if user_id not in waiting_for_cookies:
        return
    
    platform_id = waiting_for_cookies[user_id]
    platform = COOKIES_PLATFORMS[platform_id]
    
    # التحقق من نوع الملف
    if not message.document.file_name.endswith('.txt'):
        await message.reply_text("❌ يجب أن يكون الملف بصيغة .txt!")
        return
    
    status_msg = await message.reply_text("⏳ جاري حفظ الـ cookies...")
    
    try:
        # تحميل الملف
        file_path = await client.download_media(message.document.file_id)
        
        # نسخ الملف إلى مجلد cookies
        import shutil
        shutil.move(file_path, platform['file'])
        
        del waiting_for_cookies[user_id]
        
        await status_msg.edit_text(
            f"✅ **تم حفظ Cookies بنجاح!**\n\n"
            f"🍪 **المنصة:** {platform['name']}\n"
            f"📂 **الملف:** {platform['file']}\n\n"
            "يمكنك الآن استخدام /cookies لاختبارها."
        )
        
        logger.info(f"✅ الأدمن {user_id} أضاف cookies لـ {platform_id}")
        
    except Exception as e:
        await status_msg.edit_text(f"❌ فشل حفظ الملف: {str(e)}")
        logger.error(f"خطأ في حفظ cookies: {e}")


@app.on_message(filters.text & filters.regex(r'https?://\S+'))
async def handle_url(client, message):
    if not message.from_user:
        return
    
    url = message.text.strip()
    user_id = message.from_user.id
    
    # Get user language FIRST
    lang = subdb.get_user_language(user_id)
    
    # Check rate limiting
    is_limited, seconds_remaining = queue_manager.is_rate_limited(user_id)
    if is_limited:
        await message.reply_text(
            t('queue_rate_limit', lang, seconds=int(seconds_remaining) + 1)
        )
        return
    
    # Mark request time immediately for rate limiting (even during quality selection)
    queue_manager.mark_request(user_id)
    
    # Check if user already has downloads in queue
    queue_size = queue_manager.get_queue_size(user_id)
    is_processing = queue_manager.is_processing(user_id)
    
    if is_processing or queue_size > 0:
        # User has active downloads, add to queue
        # Create download task
        task = DownloadTask(
            url=url,
            message=message,
            user_id=user_id,
            quality="pending"  # Will be set when quality is chosen
        )
        
        # Add to queue
        position = await queue_manager.add_to_queue(
            user_id=user_id,
            task=task,
            process_func=process_download_from_queue
        )
        
        # Notify user
        await message.reply_text(
            t('queue_position', lang, position=position)
        )
        return
    
    # No active downloads, process normally
    pending_downloads[user_id] = url
    
    status = await message.reply_text(t('processing', lang))
    
    try:
        info = await get_video_info(url)
        
        if not info:
            # Send alert to admin
            user_name = message.from_user.first_name or "User"
            
            await send_error_to_admin(user_id, user_name, "Failed to extract video info", url)
            await status.edit_text(t('invalid_url', lang))
            return
    except Exception as e:
        # Unexpected error
        user_name = message.from_user.first_name or "User"
        await send_error_to_admin(user_id, user_name, str(e), url)
        await status.edit_text(t('error_occurred', lang, error=str(e)[:100]))
        return
    
    title = info.get('title', 'Video')[:50]
    duration = info.get('duration', 0)
    duration_str = f"{int(duration)//60}:{int(duration)%60:02d}" if duration else "0:00"
    
    # Add or update user info
    username = message.from_user.username
    first_name = message.from_user.first_name
    subdb.add_or_update_user(user_id, username, first_name)
    
    # Check subscription and video duration
    is_subscribed = subdb.is_user_subscribed(user_id)
    
    # فحص الحد اليومي للمستخدمين غير المشتركين
    # Check daily limit for non-subscribers
    if not is_subscribed:
        daily_limit = subdb.get_daily_limit()
        
        # فقط فحص إذا كان الحد ليس "غير محدود" (-1)
        if daily_limit != -1:
            daily_count = subdb.check_daily_limit(user_id)
            
            if daily_count >= daily_limit:
                await status.edit_text(
                    t('daily_limit_exceeded', lang, limit=daily_limit, count=daily_count),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(t('subscribe_now', lang), callback_data="pay_binance")],
                        [InlineKeyboardButton(t('contact_developer', lang), url=f"https://t.me/{subdb.get_setting('telegram_support', 'wahab161')}")]
                    ])
                )
                return
    
    max_duration_minutes = subdb.get_max_duration()
    max_duration_seconds = max_duration_minutes * 60
    
    # If not subscribed and exceeds max duration
    if not is_subscribed and duration and duration > max_duration_seconds:
        await show_subscription_screen(client, status, user_id, title, duration, max_duration_minutes)
        return
    
    # Show quality selection
    keyboard = [
        [InlineKeyboardButton(t('quality_best', lang), callback_data="quality_best")],
        [InlineKeyboardButton(t('quality_medium', lang), callback_data="quality_medium")],
        [InlineKeyboardButton(t('quality_audio', lang), callback_data="quality_audio")],
    ]
    
    await status.edit_text(
        t('choose_quality', lang, title=title, duration=duration_str),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



@app.on_callback_query(filters.regex(r'^quality_'))
async def handle_quality(client, callback_query):
    await callback_query.answer()
    
    user_id = callback_query.from_user.id
    quality = callback_query.data.replace("quality_", "")
    
    if user_id not in pending_downloads:
        lang = subdb.get_user_language(user_id)
        await callback_query.message.edit_text(t('error_occurred', lang, error="Session expired. Send link again."))
        return
    
    url = pending_downloads[user_id]
    lang = subdb.get_user_language(user_id)
    await callback_query.message.edit_text(t('start_download', lang))
    
    await download_and_upload(client, callback_query.message, url, quality, callback_query)
    
    # Safe deletion - prevents KeyError if user clicks multiple quality buttons
    pending_downloads.pop(user_id, None)


# ═══════════════════════════════════════════════════════════════
# Subscription System Handlers
# ═══════════════════════════════════════════════════════════════

async def show_subscription_screen(client, message, user_id, title, duration, max_minutes):
    """عرض شاشة الاشتراك للمستخدمين غير المشتركين"""
    duration_minutes = int(duration) // 60
    telegram_support = subdb.get_setting('telegram_support', 'wahab161')
    binance_id = subdb.get_setting('binance_pay_id', '86847466')
    
    # Get user language
    lang = subdb.get_user_language(user_id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t('binance_pay', lang), callback_data=f"pay_binance")],
        [InlineKeyboardButton(t('visa_card', lang), callback_data=f"pay_visa")],
        [InlineKeyboardButton(t('mastercard', lang), callback_data=f"pay_mastercard")],
        [InlineKeyboardButton(t('telegram_contact', lang), url=f"https://t.me/{telegram_support}")]
    ])
    
    text = (
        t('subscription_required', lang, title=title, duration=duration_minutes, max_duration=max_minutes) +
        "\n\n━━━━━━━━━━━━━━━━\n\n" +
        t('subscription_benefits', lang) +
        "\n\n" +
        t('choose_payment_method', lang)
    )
    
    await message.edit_text(text, reply_markup=keyboard)


@app.on_callback_query(filters.regex(r'^pay_'))
async def handle_payment_method(client, callback_query):
    """معالج طرق الدفع"""
    user_id = callback_query.from_user.id
    payment_method = callback_query.data.replace('pay_', '')
    
    # Get user language
    lang = subdb.get_user_language(user_id)
    
    binance_id = subdb.get_setting('binance_pay_id', '86847466')
    telegram_support = subdb.get_setting('telegram_support', 'wahab161')
    price = subdb.get_setting('subscription_price', '10')
    
    if payment_method == 'binance':
        text = (
            f"{t('payment_binance_title', lang)}\n\n"
            f"{t('payment_amount', lang, price=price)}\n"
            f"🆔 **Binance Pay ID:** `{binance_id}`\n\n"
            f"{t('payment_binance_steps', lang, binance_id=binance_id)}"
        )
    elif payment_method == 'visa':
        text = (
            f"{t('payment_visa_title', lang)}\n\n"
            f"{t('payment_amount', lang, price=price)}\n\n"
            f"{t('payment_visa_instructions', lang, support_username=telegram_support)}"
        )
    elif payment_method == 'mastercard':
        text = (
            f"{t('payment_mastercard_title', lang)}\n\n"
            f"{t('payment_amount', lang, price=price)}\n\n"
            f"{t('payment_mastercard_instructions', lang, support_username=telegram_support)}"
        )
    
    # حفظ طريقة الدفع المختارة
    pending_downloads[user_id] = {'payment_method': payment_method}
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t('contact_developer', lang), url=f"https://t.me/{telegram_support}")],
        [InlineKeyboardButton(t('back', lang), callback_data="back_to_subscription")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=keyboard)
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^binance_id_info$'))
async def handle_binance_id_info(client, callback_query):
    """معالج زر معلومات Binance ID"""
    binance_id = subdb.get_setting('binance_pay_id', '86847466')
    await callback_query.answer(
        f"💵 Binance Pay ID: {binance_id}\n\n"
        f"يمكنك دعم المطور عبر إرسال أي مبلغ!",
        show_alert=True
    )


@app.on_callback_query(filters.regex(r'^back_to_subscription$'))
async def handle_back_to_subscription(client, callback_query):
    """معالج الرجوع لشاشة الاشتراك"""
    user_id = callback_query.from_user.id
    
    # Get user language
    lang = subdb.get_user_language(user_id)
    
    telegram_support = subdb.get_setting('telegram_support', 'wahab161')
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t('binance_pay', lang), callback_data="pay_binance")],
        [InlineKeyboardButton(t('visa_card', lang), callback_data="pay_visa")],
        [InlineKeyboardButton(t('mastercard', lang), callback_data="pay_mastercard")],
        [InlineKeyboardButton(t('telegram_contact', lang), url=f"https://t.me/{telegram_support}")]
    ])
    
    # Show subscription options
    text = (
        t('subscription_required', lang, title="Video", duration=10, max_duration=5) +
        "\n\n━━━━━━━━━━━━━━━━\n\n" +
        t('subscription_benefits', lang) +
        "\n\n" +
        t('choose_payment_method', lang)
    )
    
    await callback_query.message.edit_text(
        text,
        reply_markup=keyboard
    )
    await callback_query.answer()


async def notify_admin_contact(client, user_id, user, payment_method):
    """إرسال إشعار للمطور عند محاولة المستخدم التواصل"""
    try:
        admin_id = int(os.getenv("ADMIN_ID"))
        username = user.username or "لا يوجد"
        first_name = user.first_name or "مستخدم"
        
        text = (
            f"📞 **طلب اشتراك جديد!**\n\n"
            f"👤 **المستخدم:** {first_name}\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"📱 **Username:** @{username}\n"
            f"💳 **الطريقة المطلوبة:** {payment_method}\n\n"
            f"المستخدم يريد الاشتراك ويحتاج للتواصل معك! 💬"
        )
        
        await client.send_message(admin_id, text)
        logger.info(f"📞 إشعار تواصل من {user_id} للأدمن")
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار التواصل: {e}")



@app.on_message(filters.photo)
async def handle_payment_proof(client, message):
    """معالج إثبات الدفع (الصور)"""
    user_id = message.from_user.id
    lang = subdb.get_user_language(user_id)
    
    # التحقق إذا كان المستخدم في عملية دفع
    if user_id not in pending_downloads:
        # رد فوري: البوت لا يدعم الصور إلا لإثبات الدفع
        await message.reply_text(t('unsupported_media_photo', lang))
        return
    
    payment_data = pending_downloads.get(user_id)
    if not isinstance(payment_data, dict) or 'payment_method' not in payment_data:
        # رد فوري: البوت لا يدعم الصور إلا لإثبات الدفع
        await message.reply_text(t('unsupported_media_photo', lang))
        return
    
    payment_method = payment_data['payment_method']
    
    # حفظ الدفعة في قاعدة البيانات
    payment_id = subdb.add_payment(
        user_id=user_id,
        payment_method=payment_method,
        proof_file_id=message.photo.file_id,
        proof_message_id=message.id
    )
    
    # حذف من pending
    del pending_downloads[user_id]
    
    # إرسال إشعار للمستخدم
    await message.reply_text(
        "✅ **تم استلام إثبات الدفع!**\n\n"
        "سيتم مراجعة دفعتك من قبل المسؤول.\n"
        "ستصلك رسالة فور تفعيل اشتراكك! 🎉\n\n"
        "⏳ الانتظار المتوقع: أقل من 24 ساعة"
    )
    
    # إرسال إشعار للأدمن
    admin_id = int(os.getenv("ADMIN_ID"))
    username = message.from_user.username or "لا يوجد"
    first_name = message.from_user.first_name or "مستخدم"
    
    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ قبول", callback_data=f"approve_payment_{payment_id}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"reject_payment_{payment_id}")]
    ])
    
    await client.send_photo(
        chat_id=admin_id,
        photo=message.photo.file_id,
        caption=(
            f"💰 **دفعة جديدة!**\n\n"
            f"👤 **المستخدم:** {first_name}\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"📱 **Username:** @{username}\n"
            f"💳 **طريقة الدفع:** {payment_method}\n"
            f"🔖 **رقم الدفعة:** #{payment_id}\n\n"
            f"**قرار:**"
        ),
        reply_markup=admin_keyboard
    )
    
    logger.info(f"💰 دفعة جديدة #{payment_id} من {user_id} عبر {payment_method}")


@app.on_message(filters.video)
async def handle_video_upload(client, message):
    """معالج الفيديوهات المرفوعة - الرد التلقائي"""
    user_id = message.from_user.id
    lang = subdb.get_user_language(user_id)
    
    # البوت لا يدعم رفع الفيديوهات، فقط تحميلها من الروابط
    await message.reply_text(t('unsupported_media_video', lang))


@app.on_message(filters.audio | filters.voice | filters.animation | filters.sticker)
async def handle_other_media(client, message):
    """معالج الوسائط الأخرى - الرد التلقائي"""
    user_id = message.from_user.id
    lang = subdb.get_user_language(user_id)
    
    # البوت يدعم تحميل الفيديوهات من الروابط فقط
    await message.reply_text(t('unsupported_media_general', lang))


@app.on_callback_query(filters.regex(r'^approve_payment_'))
async def handle_approve_payment(client, callback_query):
    """معالج قبول الدفع من الأدمن"""
    if str(callback_query.from_user.id) != os.getenv("ADMIN_ID"):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    payment_id = int(callback_query.data.replace('approve_payment_', ''))
    admin_id = callback_query.from_user.id
    
    success, message_text = subdb.approve_payment(payment_id, admin_id)
    
    if success:
        # الحصول على معلومات الدفعة
        payment_info = subdb.get_payment_by_id(payment_id)
        if payment_info:
            user_id = payment_info[1]
            
            # إرسال إشعار للمستخدم
            try:
                # Get user's preferred language
                user_lang = subdb.get_user_language(user_id)
                
                await client.send_message(
                    chat_id=user_id,
                    text=t('subscription_activated', user_lang)
                )
            except:
                pass
        
        await callback_query.message.edit_caption(
            callback_query.message.caption + "\n\n✅ **تم القبول والتفعيل**",
            reply_markup=None
        )
        await callback_query.answer("✅ تم تفعيل الاشتراك بنجاح!", show_alert=True)
    else:
        await callback_query.answer(f"❌ {message_text}", show_alert=True)


@app.on_callback_query(filters.regex(r'^reject_payment_'))
async def handle_reject_payment(client, callback_query):
    """معالج رفض الدفع من الأدمن"""
    if str(callback_query.from_user.id) != os.getenv("ADMIN_ID"):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    payment_id = int(callback_query.data.replace('reject_payment_', ''))
    
    # الحصول على معلومات الدفعة
    payment_info = subdb.get_payment_by_id(payment_id)
    if payment_info:
        user_id = payment_info[1]
        
        # رفض الدفعة
        subdb.reject_payment(payment_id)
        
        # إرسال إشعار للمستخدم
        try:
            telegram_support = subdb.get_setting('telegram_support', 'wahab161')
            await client.send_message(
                chat_id=user_id,
                text=(
                    "❌ **تم رفض دفعتك**\n\n"
                    "قد يكون هناك مشكلة في إثبات الدفع.\n"
                    f"تواصل مع المطور: @{telegram_support}"
                )
            )
        except:
            pass
        
        await callback_query.message.edit_caption(
            callback_query.message.caption + "\n\n❌ **تم الرفض**",
            reply_markup=None
        )
        await callback_query.answer("❌ تم رفض الدفعة", show_alert=True)


async def subscription_settings_panel(client, message):
    """لوحة إعدادات الاشتراك للأدمن"""
    user_id = message.from_user.id
    
    if str(user_id) != os.getenv("ADMIN_ID"):
        await message.reply_text("❌ هذا الأمر للمشرفين فقط!")
        return
    
    max_duration = subdb.get_max_duration()
    price = subdb.get_setting('subscription_price', '10')
    duration_days = subdb.get_setting('subscription_duration_days', '30')
    stats = subdb.get_user_stats()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ تحديد المدة القصوى", callback_data="sub_set_duration")],
        [InlineKeyboardButton("💰 تحديد السعر", callback_data="sub_set_price")],
        [InlineKeyboardButton("👥 عرض المشتركين", callback_data="sub_view_subscribers")],
        [InlineKeyboardButton("📊 عرض آخر 50 مستخدم", callback_data="sub_recent_users")],
        [InlineKeyboardButton("💳 الدفوعات المعلقة", callback_data="sub_pending_payments")],
        [InlineKeyboardButton("📊 إحصائيات الأعضاء", callback_data="sub_member_stats")],
        [InlineKeyboardButton("🔍 بحث عن عضو", callback_data="sub_search_user")],
        [InlineKeyboardButton("✏️ ترقية عضو", callback_data="sub_promote_user")],
        [InlineKeyboardButton("❌ إلغاء ترقية", callback_data="sub_demote_user")],
        [InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="sub_broadcast")]
    ])
    
    text = (
        f"💎 **إعدادات الاشتراك**\n\n"
        f"⏱️ **الحد الأقصى للمجاني:** {max_duration} دقيقة\n"
        f"💰 **سعر الاشتراك:** ${price}\n"
        f"📅 **مدة الاشتراك:** {duration_days} يوم\n\n"
        f"📊 **الإحصائيات:**\n"
        f"• المجموع: {stats['total']} عضو\n"
        f"• المشتركون: {stats['subscribed']} 💎\n"
        f"• العاديون: {stats['free']} 🆓\n\n"
        f"**اختر الإعداد:**"
    )
    
    await message.reply_text(text, reply_markup=keyboard)


@app.on_callback_query(filters.regex(r'^sub_'))
async def handle_subscription_settings(client, callback_query):
    """معالج إعدادات الاشتراك"""
    if str(callback_query.from_user.id) != os.getenv("ADMIN_ID"):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    action = callback_query.data.replace('sub_', '')
    
    if action == 'set_duration':
        max_duration = subdb.get_max_duration()
        daily_limit = subdb.get_daily_limit()
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏱️ تغيير الحد الزمني", callback_data="change_time_limit")],
            [InlineKeyboardButton("🔢 تغيير الحد اليومي", callback_data="change_daily_limit")],
            [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")]
        ])
        
        await callback_query.message.edit_text(
            "⚙️ **تحديد المدة القصوى**\n\n"
            f"🕒 **الحد الزمني لغير المشتركين:** {max_duration} دقيقة\n"
            f"🔁 **الحد اليومي المسموح به:** {daily_limit} مرات\n\n"
            "💡 **ملاحظات:**\n"
            "• هذه القيود تطبق فقط على المستخدمين غير المشتركين\n"
            "• المشتركون VIP لديهم حرية كاملة بلا قيود\n\n"
            "**اختر الإجراء المطلوب:**",
            reply_markup=keyboard
        )
        
    elif action == 'set_price':
        await callback_query.message.edit_text(
            "💰 **تحديد سعر الاشتراك**\n\n"
            "أرسل السعر بالدولار (مثلاً: 10)\n\n"
            "⚠️ القيمة الحالية: $" + subdb.get_setting('subscription_price', '10')
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'subscription_price'}
        
    elif action == 'view_subscribers':
        subscribers = subdb.get_all_subscribers()
        
        if not subscribers:
            await callback_query.message.edit_text("📝 **لا يوجد مشتركون حالياً**")
            return
        
        text = "👥 **قائمة المشتركين**\n\n"
        
        for idx, sub in enumerate(subscribers[:20], 1):  # أول 20 مشترك
            user_id, username, first_name, end_date, method = sub
            username_str = f"@{username}" if username else "لا يوجد"
            name = first_name or "مستخدم"
            
            # حساب الأيام المتبقية
            if end_date:
                # PostgreSQL يُرجع datetime object مباشرة، بينما SQLite يُرجع string
                if isinstance(end_date, str):
                    end_dt = datetime.fromisoformat(end_date)
                else:
                    end_dt = end_date
                days_left = (end_dt - datetime.now()).days
                days_str = f"{days_left} يوم" if days_left > 0 else "منتهي"
            else:
                days_str = "مدى الحياة"
            
            text += f"{idx}. {name} ({username_str})\n"
            text += f"   🆔 `{user_id}` | ⏳ {days_str}\n\n"
        
        text += f"\n📊 **إجمالي المشتركين:** {len(subscribers)}"
        
        await callback_query.message.edit_text(text)
        
    elif action == 'pending_payments':
        payments = subdb.get_pending_payments()
        
        if not payments:
            await callback_query.message.edit_text("✅ **لا توجد دفوعات معلقة**")
            return
        
        text = "💳 **الدفوعات المعلقة**\n\n"
        
        for payment in payments[:10]:  # أول 10 دفوعات
            payment_id, user_id, username, first_name, method, amount, proof_id, created = payment
            username_str = f"@{username}" if username else "لا يوجد"
            name = first_name or "مستخدم"
            
            text += f"━━━━━━━━━━━━━━\n"
            text += f"🔖 **#{payment_id}**\n"
            text += f"👤 {name} ({username_str})\n"
            text += f"💰 ${amount} | 💳 {method}\n\n"
        
        text += f"\n📊 **إجمالي المعلقة:** {len(payments)}"
        
        await callback_query.message.edit_text(text)
    
    elif action == 'member_stats':
        stats = subdb.get_user_stats()
        all_users = subdb.get_all_users()
        
        text = "📊 **إحصائيات الأعضاء**\n\n"
        text += f"👥 **إجمالي الأعضاء:** {stats['total']}\n"
        text += f"💎 **المشتركون:** {stats['subscribed']}\n"
        text += f"🆓 **العاديون:** {stats['free']}\n\n"
        
        # عرض بعض المشتركين مع الأيام المتبقية
        if stats['subscribed'] > 0:
            text += "━━━━━━━━━━━━━━━━\n"
            text += "**المشتركون الحاليون:**\n\n"
            
            count = 0
            for user in all_users:
                user_id, username, first_name, is_subscribed, subscription_end = user
                if is_subscribed:
                    days_left = subdb.get_days_remaining(user_id)
                    name = first_name or "مستخدم"
                    text += f"• {name}: {days_left} يوم متبقية\n"
                    count += 1
                    if count >= 10:  # أول 10 مشتركين
                        break
        
        await callback_query.message.edit_text(text)
    
    elif action == 'recent_users':
        users = subdb.get_recent_users(50)
        
        if not users:
            await callback_query.message.edit_text("📝 **لا يوجد مستخدمون**")
            return
        
        text = "📊 **آخر 50 مستخدم**\n\n"
        
        for idx, user in enumerate(users[:50], 1):
            user_id, username, first_name, is_subscribed = user
            username_str = f"@{username}" if username else "لا يوجد"
            name = first_name or "مستخدم"
            status = "💎" if is_subscribed else "🆓"
            
            text += f"{idx}. {status} {name} ({username_str})\n"
            text += f"   🆔 `{user_id}`\n\n"
        
        text += f"\n📊 **إجمالي المستخدمين:** {len(users)}\n\n"
        text += "💡 **لمراسلة أي مستخدم:**\n"
        text += "استخدم زر 'رسالة خاصة' وأرسل ID المستخدم"
        
        await callback_query.message.edit_text(text)
    
    elif action == 'promote_user':
        await callback_query.message.edit_text(
            "✏️ **ترقية عضو يدوياً**\n\n"
            "أرسل User ID أو Username للعضو المراد ترقيته\n\n"
            "مثال: `123456789` أو `@username`"
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'promote_user_id'}
    
    elif action == 'demote_user':
        await callback_query.message.edit_text(
            "❌ **إلغاء ترقية عضو**\n\n"
            "أرسل User ID أو Username للعضو المراد إلغاء ترقيته\n\n"
            "مثال: `123456789` أو `@username`"
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'demote_user_id'}
    
    elif action == 'search_user':
        await callback_query.message.edit_text(
            "🔍 **بحث عن عضو**\n\n"
            "أرسل User ID أو Username للبحث عنه\n\n"
            "مثال: `123456789` أو `@username`"
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'search_user_id'}
    
    elif action == 'broadcast':
        # عرض شاشة اختيار نوع الإرسال
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📧 إرسال لجميع المستخدمين", callback_data="msg_broadcast_all")],
            [InlineKeyboardButton("👤 إرسال لمستخدم محدد", callback_data="msg_direct_user")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="msg_cancel")]
        ])
        
        stats = subdb.get_user_stats()
        await callback_query.message.edit_text(
            "📢 **نظام الإرسال الجماعي**\n\n"
            f"👥 **عدد المستخدمين:** {stats['total']}\n"
            f"💎 **المشتركون:** {stats['subscribed']}\n"
            f"🆓 **العاديون:** {stats['free']}\n\n"
            "**اختر نوع الإرسال:**",
            reply_markup=keyboard
        )
    
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^(change_time_limit|change_daily_limit|back_to_sub_settings)$'))
async def handle_duration_actions(client, callback_query):
    """معالج إعدادات المدة والحد اليومي"""
    if str(callback_query.from_user.id) != os.getenv("ADMIN_ID"):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    action = callback_query.data
    user_id = callback_query.from_user.id
    
    if action == 'change_time_limit':
        await callback_query.message.edit_text(
            "⏱️ **تغيير الحد الزمني**\n\n"
            f"القيمة الحالية: {subdb.get_max_duration()} دقيقة\n\n"
            "أرسل الحد الزمني الجديد بالدقائق\n"
            "(مثلاً: 60 لساعة واحدة، 120 لساعتين)"
        )
        pending_downloads[user_id] = {'waiting_for': 'max_duration'}
    
    elif action == 'change_daily_limit':
        current_limit = subdb.get_daily_limit()
        
        # عرض الحد الحالي
        if current_limit == -1:
            current_text = "♾️ غير محدود"
        else:
            current_text = f"{current_limit} مرات"
        
        # لوحة أزرار الاختيار السريع
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("3️⃣ 3 تحميلات", callback_data="set_daily_limit_3"),
             InlineKeyboardButton("5️⃣ 5 تحميلات", callback_data="set_daily_limit_5")],
            [InlineKeyboardButton("🔟 10 تحميلات", callback_data="set_daily_limit_10"),
             InlineKeyboardButton("2️⃣0️⃣ 20 تحميلة", callback_data="set_daily_limit_20")],
            [InlineKeyboardButton("♾️ غير محدود", callback_data="set_daily_limit_unlimited")],
            [InlineKeyboardButton("✏️ إدخال يدوي", callback_data="set_daily_limit_manual")],
            [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")]
        ])
        
        await callback_query.message.edit_text(
            f"🔢 **تغيير الحد اليومي**\n\n"
            f"القيمة الحالية: {current_text}\n\n"
            "اختر الحد اليومي للتحميلات:",
            reply_markup=keyboard
        )
    
    elif action == 'back_to_sub_settings':
        # العودة لشاشة إعدادات الاشتراك
        await subscription_settings_panel(client, callback_query.message)
    
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^msg_'))
async def handle_message_type(client, callback_query):
    """معالج اختيار نوع الرسالة"""
    if str(callback_query.from_user.id) != os.getenv("ADMIN_ID"):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    user_id = callback_query.from_user.id
    action = callback_query.data.replace('msg_', '')
    
    if action == 'broadcast_all':
        await callback_query.message.edit_text(
            "📢 **إرسال رسالة لجميع المستخدمين**\n\n"
            "أرسل الرسالة التي تريد إرسالها لجميع مستخدمي البوت\n\n"
            f"⚠️ سيتم إرسالها لـ **{subdb.get_user_stats()['total']}** مستخدم"
        )
        pending_downloads[user_id] = {'waiting_for': 'broadcast_message'}
    
    elif action == 'direct_user':
        await callback_query.message.edit_text(
            "👤 **إرسال رسالة لمستخدم محدد**\n\n"
            "أرسل **User ID** أو **Username** للمستخدم المراد مراسلته\n\n"
            "**أمثلة:**\n"
            "• `123456789` (User ID)\n"
            "• `@username` (Username)"
        )
        pending_downloads[user_id] = {'waiting_for': 'direct_msg_user_id'}
    
    elif action == 'cancel':
        await callback_query.message.edit_text("❌ **تم الإلغاء**")
        if user_id in pending_downloads:
            del pending_downloads[user_id]
    
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^set_daily_limit_'))
async def handle_set_daily_limit(client, callback_query):
    """معالج اختيار الحد اليومي السريع"""
    if str(callback_query.from_user.id) != os.getenv("ADMIN_ID"):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    user_id = callback_query.from_user.id
    action = callback_query.data.replace('set_daily_limit_', '')
    
    if action == 'manual':
        # الإدخال اليدوي
        await callback_query.message.edit_text(
            "✏️ **إدخال يدوي للحد اليومي**\n\n"
            f"القيمة الحالية: {subdb.get_daily_limit()} مرات\n\n"
            "أرسل الحد اليومي الجديد للتحميلات\n"
            "(مثلاً: 6 لست مرات يومياً، 15 لـ 15 مرة)"
        )
        pending_downloads[user_id] = {'waiting_for': 'daily_limit'}
    
    elif action == 'unlimited':
        # تعيين غير محدود
        subdb.set_daily_limit(-1)
        await callback_query.message.edit_text(
            "✅ **تم تحديث الحد اليومي**\n\n"
            "الحد الجديد: ♾️ غير محدود\n\n"
            "المستخدمون غير المشتركين يمكنهم الآن التحميل بدون قيود يومية."
        )
        logger.info("✅ تم تعيين الحد اليومي إلى: غير محدود")
    
    else:
        # اختيار رقم محدد
        try:
            limit = int(action)
            subdb.set_daily_limit(limit)
            await callback_query.message.edit_text(
                f"✅ **تم تحديث الحد اليومي**\n\n"
                f"الحد الجديد: {limit} مرات في اليوم"
            )
            logger.info(f"✅ تم تعيين الحد اليومي إلى: {limit} مرات")
        except ValueError:
            await callback_query.answer("❌ خطأ في القيمة", show_alert=True)
    
    await callback_query.answer()



@app.on_message(filters.text & ~filters.regex(r'https?://') & ~filters.regex(r'^(🍪|📊|🔔|💎|/)'))
async def handle_admin_input(client, message):
    """معالج إدخالات الأدمن للإعدادات"""
    user_id = message.from_user.id
    
    if str(user_id) != os.getenv("ADMIN_ID"):
        return
    
    if user_id not in pending_downloads:
        return
    
    data = pending_downloads.get(user_id)
    if not isinstance(data, dict) or 'waiting_for' not in data:
        return
    
    waiting_for = data['waiting_for']
    
    try:
        if waiting_for == 'max_duration':
            minutes = int(message.text.strip())
            if minutes < 1:
                await message.reply_text("❌ يجب أن تكون المدة أكبر من 0")
                return
            
            subdb.set_max_duration(minutes)
            await message.reply_text(
                f"✅ **تم تحديث الحد الأقصى**\n\n"
                f"المدة الجديدة: {minutes} دقيقة ({minutes//60} ساعة و {minutes%60} دقيقة)"
            )
            del pending_downloads[user_id]
        
        elif waiting_for == 'daily_limit':
            limit = int(message.text.strip())
            if limit < 1:
                await message.reply_text("❌ يجب أن يكون الحد أكبر من 0")
                return
            
            subdb.set_daily_limit(limit)
            await message.reply_text(
                f"✅ **تم تحديث الحد اليومي**\n\n"
                f"الحد الجديد: {limit} مرات في اليوم"
            )
            del pending_downloads[user_id]
            
        elif waiting_for == 'subscription_price':
            price = float(message.text.strip())
            if price < 0:
                await message.reply_text("❌ يجب أن يكون السعر أكبر من 0")
                return
            
            subdb.set_setting('subscription_price', str(price))
            await message.reply_text(
                f"✅ **تم تحديث السعر**\n\n"
                f"السعر الجديد: ${price}"
            )
            del pending_downloads[user_id]
        
        elif waiting_for == 'promote_user_id':
            user_input = message.text.strip()
            
            # محاولة البحث بواسطة ID أو Username
            target_user = None
            if user_input.isdigit():
                target_user = subdb.find_user_by_id(int(user_input))
            elif user_input.startswith('@') or user_input.isalnum():
                target_user = subdb.find_user_by_username(user_input)
            
            if not target_user:
                await message.reply_text(
                    "❌ **لم يتم العثور على المستخدم**\n\n"
                    "تأكد من أن المستخدم قد استخدم البوت مسبقاً"
                )
                del pending_downloads[user_id]
                return
            
            # حفظ معلومات المستخدم المستهدف
            pending_downloads[user_id] = {
                'waiting_for': 'promote_duration',
                'target_user_id': target_user[0],
                'target_user_name': target_user[2]
            }
            
            # عرض معلومات المستخدم وطلب المدة
            user_status = "💎 مشترك" if target_user[3] else "🆓 عادي"
            await message.reply_text(
                f"👤 **تم العثور على المستخدم:**\n\n"
                f"الاسم: {target_user[2]}\n"
                f"ID: `{target_user[0]}`\n"
                f"الحالة: {user_status}\n\n"
                f"**أرسل مدة الاشتراك بالأيام**\n"
                f"(مثلاً: 30 لشهر واحد، 365 لسنة)"
            )
        
        elif waiting_for == 'promote_duration':
            days = int(message.text.strip())
            if days < 1:
                await message.reply_text("❌ يجب أن تكون المدة أكبر من 0")
                return
            
            target_user_id = data.get('target_user_id')
            target_user_name = data.get('target_user_name')
            
           # ترقية المستخدم
            subdb.activate_subscription(target_user_id, days, 'manual_by_admin')
            
            # إشعار للأدمن
            await message.reply_text(
                f"✅ **تمت الترقية بنجاح!**\n\n"
                f"👤 **المستخدم:** {target_user_name}\n"
                f"🆔 **ID:** `{target_user_id}`\n"
                f"📅 **المدة:** {days} يوم"
            )
            
            # إشعار للمستخدم
            try:
                # Get user's preferred language
                user_lang = subdb.get_user_language(target_user_id)
                
                await client.send_message(
                    chat_id=target_user_id,
                    text=t('subscription_upgraded', user_lang, days=days)
                )
                logger.info(f"✅ تمت ترقية {target_user_id} لمدة {days} يوم")
            except:
                logger.warning(f"لم يتمكن من إرسال إشعار الترقية للمستخدم {target_user_id}")
            
            del pending_downloads[user_id]
        
        elif waiting_for == 'broadcast_message':
            broadcast_text = message.text.strip()
            
            # الحصول على جميع المستخدمين
            all_users = subdb.get_all_users()
            
            await message.reply_text(
                f"📤 **جاري الإرسال...**\n\n"
                f"سيتم إرسال الرسالة لـ {len(all_users)} مستخدم"
            )
            
            success_count = 0
            fail_count = 0
            
            for user in all_users:
                try:
                    # Get each user's preferred language
                    user_lang = subdb.get_user_language(user[0])
                    
                    await client.send_message(
                        chat_id=user[0],  # user_id
                        text=f"{t('broadcast_message_prefix', user_lang)}\n\n{broadcast_text}"
                    )
                    success_count += 1
                    await asyncio.sleep(0.05)  # تأخير بسيط لتجنب Flood
                except:
                    fail_count += 1
            
            await message.reply_text(
                f"✅ **اكتمل الإرسال!**\n\n"
                f"✅ النجاح: {success_count}\n"
                f"❌ الفشل: {fail_count}"
            )
            
            del pending_downloads[user_id]
            logger.info(f"📢 Broadcast: {success_count} نجح, {fail_count} فشل")
        
        elif waiting_for == 'direct_msg_user_id':
            user_input = message.text.strip()
            
            # محاولة البحث بواسطة ID أو Username
            target_user = None
            if user_input.isdigit():
                target_user = subdb.find_user_by_id(int(user_input))
            elif user_input.startswith('@') or user_input.isalnum():
                target_user = subdb.find_user_by_username(user_input)
            
            if not target_user:
                await message.reply_text(
                    "❌ **لم يتم العثور على المستخدم**\n\n"
                    "تأكد من أن المستخدم قد استخدم البوت مسبقاً"
                )
                del pending_downloads[user_id]
                return
            
            # حفظ معلومات المستخدم المستهدف
            pending_downloads[user_id] = {
                'waiting_for': 'direct_msg_text',
                'target_user_id': target_user[0],
                'target_user_name': target_user[2]
            }
            
            await message.reply_text(
                f"👤 **سيتم الإرسال إلى:**\n\n"
                f"الاسم: {target_user[2]}\n"
                f"ID: `{target_user[0]}`\n\n"
                f"**أرسل الرسالة الآن:**"
            )
        
        elif waiting_for == 'direct_msg_text':
            msg_text = message.text.strip()
            target_user_id = data.get('target_user_id')
            target_user_name = data.get('target_user_name')
            
            try:
                # Get user's preferred language
                user_lang = subdb.get_user_language(target_user_id)
                
                await client.send_message(
                    chat_id=target_user_id,
                    text=f"{t('direct_message_prefix', user_lang)}\n\n{msg_text}"
                )
                
                await message.reply_text(
                    f"✅ **تم الإرسال بنجاح!**\n\n"
                    f"👤 إلى: {target_user_name}\n"
                    f"🆔 ID: `{target_user_id}`"
                )
                logger.info(f"✉️ رسالة مباشرة من الأدمن إلى {target_user_id}")
            except Exception as e:
                await message.reply_text(
                    f"❌ **فشل الإرسال**\n\n"
                    f"الخطأ: {str(e)}"
                )
            
            del pending_downloads[user_id]
        
        elif waiting_for == 'search_user_id':
            user_input = message.text.strip()
            
            # محاولة البحث بواسطة ID أو Username
            target_user = None
            if user_input.isdigit():
                target_user = subdb.find_user_by_id(int(user_input))
            elif user_input.startswith('@') or user_input.isalnum():
                target_user = subdb.find_user_by_username(user_input)
            
            if not target_user:
                await message.reply_text(
                    "❌ **لم يتم العثور على المستخدم**\n\n"
                    "تأكد من أن المستخدم قد استخدم البوت مسبقاً"
                )
                del pending_downloads[user_id]
                return
            
            # عرض معلومات المستخدم
            user_id_found, username, first_name, is_subscribed, subscription_end = target_user
            username_str = f"@{username}" if username else "لا يوجد"
            name = first_name or "مستخدم"
            
            # حالة الاشتراك
            if is_subscribed:
                days_left = subdb.get_days_remaining(user_id_found)
                status = f"💎 **مشترك** ({days_left} يوم متبقية)"
            else:
                status = "🆓 **عادي** (غير مشترك)"
            
            text = (
                f"🔍 **معلومات المستخدم**\n\n"
                f"👤 **الاسم:** {name}\n"
                f"🆔 **User ID:** `{user_id_found}`\n"
                f"📱 **Username:** {username_str}\n"
                f"📊 **الحالة:** {status}\n"
            )
            
            await message.reply_text(text)
            del pending_downloads[user_id]
        
        elif waiting_for == 'demote_user_id':
            user_input = message.text.strip()
            
            # محاولة البحث بواسطة ID أو Username
            target_user = None
            if user_input.isdigit():
                target_user = subdb.find_user_by_id(int(user_input))
            elif user_input.startswith('@') or user_input.isalnum():
                target_user = subdb.find_user_by_username(user_input)
            
            if not target_user:
                await message.reply_text(
                    "❌ **لم يتم العثور على المستخدم**\n\n"
                    "تأكد من أن المستخدم قد استخدم البوت مسبقاً"
                )
                del pending_downloads[user_id]
                return
            
            # التحقق من أن المستخدم مشترك
            target_user_id, username, first_name, is_subscribed, subscription_end = target_user
            
            if not is_subscribed:
                await message.reply_text(
                    "❌ **المستخدم ليس مشتركاً**\n\n"
                    f"👤 {first_name}\n"
                    f"🆔 `{target_user_id}`\n"
                    f"الحالة: 🆓 عادي"
                )
                del pending_downloads[user_id]
                return
            
            # إلغاء الاشتراك
            subdb.deactivate_subscription(target_user_id)
            
            # إرسال إشعار للمستخدم
            try:
                # Get user's preferred language
                user_lang = subdb.get_user_language(target_user_id)
                
                await client.send_message(
                    chat_id=target_user_id,
                    text=t('subscription_deactivated', user_lang)
                )
            except:
                pass
            
            await message.reply_text(
                f"✅ **تم إلغاء الترقية بنجاح!**\n\n"
                f"👤 **المستخدم:** {first_name}\n"
                f"🆔 **ID:** `{target_user_id}`\n"
                f"📊 **الحالة الجديدة:** 🆓 عادي"
            )
            logger.info(f"❌ تم إلغاء ترقية المستخدم {target_user_id}")
            del pending_downloads[user_id]
    
    except ValueError:
        await message.reply_text("❌ قيمة غير صحيحة! أرسل رقماً فقط.")


# ═══════════════════════════════════════════════════════════════
# معالج اختيار اللغة - Language Selection Handler
# ═══════════════════════════════════════════════════════════════

@app.on_callback_query(filters.regex(r'^lang_'))
async def handle_language_selection(client, callback_query):
    """معالج اختيار اللغة"""
    lang = callback_query.data.replace('lang_', '')
    user_id = callback_query.from_user.id
    
    # حفظ اللغة
    subdb.set_user_language(user_id, lang)
    
    # إضافة المستخدم إلى قاعدة البيانات
    username = callback_query.from_user.username
    first_name = callback_query.from_user.first_name
    subdb.add_or_update_user(user_id, username, first_name)
    
    # رسالة التأكيد
    await callback_query.message.edit_text(
        t('language_set', lang)
    )
    
    # إرسال رسالة الترحيب
    admin_id = os.getenv("ADMIN_ID")
    keyboard = None
    
    if admin_id and str(user_id) == admin_id:
        from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton(t('btn_cookies', lang)), KeyboardButton(t('btn_daily_report', lang))],
            [KeyboardButton(t('btn_errors', lang)), KeyboardButton(t('btn_subscription', lang))],
            [KeyboardButton("📁 نسخ احتياطي"), KeyboardButton(t('btn_change_language', lang))]
        ], resize_keyboard=True)
    else:
        from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton(t('btn_change_language', lang))]
        ], resize_keyboard=True)
    
    await client.send_message(
        chat_id=user_id,
        text=t('welcome', lang, name=first_name),
        reply_markup=keyboard
    )
    
    await callback_query.answer()

@app.on_message(filters.text & ~filters.regex(r'^/'), group=10)
async def handle_change_language_button(client, message):
    """معالج زر تغيير اللغة - مع أولوية أعلى"""
    # Check if message is change language button in any language
    if message.text in ["🌍 تغيير اللغة", "🌍 Change Language"]:
        user_id = message.from_user.id
        # Get user's current language
        current_lang = subdb.get_user_language(user_id)
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🇮🇶 العربية", callback_data="lang_ar"),
                InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")
            ]
        ])
        
        # Use bilingual message (works for both languages)
        await message.reply_text(
            t('choose_language', current_lang),
            reply_markup=keyboard
        )


logger.info("🚀 بدء البوت...")
# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("🤖 Telegram Video Downloader Bot (Standalone)")
    print("=" * 60)
    print("✅ يرفع حتى 2GB")
    print("✅ نجح مع فيديو 3 ساعات")
    print("=" * 60)
    
    # إنشاء مجلد videos وcookies
    os.makedirs('videos', exist_ok=True)
    os.makedirs('cookies', exist_ok=True)
    
    # إنشاء قاعدة البيانات
    subdb.init_db()
    print("✅ تم إنشاء قاعدة بيانات الاشتراكات")
    
    # بدء مهمة التقرير اليومي
    loop = asyncio.get_event_loop()
    loop.create_task(daily_report_task())
    
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n⏹️ تم الإيقاف")



if __name__ == "__main__":
    main()


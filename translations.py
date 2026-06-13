# -*- coding: utf-8 -*-
"""
نظام الترجمات - دعم العربية والإنجليزية
Translation System - Arabic & English Support
"""

TRANSLATIONS = {
    'ar': {
        # الرسائل الأساسية - Basic Messages
        'welcome': '👋 أهلاً بك في بوت التحميل الأقوى!\n\n🚀 يمكنني تحميل أي فيديو من أشهر المنصات:\n• YouTube (حتى 4 ساعات)\n• Facebook\n• Instagram\n• TikTok\n• Snapchat (ستوريات)\n• Pinterest\n• X\n• Reddit\n\n🎬 مزايا البوت:\n• يدعم الجودة العالية Full HD\n• رفع حتى 2GB\n• فيديوهات حتى 4 ساعات لليوتيوب\n• بصيغة MP4 الجاهزة للمشاهدة\n\n📥 *أرسل رابط أي فيديو… والبوت سيتكفّل بالباقي!*',
        'choose_language': '🌍 **اختر لغتك**\nChoose Your Language',
        'language_set': '✅ تم تحديد اللغة: العربية 🇮🇶',
        'language_changed': '✅ تم تغيير اللغة إلى العربية 🇮🇶',
        
        # الأزرار - Buttons
        'btn_cookies': '🍪 Cookies',
        'btn_daily_report': '📊 التقرير اليومي',
        'btn_errors': '🔔 الأخطاء',
        'btn_subscription': '💎 إعدادات الاشتراك',
        'btn_change_language': '🌍 تغيير اللغة',
        'btn_my_subscription': '💎 اشتراكي',
        
        # Download
        'processing': '⏳ **جاري المعالجة...**',
        'start_downloading': '📥 **جاري التحميل...**',
        'upload_started': '⬆️ جاري الرفع...',
        'download_failed': '❌ **فشل التحميل**',
        'downloading': '📥 ⏬ جاري التحميل...\n📊 {percent}%\n\n💾 {current_mb} / {total_mb} MB\n🚀 {speed_mb} MB/s\n⏳ {eta}s\n\n{progress_bar}',
        'uploading': '📤 ⏫ جاري الرفع...\n📊 {percent}%\n\n💾 {current_mb} / {total_mb} MB\n🚀 {speed_mb} MB/s\n⏳ {eta}s\n\n{progress_bar}',
        'choose_quality': '📺 **اختر الجودة:**\n\n🎬 {title}\n⏱️ {duration}',
        'quality_best': '📺 1080p',
        'quality_medium': '📱 720p',
        'quality_audio': '🎵 MP3',
        
        # الاشتراك - Subscription
        'subscription_required': '⚠️ **يتطلب اشتراك مدفوع**\n\n🎬 **الفيديو:** {title}\n⏱️ **المدة:** {duration} دقيقة\n🔒 **الحد الأقصى للمجاني:** {max_duration} دقيقة',
        'subscription_benefits': '💎 **للحصول على اشتراك:**\n• تحميل فيديوهات بدون حد\n• أولوية في التحميل\n• دعم المطور',
        'subscription_status': '💎 **اشتراكك نشط**\n\n📅 **ينتهي في:** {end_date}\n\n⏳ **الوقت المتبقي:**\n• {days} يوم\n• {hours} ساعة',
        'not_subscribed': '❌ **ليس لديك اشتراك نشط**\n\nاشترك الآن للحصول على مزايا غير محدودة!',
        'subscription_upgraded': '🎉 **تمت ترقيتك للاشتراك المميز!**\n\n💎 يمكنك الآن تحميل فيديوهات بدون حد للمدة.\n📅 **مدة الاشتراك:** {days} يوم\n\nاستمتع بالخدمة! ✨',
        'subscription_activated': '🎉 **تم تفعيل اشتراكك!**\n\nيمكنك الآن تحميل فيديوهات بدون حد للمدة.\nاستمتع بالخدمة! 💎',
        'subscription_deactivated': '⚠️ **تم إلغاء اشتراكك**\n\nللمزيد من المعلومات، تواصل مع المطور.',
        'daily_limit_exceeded': '⚠️ **تجاوزت الحد اليومي**\n\n🔁 **الحد المسموح:** {limit} مرات في اليوم\n📊 **تحميلاتك اليوم:** {count} مرات',
        'downloads_remaining': '✅ **تم التحميل بنجاح!**\n\n📊 **باقي لك:** {remaining} تحميلات اليوم',
        'unlimited_downloads': '♾️ غير محدود',
        
        # الأخطاء - Errors
        'error_occurred': '❌ **حدث خطأ**\n\n{error}',
        'invalid_url': '❌ **رابط غير صحيح**\n\nأرسل رابط فيديو صالح',
        'user_not_found': '❌ **لم يتم العثور على المستخدم**\n\nتأكد من أن المستخدم قد استخدم البوت مسبقاً',
        'facebook_unavailable': '⚠️ **Facebook غير متاح حالياً**\n\nFacebook لديه مشاكل في استخراج البيانات.\n\n**السبب:** تغييرات في هيكل موقع Facebook\n\n**الحل:**\n• جرّب رابط آخر\n• انتظر تحديث yt-dlp\n• استخدم منصة أخرى (YouTube, Twitter)\n\nتم إرسال تنبيه للأدمن 🔔',
        'pinterest_unavailable': '⚠️ **Pinterest غير متاح حالياً**\n\nPinterest لديه مشاكل في سيرفراته.\n\nجرّب:\n• رابط آخر من Pinterest\n• منصة أخرى (YouTube, Twitter, TikTok)\n• المحاولة لاحقاً\n\nتم إرسال تنبيه للأدمن 🔔',
        'generic_error': '❌ **حدث خطأ**\n\n**المشكلة:** {error}...\n\nتم إرسال تنبيه للأدمن 🔔',
        
        # الإدارة - Administration
        'admin_only': '❌ هذا الأمر للمشرفين فقط!',
        'success': '✅ تم بنجاح!',
        'cancelled': '❌ تم الإلغاء',
        'broadcast_message_prefix': '📢 **رسالة من المطور:**',
        'direct_message_prefix': '✉️ **رسالة من المطور:**',
        'reply_button': '↩️ رد',
        'type_your_reply': '✍️ **أرسل ردك الآن:**',
        'member_reply_prefix': '📨 **رد من العضو {name}** (`{user_id}`)**:**',
        'reply_sent': '✅ **تم إرسال ردك بنجاح**',
        'reply_failed': '❌ **تعذّر إرسال الرد** (ربما حظر المستخدم البوت)',

        # رسائل الاشتراك المفصلة
        'subscribe_now': '💎 اشترك الآن',
        'contact_developer': '📱 تواصل مع المطور',
        'binance_pay': '💰 Binance Pay',
        'visa_card': '💳 Visa',
        'mastercard': '💳 Mastercard',
        'telegram_contact': '📱 تواصل عبر Telegram',
        'back': '« رجوع',
        
        # رسائل التحميل المفصلة
        'start_download': '⏳ بدء التحميل...',
        'downloading_detailed': '📥 جاري التحميل...\n\n📊 {percent}%\n💾 {current} / {total} MB\n🚀 {speed} MB/s\n⏳ {eta}s',
        'uploading_detailed': '📤 جاري الرفع...\n\n📊 {percent}%\n💾 {current} / {total} MB\n🚀 {speed} MB/s\n⏳ {eta}s',
        'video_downloaded': '✅ تم التحميل! جاري الرفع...',
        
        # دعم المطور عبر Binance
        'support_dev_binance': '💰 دعم المطور عبر Binance',
        'binance_pay_id': '💳 Binance Pay ID: {binance_id}',
        
        # Payment screens
        'payment_binance_title': '💳 الدفع عبر Binance Pay',
        'payment_amount': '💰 المبلغ: $10',
        'payment_binance_steps': 'الخطوات:\n1. افتح تطبيق Binance\n2. اذهب إلى Binance Pay\n3. أرسل $10 إلى ID: {binance_id}\n4. التقط صورة للدفعة (screenshot)\n5. أرسل الصورة هنا\n\n✅ بعد إرسال الصورة، سيتم مراجعة دفعتك وتفعيل الاشتراك',
        'payment_visa_title': '💳 الدفع عبر Visa',
        'payment_visa_instructions': 'للدفع عبر Visa، تواصل مع المطور:\n👤 @{support_username}\n\nسيتم إرشادك لإكمال عملية الدفع.',
        'payment_mastercard_title': '💳 الدفع عبر Mastercard',
        'payment_mastercard_instructions': 'للدفع عبر Mastercard، تواصل مع المطور:\n👤 @{support_username}\n\nسيتم إرشادك لإكمال عملية الدفع.',
        'video_label': '🎬 فيديو',
        'audio_label': '🎵 صوت',
        'choose_payment_method': 'اختر طريقة الدفع:',
        
        # Queue System
        'queue_rate_limit': '⏳ **انتظر قليلاً!**\n\nيجب الانتظار {seconds} ثانية قبل إرسال رابط آخر.\n\n💡 يمكنك إرسال رابط آخر بعد {seconds} ثواني.',
        'queue_position': '📋 **تم إضافة الرابط للطابور**\n\n⏱️ **موقعك:** {position} في الطابور\n⚙️ جاري معالجة الفيديو الأول...\n\nانتظر حتى يكتمل التحميل الحالي 🔄',
        'queue_processing_current': '⚙️ **جاري معالجة طلبك...**\n\n📥 يتم الآن تحميل الفيديو الحالي\n⏳ انتظر حتى يكتمل التحميل\n\n💡 سيتم معالجة طلبك التالي تلقائياً',
        'queue_next_download': '🔄 **بدء التحميل التالي...**\n\n📋 يوجد {remaining} فيديو في الطابور',
        
        # Unsupported Media
        'unsupported_media_photo': '📷 البوت لا يدعم تحميل الصور حالياً.\n\nℹ️ إذا كنت تريد الدفع، اضغط /start ثم اختر الاشتراك.',
        'unsupported_media_video': '🎥 البوت لا يدعم رفع الفيديوهات مباشرة.\n\n✅ لتحميل فيديو، أرسل رابط الفيديو من:\n• Facebook\n• Instagram\n• TikTok\n• YouTube\n• وأكثر...',
        'unsupported_media_general': '📎 البوت يعمل مع روابط الفيديوهات فقط.\n\n✅ أرسل رابط فيديو من أي منصة مدعومة.',
    },
    
    'en': {
        # Basic Messages
        'welcome': '👋 Welcome to the ultimate video downloader bot!\n\n🚀 I can download videos from all major platforms:\n• YouTube (up to 4 hours)\n• Facebook\n• Instagram\n• TikTok\n• Snapchat Stories\n• Pinterest\n• X\n• Reddit\n\n🎬 Bot Features:\n• Supports Full HD quality\n• Uploads up to 2GB\n• YouTube videos up to 4 hours\n• Delivered in MP4 format\n\n📥 *Send me any video link… and I\'ll handle the rest!*',
        'choose_language': '🌍 **اختر لغتك**\nChoose Your Language',
        'language_set': '✅ Language set to: English 🇺🇸',
        'language_changed': '✅ Language changed to English 🇺🇸',
        
        # Buttons
        'btn_cookies': '🍪 Cookies',
        'btn_daily_report': '📊 Daily Report',
        'btn_errors': '🔔 Errors',
        'btn_subscription': '💎 Subscription Settings',
        'btn_change_language': '🌍 Change Language',
        'btn_my_subscription': '💎 My Subscription',
        
        # Download
        'processing': '⏳ **Processing...**',
        'start_downloading': '📥 **Downloading...**',
        'upload_started': '⬆️ Uploading...',
        'download_failed': '❌ **Download Failed**',
        'downloading': '📥 ⏬ Downloading...\n📊 {percent}%\n\n💾 {current_mb} / {total_mb} MB\n🚀 {speed_mb} MB/s\n⏳ {eta}s\n\n{progress_bar}',
        'uploading': '📤 ⏫ Uploading...\n📊 {percent}%\n\n💾 {current_mb} / {total_mb} MB\n🚀 {speed_mb} MB/s\n⏳ {eta}s\n\n{progress_bar}',
        'choose_quality': '📺 **Choose Quality:**\n\n🎬 {title}\n⏱️ {duration}',
        'quality_best': '📺 1080p',
        'quality_medium': '📱 720p',
        'quality_audio': '🎵 MP3',
        
        # Subscription
        'subscription_required': '⚠️ **Subscription Required**\n\n🎬 **Video:** {title}\n⏱️ **Duration:** {duration} minutes\n🔒 **Free Limit:** {max_duration} minutes',
        'subscription_benefits': '💎 **Get Subscription:**\n• Unlimited video downloads\n• Priority downloads\n• Support developer',
        'subscription_status': '💎 **Your Subscription is Active**\n\n📅 **Expires on:** {end_date}\n\n⏳ **Time Remaining:**\n• {days} days\n• {hours} hours',
        'not_subscribed': '❌ **No Active Subscription**\n\nSubscribe now to get unlimited features!',
        'subscription_upgraded': '🎉 **You\'ve been upgraded to Premium!**\n\n💎 You can now download unlimited videos without duration limits.\n📅 **Subscription Duration:** {days} days\n\nEnjoy the service! ✨',
        'subscription_activated': '🎉 **Your subscription has been activated!**\n\nYou can now download unlimited videos without duration limits.\nEnjoy the service! 💎',
        'subscription_deactivated': '⚠️ **Your subscription has been cancelled**\n\nFor more information, contact the developer.',
        'daily_limit_exceeded': '⚠️ **Daily Limit Exceeded**\n\n🔁 **Allowed Limit:** {limit} times per day\n📊 **Your Downloads Today:** {count} times',
        'downloads_remaining': '✅ **Download Successful!**\n\n📊 **You have:** {remaining} downloads remaining today',
        'unlimited_downloads': '♾️ Unlimited',
        
        # Errors
        'error_occurred': '❌ **An Error Occurred**\n\n{error}',
        'invalid_url': '❌ **Invalid URL**\n\nPlease send a valid video link',
        'user_not_found': '❌ **User Not Found**\n\nMake sure the user has used the bot before',
        'facebook_unavailable': '⚠️ **Facebook Currently Unavailable**\n\nFacebook has issues extracting data.\n\n**Reason:** Changes in Facebook\'s website structure\n\n**Solution:**\n• Try another link\n• Wait for yt-dlp update\n• Use another platform (YouTube, Twitter)\n\nAdmin has been notified 🔔',
        'pinterest_unavailable': '⚠️ **Pinterest Currently Unavailable**\n\nPinterest is experiencing server issues.\n\nTry:\n• Another Pinterest link\n• Another platform (YouTube, Twitter, TikTok)\n• Try again later\n\nAdmin has been notified 🔔',
        'generic_error': '❌ **An Error Occurred**\n\n**Issue:** {error}...\n\nAdmin has been notified 🔔',
        
        # Administration
        'admin_only': '❌ This command is for admins only!',
        'success': '✅ Success!',
        'cancelled': '❌ Cancelled',
        'broadcast_message_prefix': '📢 **Message from Developer:**',
        'direct_message_prefix': '✉️ **Message from Developer:**',
        'reply_button': '↩️ Reply',
        'type_your_reply': '✍️ **Type your reply now:**',
        'member_reply_prefix': '📨 **Reply from {name}** (`{user_id}`)**:**',
        'reply_sent': '✅ **Your reply was sent**',
        'reply_failed': '❌ **Could not send the reply** (user may have blocked the bot)',

        # Detailed subscription messages
        'subscribe_now': '💎 Subscribe Now',
        'contact_developer': '📱 Contact Developer',
        'binance_pay': '💰 Binance Pay',
        'visa_card': '💳 Visa',
        'mastercard': '💳 Mastercard',
        'telegram_contact': '📱 Contact via Telegram',
        'back': '« Back',
        
        # Detailed download messages
        'start_download': '⏳ Starting download...',
        'downloading_detailed': '📥 Downloading...\n\n📊 {percent}%\n💾 {current} / {total} MB\n🚀 {speed} MB/s\n⏳ {eta}s',
        'uploading_detailed': '📤 Uploading...\n\n📊 {percent}%\n💾 {current} / {total} MB\n🚀 {speed} MB/s\n⏳ {eta}s',
        'video_downloaded': '✅ Downloaded! Uploading...',
        
        # Support developer via Binance
        'support_dev_binance': '💰 Support Developer via Binance',
        'binance_pay_id': '💳 Binance Pay ID: {binance_id}',
        
        # Payment screens
        'payment_binance_title': '💳 Pay via Binance Pay',
        'payment_amount': '💰 Amount: $10',
        'payment_binance_steps': 'Steps:\n1. Open Binance app\n2. Go to Binance Pay\n3. Send $10 to ID: {binance_id}\n4. Take a screenshot of the payment\n5. Send the screenshot here\n\n✅ After sending the screenshot, your payment will be reviewed and subscription activated',
        'payment_visa_title': '💳 Pay via Visa',
        'payment_visa_instructions': 'To pay via Visa, contact the developer:\n👤 @{support_username}\n\nYou will be guided to complete the payment.',
        'payment_mastercard_title': '💳 Pay via Mastercard',
        'payment_mastercard_instructions': 'To pay via Mastercard, contact the developer:\n👤 @{support_username}\n\nYou will be guided to complete the payment.',
        'video_label': '🎬 Video',
        'audio_label': '🎵 Audio',
        'choose_payment_method': 'Choose payment method:',
        
        # Queue System
        'queue_rate_limit': '⏳ **Please wait!**\n\nYou must wait {seconds} seconds before sending another link.\n\n💡 You can send another link in {seconds} seconds.',
        'queue_position': '📋 **Link added to queue**\n\n⏱️ **Your position:** {position} in queue\n⚙️ Processing first video...\n\nPlease wait for current download to complete 🔄',
        'queue_processing_current': '⚙️ **Processing your request...**\n\n📥 Currently downloading video\n⏳ Please wait for download to complete\n\n💡 Your next request will be processed automatically',
        'queue_next_download': '🔄 **Starting next download...**\n\n📋 {remaining} video(s) remaining in queue',
        
        # Unsupported Media
        'unsupported_media_photo': '📷 Bot does not support photo uploads currently.\n\nℹ️ If you want to subscribe, press /start then choose subscription.',
        'unsupported_media_video': '🎥 Bot does not support direct video uploads.\n\n✅ To download a video, send a video link from:\n• Facebook\n• Instagram\n• TikTok\n• YouTube\n• and more...',
        'unsupported_media_general': '📎 Bot works with video links only.\n\n✅ Send a video link from any supported platform.',
    }
}

def t(key, lang='ar', **kwargs):
    """
    Get translated text
    
    Args:
        key: Translation key
        lang: Language code ('ar' or 'en')
        **kwargs: Format parameters
    
    Returns:
        Translated and formatted text
    """
    text = TRANSLATIONS.get(lang, TRANSLATIONS['ar']).get(key, key)
    
    if kwargs:
        try:
            return text.format(**kwargs)
        except KeyError:
            return text
    
    return text

def get_available_languages():
    """Get list of available language codes"""
    return list(TRANSLATIONS.keys())

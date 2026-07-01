# -*- coding: utf-8 -*-
"""
نظام الترجمات - دعم العربية والإنجليزية
Translation System - Arabic & English Support
"""

TRANSLATIONS = {
    'ar': {
        # الرسائل الأساسية - Basic Messages
        'welcome': '╭─────────────────╮\n   ✦ 𝗩𝗜𝗗𝗘𝗢 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗘𝗥 ✦\n╰─────────────────╯\n\n🌟 أهـلاً وسهـلاً **{name}** 🌟\nنوّرت **بوت التحميل الأقوى** 🏆\n\n🌐 **المنصّات المدعومة:**\n▸ YouTube ▸ TikTok ▸ Instagram\n▸ Facebook ▸ Snapchat ▸ X\n▸ Pinterest ▸ Reddit ▸ Threads\n\n💎 **المزايا:**\n🎬 جودة عالية حتى Full HD\n🚀 رفع حتى 2GB\n⏱️ فيديوهات حتى 4 ساعات\n🎵 تحميل الصوت MP3\n⚡ إرسال فوري للمقاطع المكرّرة\n\n━━━━━━━━━━━━━━━\n📥 أرسل **رابط أي فيديو**… وخلّ الباقي علينا! ✨',
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
        'downloading_images': '🖼️ **جاري تحميل الصور...**',
        'uploading_images': '📤 **جاري إرسال الصور ({current}/{total})...**',
        'no_media_found': '❌ **لم يتم العثور على وسائط قابلة للتحميل في هذا الرابط**',
        'images_caption': '🖼️ `{title}`\n\n📷 {count} صورة\n👤 {user}{promo}',
        'downloading': '📥 ⏬ جاري التحميل...\n📊 {percent}%\n\n💾 {current_mb} / {total_mb} MB\n🚀 {speed_mb} MB/s\n⏳ {eta}s\n\n{progress_bar}',
        'uploading': '📤 ⏫ جاري الرفع...\n📊 {percent}%\n\n💾 {current_mb} / {total_mb} MB\n🚀 {speed_mb} MB/s\n⏳ {eta}s\n\n{progress_bar}',
        'choose_quality': '📥 **اختر نوع التحميل:**\n\n🎬 {title}\n⏱️ {duration}',
        'btn_video': '🎬 فيديو',
        'btn_audio': '🎵 صوت (MP3)',
        'quality_best': '📺 1080p',
        'quality_medium': '📱 720p',
        'quality_480': '📲 480p',
        'quality_360': '🪶 360p',
        'quality_audio': '🎵 MP3',

        # السجل والإحصائيات والدعوات - History / Stats / Referral
        'btn_my_downloads': '📥 تحميلاتي',
        'btn_invite': '🎁 ادعُ أصدقاءك',
        'history_title': '📥 **آخر تحميلاتك:**',
        'history_tap_hint': '👇 اضغط أي فيديو لإعادة إرساله فوراً',
        'history_empty': '📭 لا توجد تحميلات سابقة بعد.',
        'history_item': '{idx}. {title}\n   ⏱️ {date} • {quality}',
        'invite_info': '🎁 **ادعُ أصدقاءك وزِد حدّك اليومي!**\n\nكل صديق ينضم عبر رابطك يزيد تحميلك اليومي **+{bonus}** فيديو (دائماً).\n\n🔗 **رابطك:**\n`{link}`\n\n👥 عدد دعواتك: **{count}**\n📥 حدّك اليومي الآن: **{limit}** فيديو/يوم',
        'referral_granted': '🎁 **انضم صديق عبر رابطك!**\n\nزاد حدّك اليومي — أصبح بإمكانك تحميل **{limit}** فيديو يومياً! 🎉',
        'dlstats_title': '📊 **إحصائيات التحميل**\n\n📥 اليوم: **{today}**\n📦 الإجمالي: **{total}**\n⚡ من الكاش: **{cache_hits}** مرة (عناصر مخزّنة: {cache_items})\n\n🏆 **أكثر المنصات:**\n{platforms}\n\n👥 **أنشط المستخدمين:**\n{top_users}',
        'playlist_detected': '📃 **هذا رابط قائمة تشغيل** فيها {count} مقطع.\nاضغط لتحميل أول {max} مقاطع بأفضل جودة:',
        'playlist_btn': '📥 حمّل القائمة ({n})',
        'playlist_started': '📃 بدأ تحميل {n} مقاطع من القائمة...',
        'playlist_subscribers_only': '📃 **هذا رابط قائمة تشغيل**\n\nتحميل القوائم متاح للمشتركين فقط.\nأرسل رابط فيديو واحد، أو اشترك للاستفادة من تحميل القوائم.',

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
        'file_too_large': '❌ **الملف كبير جداً!**\n\n📊 {size} MB\n🔒 الحد الأقصى: 2000 MB',
        'problem_fixed': '✅ **تم إصلاح مشكلتك!**\n\nالمشكلة التي واجهتها مع الرابط:\n`{url}`\n\nتم حلها الآن. يمكنك المحاولة مرة أخرى! 🎉',
        'payment_received': '✅ **تم استلام إثبات الدفع!**\n\nسيتم مراجعة دفعتك من قبل المسؤول.\nستصلك رسالة فور تفعيل اشتراكك! 🎉\n\n⏳ الانتظار المتوقع: أقل من 24 ساعة',
        'payment_rejected': '❌ **تم رفض دفعتك**\n\nقد يكون هناك مشكلة في إثبات الدفع.\nتواصل مع المطور: @{support}',
        
        # الأخطاء - Errors
        'error_occurred': '❌ **حدث خطأ**\n\n{error}',
        'invalid_url': '❌ **رابط غير صحيح**\n\nأرسل رابط فيديو صالح',
        'content_restricted': '⚠️ **محتوى مقيّد**\n\nهذا المنشور مقيّد بالعمر أو مصنّف كمحتوى حسّاس على المنصة، ويتعذّر تحميله حالياً.',
        'adult_blocked': '🔞 **محتوى محظور**\n\nهذا البوت لا يسمح بتحميل المحتوى الإباحي أو غير اللائق.',
        'banned_screen': '🚫 **تم حظرك من البوت**\n\n📌 **السبب:** تم تحميل مقاطع إباحية.\n\nيمكنك العودة بالتعهّد بعدم تكرار ذلك. أي مخالفة بعد التعهّد = حظر دائم.',
        'banned_permanent': '🚫 **أنت محظور نهائياً**\n\n📌 **السبب:** تكرار تحميل محتوى إباحي بعد التعهّد.\n\nالحظر دائم — تواصل مع الأدمن لمراجعة حالتك.',
        'btn_pledge': '✋ أتعهّد بعدم تحميل محتوى إباحي',
        'pledge_accepted': '✅ **تم قبول تعهّدك ورُفع الحظر.**\n\nالتزم — أي مخالفة قادمة تعني حظراً دائماً.',
        'pledge_denied': '❌ سبق أن تعهّدت ونقضت تعهّدك.\nالحظر الآن دائم — تواصل مع الأدمن.',
        'ban_reason_adult': 'تم تحميل مقاطع إباحية',
        'ask_gender': '👤 **قبل التحميل، أجب على سؤال واحد:**\n\nهل أنت رجل أم امرأة؟',
        'gender_male': '👨 رجل',
        'gender_female': '👩 امرأة',
        'answer_yes': '✅ نعم',
        'answer_no': '❌ لا',
        'survey_done': '✅ **شكراً!** الآن أرسل رابط الفيديو لتحميله.',
        'btn_edit_gender': '🧍 تعديل جنسي',
        'edit_gender_prompt': '👤 **اختر جنسك الصحيح:**',
        'gender_updated': '✅ **تم تحديث جنسك في النظام.**',
        'reminder_inactive': '👋 **اشتقنا لك!**\n\nمرّت فترة ولم تحمّل أي فيديو.\nجرّب الآن — أرسل رابط أي فيديو ونحمّله لك فوراً! 🎬',
        'choose_plan': '💎 **اختر خطة الاشتراك:**',
        'plan_monthly': '📅 شهري',
        'plan_yearly': '🗓️ سنوي',
        'free_label': 'مجاني',
        'plan_activated_free': '🎉 **تم تفعيل اشتراكك المجاني!**\n\n📅 المدة: {days} يوم\nاستمتع بالخدمة بلا حدود! 💎',
        'downloads_paused': '🛠️ **البوت في وضع الصيانة حالياً**\n\nالتحميل متوقف مؤقتاً، نعمل على تحسين الخدمة.\nرجاءً حاول لاحقاً. 🙏',
        'fsub_required': '⚠️ للوصول إلى ميزات البوت، يجب الاشتراك في قنواتنا، ثم اضغط على «تحقق».',
        'fsub_join_btn': '📢 اشترك #{n}',
        'fsub_check_btn': 'تحقق ✅',
        'fsub_thanks': '✅ شكراً لاشتراكك! الآن أرسل الرابط وحمّل الفيديو.',
        'fsub_not_yet': '❌ لم تشترك بعد في جميع القنوات. اشترك ثم اضغط «تحقق».',
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
        'btn_yes': '✅ نعم',
        'btn_no': '❌ لا',
        'vote_yes_ack': '✅ شكراً، تم تسجيل ردك: نعم',
        'vote_no_ack': '❌ تم تسجيل ردك: لا',
        'drm_protected': '🔒 **هذا الفيديو محمي بحقوق النشر (DRM)**\n\nلا يمكن تحميله — هذه حماية من المنصة نفسها ولا يمكن تجاوزها (مثل الأفلام والأغاني الرسمية المدفوعة). جرّب رابطاً آخر.',

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
        'welcome': '╭─────────────────╮\n   ✦ 𝗩𝗜𝗗𝗘𝗢 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗘𝗥 ✦\n╰─────────────────╯\n\n🌟 Welcome **{name}** 🌟\nto the **Ultimate Downloader** 🏆\n\n🌐 **Supported platforms:**\n▸ YouTube ▸ TikTok ▸ Instagram\n▸ Facebook ▸ Snapchat ▸ X\n▸ Pinterest ▸ Reddit ▸ Threads\n\n💎 **Features:**\n🎬 Up to Full HD quality\n🚀 Upload up to 2GB\n⏱️ Videos up to 4 hours\n🎵 MP3 audio download\n⚡ Instant resend for cached clips\n\n━━━━━━━━━━━━━━━\n📥 Just send **any video link**… we\'ll handle the rest! ✨',
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
        'downloading_images': '🖼️ **Downloading images...**',
        'uploading_images': '📤 **Sending images ({current}/{total})...**',
        'no_media_found': '❌ **No downloadable media found at this link**',
        'images_caption': '🖼️ `{title}`\n\n📷 {count} photos\n👤 {user}{promo}',
        'downloading': '📥 ⏬ Downloading...\n📊 {percent}%\n\n💾 {current_mb} / {total_mb} MB\n🚀 {speed_mb} MB/s\n⏳ {eta}s\n\n{progress_bar}',
        'uploading': '📤 ⏫ Uploading...\n📊 {percent}%\n\n💾 {current_mb} / {total_mb} MB\n🚀 {speed_mb} MB/s\n⏳ {eta}s\n\n{progress_bar}',
        'choose_quality': '📥 **Choose download type:**\n\n🎬 {title}\n⏱️ {duration}',
        'btn_video': '🎬 Video',
        'btn_audio': '🎵 Audio (MP3)',
        'quality_best': '📺 1080p',
        'quality_medium': '📱 720p',
        'quality_480': '📲 480p',
        'quality_360': '🪶 360p',
        'quality_audio': '🎵 MP3',

        # History / Stats / Referral
        'btn_my_downloads': '📥 My Downloads',
        'btn_invite': '🎁 Invite Friends',
        'history_title': '📥 **Your recent downloads:**',
        'history_tap_hint': '👇 Tap any video to resend it instantly',
        'history_empty': '📭 No downloads yet.',
        'history_item': '{idx}. {title}\n   ⏱️ {date} • {quality}',
        'invite_info': '🎁 **Invite friends and raise your daily limit!**\n\nEach friend who joins through your link adds **+{bonus}** video to your daily downloads (permanently).\n\n🔗 **Your link:**\n`{link}`\n\n👥 Your invites: **{count}**\n📥 Your daily limit now: **{limit}** videos/day',
        'referral_granted': '🎁 **A friend joined via your link!**\n\nYour daily limit increased — you can now download **{limit}** videos per day! 🎉',
        'dlstats_title': '📊 **Download Statistics**\n\n📥 Today: **{today}**\n📦 Total: **{total}**\n⚡ From cache: **{cache_hits}** times (stored items: {cache_items})\n\n🏆 **Top platforms:**\n{platforms}\n\n👥 **Most active users:**\n{top_users}',
        'playlist_detected': '📃 **This is a playlist** with {count} videos.\nTap to download the first {max} in best quality:',
        'playlist_btn': '📥 Download playlist ({n})',
        'playlist_started': '📃 Started downloading {n} videos from the playlist...',
        'playlist_subscribers_only': '📃 **This is a playlist link**\n\nPlaylist downloads are for subscribers only.\nSend a single video link, or subscribe to download playlists.',

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
        'file_too_large': '❌ **File too large!**\n\n📊 {size} MB\n🔒 Maximum: 2000 MB',
        'problem_fixed': '✅ **Your issue is fixed!**\n\nThe problem you had with the link:\n`{url}`\n\nIt has been resolved. You can try again! 🎉',
        'payment_received': '✅ **Payment proof received!**\n\nYour payment will be reviewed by the admin.\nYou will get a message as soon as your subscription is activated! 🎉\n\n⏳ Expected wait: under 24 hours',
        'payment_rejected': '❌ **Your payment was rejected**\n\nThere may be an issue with the payment proof.\nContact the developer: @{support}',
        
        # Errors
        'error_occurred': '❌ **An Error Occurred**\n\n{error}',
        'invalid_url': '❌ **Invalid URL**\n\nPlease send a valid video link',
        'content_restricted': '⚠️ **Restricted Content**\n\nThis post is age-restricted or flagged as sensitive on the platform, and cannot be downloaded right now.',
        'adult_blocked': '🔞 **Blocked Content**\n\nThis bot does not allow downloading adult or inappropriate content.',
        'banned_screen': '🚫 **You have been banned**\n\n📌 **Reason:** attempting to download adult content.\n\nYou may return by pledging not to repeat it. Any violation after the pledge = permanent ban.',
        'banned_permanent': '🚫 **You are permanently banned**\n\n📌 **Reason:** repeated adult content downloads after pledging.\n\nThe ban is permanent — contact the admin to review your case.',
        'btn_pledge': '✋ I pledge not to download adult content',
        'pledge_accepted': '✅ **Your pledge is accepted and the ban is lifted.**\n\nStay committed — any future violation means a permanent ban.',
        'pledge_denied': '❌ You already pledged and broke it.\nThe ban is now permanent — contact the admin.',
        'ban_reason_adult': 'attempted to download adult content',
        'ask_gender': '👤 **Before downloading, answer one question:**\n\nAre you a man or a woman?',
        'gender_male': '👨 Man',
        'gender_female': '👩 Woman',
        'answer_yes': '✅ Yes',
        'answer_no': '❌ No',
        'survey_done': '✅ **Thank you!** Now send the video link to download.',
        'btn_edit_gender': '🧍 Edit my gender',
        'edit_gender_prompt': '👤 **Choose your correct gender:**',
        'gender_updated': '✅ **Your gender has been updated.**',
        'reminder_inactive': '👋 **We missed you!**\n\nIt has been a while since your last download.\nTry now — send any video link and we will download it instantly! 🎬',
        'choose_plan': '💎 **Choose a subscription plan:**',
        'plan_monthly': '📅 Monthly',
        'plan_yearly': '🗓️ Yearly',
        'free_label': 'Free',
        'plan_activated_free': '🎉 **Your free subscription is active!**\n\n📅 Duration: {days} days\nEnjoy unlimited access! 💎',
        'downloads_paused': '🛠️ **The bot is under maintenance**\n\nDownloads are temporarily paused while we improve the service.\nPlease try again later. 🙏',
        'fsub_required': '⚠️ To access the bot\'s features, you need to subscribe to our partners, then click "Check".',
        'fsub_join_btn': '📢 Subscribe #{n}',
        'fsub_check_btn': 'Check ✅',
        'fsub_thanks': '✅ Thanks for subscribing! Now send the link and download the video.',
        'fsub_not_yet': '❌ You are not subscribed to all channels yet. Subscribe then press Check.',
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
        'btn_yes': '✅ Yes',
        'btn_no': '❌ No',
        'vote_yes_ack': '✅ Thanks, recorded: Yes',
        'vote_no_ack': '❌ Recorded: No',
        'drm_protected': '🔒 **This video is DRM protected**\n\nIt cannot be downloaded — this protection comes from the platform itself and cannot be bypassed (e.g. paid movies and official music). Try another link.',

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
    # ارجع للعربية إن لم تتوفر اللغة، ثم للمفتاح نفسه إن لم تتوفر الترجمة
    lang_map = TRANSLATIONS.get(lang, TRANSLATIONS['ar'])
    text = lang_map.get(key)
    if text is None:
        text = TRANSLATIONS['ar'].get(key, key)

    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            # وسيط ناقص أو قالب تنسيق غير صالح → أعد النص كما هو بدل الانهيار
            return text

    return text

def get_available_languages():
    """Get list of available language codes"""
    return list(TRANSLATIONS.keys())

# -*- coding: utf-8 -*-
"""
بناء وصف الوسائط - Media Caption
=================================
منطق نقيّ لعرض الوسائط: تنظيف العنوان، أسماء الدول، سطرا تحليل المصدر،
وبناء الوصف الموحّد. لا يعتمد على pyrogram ولا قاعدة البيانات — فيمكن
اختباره مباشرةً (بخلاف بقيّة bot.py الذي يتطلّب pyrogram للاستيراد).
"""

from datetime import datetime, timezone

from url_utils import _platform_of



_PLATFORM_TITLE_LABELS = {
    'instagram': 'Instagram', 'tiktok': 'TikTok', 'twitter': 'Twitter/X',
    'facebook': 'Facebook', 'youtube': 'YouTube', 'snapchat': 'Snapchat',
    'reddit': 'Reddit', 'pinterest': 'Pinterest', 'threads': 'Threads',
}


def _looks_like_media_id(title: str) -> bool:
    """هل العنوان معرّف CDN/هاش قبيح لا اسم مقروء؟ (كلمة واحدة طويلة تخلط حروفاً
    وأرقاماً بلا مسافات — مثل اسم ملف إنستغرام عبر المرآة AQM4FbWDo4mvcl...)."""
    s = (title or '').strip()
    if not s or ' ' in s:
        return False  # فارغ أو فيه مسافات (كلمات مقروءة) → ليس معرّفاً
    # النقطة تدخل في أسماء ملفات سناب (RG3vywiIqsKhqon9qFsTQ.1034) فنُسقطها
    # مثل الشرطات وإلا فشل فحص isalnum وظهر المعرّف عنواناً
    core = s.replace('_', '').replace('-', '').replace('.', '')
    return (len(s) >= 24 and core.isalnum()
            and any(c.isalpha() for c in core)
            and any(c.isdigit() for c in core))


def _clean_media_title(raw_title, url):
    """عنوان عرض ودود موحّد بين المنصات: يُبقي العناوين المقروءة كما هي، لكن
    يستبدل العناوين الفارغة أو معرّفات CDN القبيحة (شائعة لإنستغرام عبر المرآة)
    باسم منصة نظيف مثل 'Instagram Video' — تماماً كما تظهر تيك توك/تويتر."""
    title = (raw_title or '').strip()
    if title and not _looks_like_media_id(title):
        return title
    label = _PLATFORM_TITLE_LABELS.get(_platform_of(url))
    return f"{label} Video" if label else 'فيديو'


# أسماء الدول الشائعة بالعربية + علمها (رمز ISO-3166 alpha-2 من تيك توك).
# ما لا يرد هنا يُعرض برمزه كما هو — أفضل من إخفائه.
_COUNTRY_AR = {
    'SA': ('السعودية', '🇸🇦'), 'AE': ('الإمارات', '🇦🇪'), 'EG': ('مصر', '🇪🇬'),
    'SY': ('سوريا', '🇸🇾'), 'IQ': ('العراق', '🇮🇶'), 'JO': ('الأردن', '🇯🇴'),
    'KW': ('الكويت', '🇰🇼'), 'QA': ('قطر', '🇶🇦'), 'BH': ('البحرين', '🇧🇭'),
    'OM': ('عُمان', '🇴🇲'), 'YE': ('اليمن', '🇾🇪'), 'LB': ('لبنان', '🇱🇧'),
    'PS': ('فلسطين', '🇵🇸'), 'MA': ('المغرب', '🇲🇦'), 'DZ': ('الجزائر', '🇩🇿'),
    'TN': ('تونس', '🇹🇳'), 'LY': ('ليبيا', '🇱🇾'), 'SD': ('السودان', '🇸🇩'),
    'MR': ('موريتانيا', '🇲🇷'), 'SO': ('الصومال', '🇸🇴'), 'DJ': ('جيبوتي', '🇩🇯'),
    'KM': ('جزر القمر', '🇰🇲'),
    'DE': ('ألمانيا', '🇩🇪'), 'TR': ('تركيا', '🇹🇷'), 'US': ('أمريكا', '🇺🇸'),
    'GB': ('بريطانيا', '🇬🇧'), 'FR': ('فرنسا', '🇫🇷'), 'NL': ('هولندا', '🇳🇱'),
    'SE': ('السويد', '🇸🇪'), 'NO': ('النرويج', '🇳🇴'), 'DK': ('الدنمارك', '🇩🇰'),
    'FI': ('فنلندا', '🇫🇮'), 'BE': ('بلجيكا', '🇧🇪'), 'AT': ('النمسا', '🇦🇹'),
    'CH': ('سويسرا', '🇨🇭'), 'PL': ('بولندا', '🇵🇱'), 'RO': ('رومانيا', '🇷🇴'),
    'GR': ('اليونان', '🇬🇷'), 'PT': ('البرتغال', '🇵🇹'), 'IE': ('أيرلندا', '🇮🇪'),
    'RU': ('روسيا', '🇷🇺'), 'UA': ('أوكرانيا', '🇺🇦'),
    'CA': ('كندا', '🇨🇦'), 'AU': ('أستراليا', '🇦🇺'), 'NZ': ('نيوزيلندا', '🇳🇿'),
    'MX': ('المكسيك', '🇲🇽'), 'BR': ('البرازيل', '🇧🇷'), 'AR': ('الأرجنتين', '🇦🇷'),
    'CL': ('تشيلي', '🇨🇱'), 'CO': ('كولومبيا', '🇨🇴'), 'PE': ('بيرو', '🇵🇪'),
    'VE': ('فنزويلا', '🇻🇪'), 'EC': ('الإكوادور', '🇪🇨'), 'DO': ('الدومينيكان', '🇩🇴'),
    'IN': ('الهند', '🇮🇳'), 'PK': ('باكستان', '🇵🇰'), 'BD': ('بنغلاديش', '🇧🇩'),
    'ID': ('إندونيسيا', '🇮🇩'), 'MY': ('ماليزيا', '🇲🇾'), 'SG': ('سنغافورة', '🇸🇬'),
    'PH': ('الفلبين', '🇵🇭'), 'TH': ('تايلاند', '🇹🇭'), 'VN': ('فيتنام', '🇻🇳'),
    'JP': ('اليابان', '🇯🇵'), 'KR': ('كوريا الجنوبية', '🇰🇷'), 'CN': ('الصين', '🇨🇳'),
    'ES': ('إسبانيا', '🇪🇸'), 'IT': ('إيطاليا', '🇮🇹'), 'IR': ('إيران', '🇮🇷'),
    'AF': ('أفغانستان', '🇦🇫'), 'AZ': ('أذربيجان', '🇦🇿'), 'KZ': ('كازاخستان', '🇰🇿'),
    'NG': ('نيجيريا', '🇳🇬'), 'KE': ('كينيا', '🇰🇪'), 'ET': ('إثيوبيا', '🇪🇹'),
    'ZA': ('جنوب أفريقيا', '🇿🇦'), 'IL': ('إسرائيل', '🇮🇱'),
}

def _country_label(code):
    """«ألمانيا 🇩🇪» من رمز الدولة، أو الرمز كما هو إن كان غير معروف."""
    code = str(code or '').strip().upper()
    if not code:
        return None
    name, flag = _COUNTRY_AR.get(code, (code, '🌍'))
    return f"{name} {flag}"


def _build_source_lines(info):
    """سطرا تحليل المصدر لوصف الرفع (تيك توك)، أو [] إن لا بيانات.

    مقصوران على ما هو مؤكَّد من حقول تيك توك الصريحة: بلد نشر المقطع، وتاريخ
    إنشاء الحساب. (لا نعرض بلد الحساب: فحصٌ على ١٢ مساراً — بِتّات المعرّف
    وsecUid ومسارات التخزين على ٢٥ حساباً — أثبت أن تيك توك لا ينشره، وأن كل
    مؤشّر بديل ينهار على حساب معروف البلد.)

    ملاحظتان تصحيحيّتان:
    • التاريخ يُغلَّف بعلامة LTR لأن «2023-03-29» ينقلب بصرياً في السياق
      العربي فيُقرأ «29-03-2023» — أي يوماً وشهراً معكوسين.
    • لا نعرض مركز البيانات إطلاقاً: alisg هو المركز الافتراضي لتيك توك خارج
      أوروبا وأمريكا فلا يدلّ على بلد صاحب الحساب، و«أوروبا» وحدها مبهمة —
      وحقل created_in يعطي الدولة بعينها فأغنى عنه."""
    a = (info or {}).get('_source_analysis') or {}
    if not a:
        return []
    lines = []
    # created_in حقل تيك توك الصريح لبلد إنشاء المقطع — أدقّ من region في
    # المرآة، ويعطي الدولة بعينها فيغني عن أي ذكر مبهم لمنطقة كأوروبا
    where = _country_label(a.get('created_in') or a.get('video_region'))
    if where:
        lines.append(f"🌍 نُشر من: {where}")
    created = a.get('account_created')
    if created:
        # ‎ يمنع انقلاب التاريخ في العرض العربي
        stamp = f"‎{created:%Y-%m-%d}‎"
        try:
            from datetime import datetime, timezone
            years = (datetime.now(timezone.utc) - created).days / 365.25
            age = (f" (قبل {years:.1f} سنة)" if years >= 1
                   else f" (قبل {(datetime.now(timezone.utc) - created).days} يوماً)")
        except Exception:
            age = ''
        lines.append(f"📅 الحساب أُنشئ: {stamp}{age}")
    return lines


def _build_media_caption(title, file_size_mb, duration, user_name,
                         bot_username=None, stats=None, source_lines=None):
    """وصف الوسائط الموحّد: العنوان قابل للنسخ (monospace) + الحجم والمدة +
    يوزر البوت (يبقى مع الفيديو عند إعادة إرساله).

    stats: سطر تفاعلات المنشور (مثل «❤️ 425  💬 113») للمنصات التي تتيحه —
    لقطة وقت التحميل، فلا يُحفظ في الكاش كي لا يُعاد إرسال أرقام قديمة."""
    safe_title = (title or 'فيديو').replace('`', "'")[:300]
    dur_line = f"⏱️ {int(duration)//60}:{int(duration)%60:02d}\n" if duration else ""
    stats_line = f"{str(stats).strip()}\n" if stats else ""
    src_line = ''.join(f"{ln}\n" for ln in (source_lines or []))
    promo = f"\n\n📥 @{bot_username}" if bot_username else ""
    return (
        f"🎬 `{safe_title}`\n\n"
        f"📊 {file_size_mb:.1f} MB\n"
        f"{dur_line}"
        f"{stats_line}"
        f"{src_line}"
        f"👤 {user_name}"
        f"{promo}"
    )

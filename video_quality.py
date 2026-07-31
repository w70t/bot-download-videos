# -*- coding: utf-8 -*-
"""
اختيار جودة التحميل - Download Quality Selection
================================================
مُحدِّدات صيغ yt-dlp لكل مستوى جودة، ولوحة أزرار الجودة الخاصة بالأدمن.

لماذا وحدة مستقلة؟ لأن bot.py يتطلّب pyrogram واتصالاً بتيليجرام لاستيراده،
فلا يمكن اختبار منطق الجودة داخله. هنا منطق نقيّ بلا اعتماديات — يُختبر مباشرةً.

خلاصة السياسة:
- العضو العادي: زرّا «فيديو / صوت» فقط، والفيديو محدود بـ 1080p (best).
- الأدمن وحده: أزرار جودة كاملة، ومنها «أعلى جودة» (max) بلا أي سقف دقة —
  4K/8K وأي ترميز (VP9/AV1) إن كان هو الأعلى دقةً.
"""

# رموز الجودة (تُستخدم أيضاً مفتاحاً في كاش الوسائط، فلا تُغيَّر قيمها)
MAX_QUALITY = 'max'          # أعلى جودة متاحة بلا سقف — للأدمن وحده
DEFAULT_QUALITY = 'best'     # 1080p — الافتراضي لكل الأعضاء
AUDIO_QUALITY = 'audio'

# رموز لا تُتاح إلا للأدمن. أي طلب بها من غير الأدمن يُخفَّض إلى DEFAULT_QUALITY.
# ملاحظة: بقية الرموز (medium/480/360) ليست حكراً — إنها أدنى من السقف المجاني
# أصلاً، وقد تكون محفوظة في سجلّ أعضاء قدامى فيُعاد التحميل بها من السجل.
ADMIN_ONLY_QUALITIES = frozenset({MAX_QUALITY})

# صفوف أزرار الجودة كما يراها الأدمن (كل صف = مجموعة أزرار في سطر)
ADMIN_QUALITY_ROWS = (
    (MAX_QUALITY,),
    (DEFAULT_QUALITY, 'medium'),
    ('480', '360'),
    (AUDIO_QUALITY,),
)

# مفتاح الترجمة لنصّ زرّ كل جودة (يُقرأ عبر translations.t)
QUALITY_LABEL_KEYS = {
    MAX_QUALITY: 'quality_max',
    DEFAULT_QUALITY: 'quality_best',
    'medium': 'quality_medium',
    '480': 'quality_480',
    '360': 'quality_360',
    AUDIO_QUALITY: 'quality_audio',
}

# وصف مختصر محايد لغوياً يظهر في سجلّ التحميلات
QUALITY_DISPLAY = {
    MAX_QUALITY: 'MAX',
    DEFAULT_QUALITY: '1080p',
    'medium': '720p',
    '480': '480p',
    '360': '360p',
    AUDIO_QUALITY: 'MP3',
}


def _capped_chain(height):
    """سلسلة صيغ محدودة بدقّة معيّنة تُفضّل H.264 + AAC.

    نُفضّل ترميز H.264 لأنه متوافق 100% مع مشغّل تلجرام؛ والمنصات ذات الصيغ
    المدمجة (تيك توك) تُصدّر الترميز باسم "h264" لا "avc1" فنضيف فرعاً صريحاً
    لها قبل best العام (وإلا اختار H.265 الأعلى بت-ريت ⇒ فيديو بلا صوت).
    السلسلة تنازلية لضمان نجاح التحميل دائماً.
    """
    return (
        f'bestvideo[height<={height}][vcodec^=avc1]+bestaudio[ext=m4a]/'
        f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/'
        f"best[height<={height}][vcodec~='^(avc1|h264)']/"
        f'best[height<={height}][ext=mp4]/best[height<={height}]/best'
    )


QUALITY_FORMATS = {
    # 🏆 أعلى جودة: بلا أي سقف دقة وبلا تقييد ترميز — وإلا لن تُختار 1440p/4K
    #    إطلاقاً لأن المنصات (يوتيوب خاصةً) لا توفّر فوق 1080p إلا بـ VP9/AV1.
    #    المفاضلة تتكفّل بها format_sort أدناه.
    MAX_QUALITY: 'bestvideo*+bestaudio/best',
    DEFAULT_QUALITY: _capped_chain(1080),
    'medium': _capped_chain(720),
    '480': _capped_chain(480),
    '360': _capped_chain(360),
    AUDIO_QUALITY: 'bestaudio/best',  # أفضل جودة صوت (يُحوَّل لاحقاً إلى MP3)
}

# ترتيب المفاضلة لأعلى جودة: الدقّة أولاً ثم معدّل الإطارات — فتفوز 4K حتماً
# على 1080p مهما كان ترميزها. وعند تساوي الدقّة والإطارات يُفضَّل H.264 (أوسع
# توافقاً مع تلجرام) ثم البت-ريت الأعلى.
# ملاحظة: نزول VP9/AV1 ليس مشكلة توافق — finalize_video يعيد ترميزه إلى
# H.264 قبل الرفع (لكنه يستهلك وقت معالجة أطول كلما زادت الدقّة).
MAX_FORMAT_SORT = ('res', 'fps', 'vcodec:h264', 'br')


def normalize_quality(quality, admin=False):
    """يرجع رمز الجودة الفعلي المسموح لهذا المستخدم.

    نقطة الفرض الوحيدة: أي جودة محصورة بالأدمن تُخفَّض إلى الافتراضي لغيره،
    والرمز المجهول يعود للافتراضي. تُستدعى قبل فحص الكاش حتى لا يختلط ملف
    الأدمن عالي الدقّة بمفتاح كاش العضو العادي.
    """
    q = (quality or '').strip() or DEFAULT_QUALITY
    if q in ADMIN_ONLY_QUALITIES and not admin:
        return DEFAULT_QUALITY
    if q not in QUALITY_FORMATS:
        return DEFAULT_QUALITY
    return q


def format_selector(quality):
    """مُحدِّد صيغة yt-dlp (قيمة الخيار format) لرمز الجودة."""
    return QUALITY_FORMATS.get(quality, QUALITY_FORMATS[DEFAULT_QUALITY])


def format_sort(quality):
    """قائمة format_sort لـ yt-dlp، أو None حين لا حاجة لترتيب مخصّص."""
    return list(MAX_FORMAT_SORT) if quality == MAX_QUALITY else None


def quality_display(quality, kind=None):
    """وصف الجودة كما يظهر في سجلّ التحميلات."""
    if kind == 'audio':
        return QUALITY_DISPLAY[AUDIO_QUALITY]
    return QUALITY_DISPLAY.get(quality, quality or '')


def all_cache_qualities():
    """كل رموز الجودة التي قد تحمل نسخة في الكاش (لمسح رابط من الكاش)."""
    return tuple(QUALITY_FORMATS)

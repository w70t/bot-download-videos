# -*- coding: utf-8 -*-
"""
حدود رفع الملفات - Upload Size Limits
=====================================
سقف حجم الملف الذي يقبله تلجرام، ومتى نحاول تصغير الملف بدل رفضه.

⚠️ السقف صلب ولا يُرفع برقم في الكود: بايروجرام يرفض أي ملف فوق 2000
ميبي‑بايت *قبل* بدء الرفع أصلاً — راجع `save_file`:

    file_size_limit_mib = 4000 if self.me.is_premium else 2000

والبوت ليس حساب بريميوم أبداً، فالرقم الفعّال 2000 دائماً. رفع الرقم عندنا
لا يزيد ما يقبله تلجرام، إنما يستبدل رسالة واضحة بانهيار ValueError.

الذي *يمكن* رفعه هو ما يسع تحت السقف: مقاطع 4K تنزل بترميز VP9/AV1 بحجم
ضخم، وتجهيزها لتلجرام (finalize_video) يعيد ترميزها إلى H.264 فيتقلّص الملف
كثيراً — فمقطع يُرفض بحجمه الخام قد يسع بعد التجهيز. لذا نجرّب التجهيز قبل
الرفض، **للأدمن وحده**: العضو العادي يبقى على السلوك القديم (رفض فوري) حتى
لا يُثقل جهاز التشغيل بإعادة ترميز 4K لكل من يرسل رابطاً ضخماً.
"""

# سقف بايروجرام الصلب لحساب غير بريميوم (ميبي‑بايت)
TELEGRAM_BOT_UPLOAD_LIMIT_MB = 2000


def upload_limit_mb(limit_mb=None):
    """السقف الفعّال بالميبي‑بايت، مقصوصاً دائماً على سقف تلجرام الصلب.

    أي قيمة غير صالحة أو أعلى من السقف تعود إلى السقف نفسه — فلا يَعِد البوت
    بما لا يستطيع رفعه.
    """
    if limit_mb is None:
        return TELEGRAM_BOT_UPLOAD_LIMIT_MB
    try:
        value = float(limit_mb)
    except (TypeError, ValueError):
        return TELEGRAM_BOT_UPLOAD_LIMIT_MB
    # ‏`not (value > 0)` لا `value <= 0`: يلتقط NaN أيضاً — وإلا مرّ NaN إلى
    # min() فصار السقف NaN وقورن كل حجم به بـ False ⇒ رفض كل الملفات.
    if not (value > 0):
        return TELEGRAM_BOT_UPLOAD_LIMIT_MB
    return min(value, TELEGRAM_BOT_UPLOAD_LIMIT_MB)


def fits_upload_limit(size_mb, limit_mb=None):
    """هل يسع هذا الحجم تحت السقف؟"""
    return size_mb <= upload_limit_mb(limit_mb)


def should_shrink_before_reject(size_mb, admin=False, is_audio=False,
                                limit_mb=None):
    """هل نجرّب تجهيز الفيديو (إعادة ترميزه إلى H.264) قبل رفضه لكبر حجمه؟

    شرطها: فيديو (لا صوت) تجاوز السقف، وصاحب الطلب أدمن. الصوت لا يُجهَّز
    بـ finalize_video أصلاً، والعضو العادي يبقى على الرفض الفوري كما كان.
    """
    if not admin or is_audio:
        return False
    return not fits_upload_limit(size_mb, limit_mb)

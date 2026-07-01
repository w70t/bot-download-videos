#!/bin/bash
# =============================================================
# تحديث yt-dlp تلقائياً (يُشغَّل من cron)
# - يحدّث yt-dlp داخل بيئة البوت الافتراضية (بصلاحيات مالك المجلد)
# - يعيد تشغيل البوت فقط إذا تغيّر الإصدار (لا يقطع تحميلات جارية بلا داعٍ)
# - يرسل إشعار تلجرام للأدمن بالنتيجة (نجاح/فشل)
#
# الاستخدام في جدولة root (مثال كل 6 ساعات):
#   0 */6 * * * /home/<user>/bot7/update_ytdlp.sh >> /home/<user>/bot7/ytdlp_update.log 2>&1
#
# متغيرات اختيارية (تُضبط قبل السطر في cron أو تُصدَّر):
#   BOT_SERVICE=bot7        اسم خدمة systemd (الافتراضي bot7)
#   NOTIFY_NO_CHANGE=1      أرسل إشعاراً حتى عند عدم وجود تحديث (الافتراضي 0 = صامت)
# =============================================================
set -u

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIP="$BOT_DIR/venv/bin/pip"
SERVICE="${BOT_SERVICE:-bot7}"
NOTIFY_NO_CHANGE="${NOTIFY_NO_CHANGE:-0}"
OWNER="$(stat -c %U "$BOT_DIR")"

# قراءة توكن البوت ومعرّف الأدمن من .env لإرسال الإشعار
_env() { grep -E "^$1=" "$BOT_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d ' \r'; }
BOT_TOKEN="$(_env BOT_TOKEN)"
ADMIN_ID="$(_env ADMIN_ID)"

notify() {
    [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_ID" ] || return 0
    curl -s -m 20 "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d chat_id="${ADMIN_ID}" --data-urlencode text="$1" >/dev/null || true
}

# نفّذ pip بصلاحيات مالك المجلد حتى لا تتخرب ملكية ملفات venv عند التشغيل كـroot
run_pip() {
    if [ "$(id -un)" = "$OWNER" ]; then
        "$PIP" "$@"
    else
        runuser -u "$OWNER" -- "$PIP" "$@"
    fi
}

ver() { run_pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}'; }

echo "===== $(date '+%F %T') فحص تحديث yt-dlp ====="
OLD="$(ver)"

if OUT="$(run_pip install -U yt-dlp 2>&1)"; then
    NEW="$(ver)"
    if [ -n "$NEW" ] && [ "$OLD" != "$NEW" ]; then
        echo "تم التحديث: ${OLD:-?} -> ${NEW} — إعادة تشغيل ${SERVICE}"
        if systemctl restart "$SERVICE"; then
            notify "✅ تحديث تلقائي: yt-dlp
${OLD:-?} ← ${NEW}
♻️ تمت إعادة تشغيل البوت بنجاح"
        else
            notify "⚠️ تحدّث yt-dlp إلى ${NEW} لكن فشلت إعادة تشغيل ${SERVICE} — افحص الخادم!"
        fi
    else
        echo "لا جديد (الإصدار ${OLD:-?})"
        if [ "$NOTIFY_NO_CHANGE" = "1" ]; then
            notify "ℹ️ فحص تحديث yt-dlp: لا جديد (الإصدار ${OLD:-?})"
        fi
    fi
else
    echo "فشل التحديث:"
    echo "$OUT" | tail -5
    notify "❌ فشل التحديث التلقائي لـ yt-dlp:
$(echo "$OUT" | tail -3)"
fi

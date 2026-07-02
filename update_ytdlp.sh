#!/bin/bash
# =============================================================
# تحديث مكتبات التحميل تلقائياً: yt-dlp + gallery-dl + curl_cffi
# (يُشغَّل من cron)
# - يكتشف بيئة بايثون التي يعمل بها البوت فعلياً (من العملية الحيّة عبر
#   systemd) فيحدّث المكان الصحيح سواء كان venv أو بايثون النظام
# - يتجاوز منع Debian لتحديث بايثون النظام (PEP 668) عند الحاجة لأن
#   المستهدفة هي بيئة تشغيل البوت الفعلية نفسها
# - يعيد تشغيل البوت فقط إذا تغيّر إصدار مكتبة (لا يقطع تحميلات جارية بلا داعٍ)
# - يرسل إشعار تلجرام للأدمن بالنتيجة (نجاح/فشل) مع قائمة ما تغيّر
#
# الاستخدام في جدولة root (مثال كل 6 ساعات):
#   0 */6 * * * /home/<user>/bot7/update_ytdlp.sh >> /home/<user>/bot7/ytdlp_update.log 2>&1
#
# متغيرات اختيارية (تُضبط قبل السطر في cron أو تُصدَّر):
#   BOT_SERVICE=bot7        اسم خدمة systemd (الافتراضي bot7)
#   NOTIFY_NO_CHANGE=1      أرسل إشعاراً حتى عند عدم وجود تحديث (الافتراضي 0 = صامت)
#   PKGS="yt-dlp ..."       قائمة الحزم (الافتراضي yt-dlp gallery-dl curl_cffi)
# =============================================================
set -u

# cron لا يضع مجلدات sbin في PATH فلا يجد runuser/systemctl أحياناً
export PATH="/usr/local/sbin:/usr/sbin:/sbin:$PATH"

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE="${BOT_SERVICE:-bot7}"
NOTIFY_NO_CHANGE="${NOTIFY_NO_CHANGE:-0}"

# بيئة بايثون الفعلية للبوت: من العملية الحيّة أولاً، وإلا venv المشروع، وإلا python3
MAIN_PID="$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null | tr -d ' ')"
MAIN_PID="${MAIN_PID:-0}"
if [ "$MAIN_PID" != "0" ] && [ -n "$MAIN_PID" ] && [ -e "/proc/$MAIN_PID/exe" ]; then
    PY="$(readlink -f "/proc/$MAIN_PID/exe")"
    RUN_USER="$(ps -o user= -p "$MAIN_PID" | tr -d ' ')"
elif [ -x "$BOT_DIR/venv/bin/python" ]; then
    PY="$BOT_DIR/venv/bin/python"
    RUN_USER="$(stat -c %U "$BOT_DIR")"
else
    PY="$(command -v python3)"
    RUN_USER="$(stat -c %U "$BOT_DIR")"
fi

# قراءة توكن البوت ومعرّف الأدمن من .env لإرسال الإشعار
_env() { grep -E "^$1=" "$BOT_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d ' \r'; }
BOT_TOKEN="$(_env BOT_TOKEN)"
ADMIN_ID="$(_env ADMIN_ID)"

notify() {
    [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_ID" ] || return 0
    curl -s -m 20 "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d chat_id="${ADMIN_ID}" --data-urlencode text="$1" >/dev/null || true
}

# نفّذ بايثون بهوية مستخدم البوت نفسه حتى يصل التحديث لنفس البيئة التي يقرأها
run_py() {
    if [ "$(id -un)" = "$RUN_USER" ]; then
        "$PY" "$@"
    elif command -v runuser >/dev/null 2>&1; then
        runuser -u "$RUN_USER" -- "$PY" "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo -u "$RUN_USER" "$PY" "$@"
    else
        "$PY" "$@"
    fi
}

PKGS="${PKGS:-yt-dlp gallery-dl curl_cffi}"

ver() { run_py -m pip show "$1" 2>/dev/null | awk '/^Version:/{print $2}'; }

pip_upgrade() {
    # shellcheck disable=SC2086
    OUT="$(run_py -m pip install -U $PKGS 2>&1)" && return 0
    # بايثون النظام في Debian يمنع pip افتراضياً (PEP 668) — تجاوز المنع
    if echo "$OUT" | grep -q 'externally-managed-environment'; then
        # shellcheck disable=SC2086
        OUT="$(run_py -m pip install -U $PKGS --break-system-packages 2>&1)" && return 0
    fi
    return 1
}

echo "===== $(date '+%F %T') فحص تحديث المكتبات [$PKGS] (python: $PY, user: $RUN_USER) ====="
declare -A OLDV
for p in $PKGS; do OLDV[$p]="$(ver "$p")"; done

if pip_upgrade; then
    CHANGES=""
    for p in $PKGS; do
        NEWP="$(ver "$p")"
        if [ -n "$NEWP" ] && [ "${OLDV[$p]}" != "$NEWP" ]; then
            CHANGES="${CHANGES}${p}: ${OLDV[$p]:-?} ← ${NEWP}
"
        fi
    done
    if [ -n "$CHANGES" ]; then
        echo "تم التحديث — إعادة تشغيل ${SERVICE}:"
        echo "$CHANGES"
        if systemctl restart "$SERVICE"; then
            notify "✅ تحديث تلقائي للمكتبات:
${CHANGES}♻️ تمت إعادة تشغيل البوت بنجاح"
        else
            notify "⚠️ تحدّثت المكتبات لكن فشلت إعادة تشغيل ${SERVICE} — افحص الخادم!
${CHANGES}"
        fi
    else
        echo "لا جديد (yt-dlp ${OLDV[yt-dlp]:-?})"
        if [ "$NOTIFY_NO_CHANGE" = "1" ]; then
            notify "ℹ️ فحص تحديث المكتبات: لا جديد (yt-dlp ${OLDV[yt-dlp]:-?})"
        fi
    fi
else
    echo "فشل التحديث:"
    echo "$OUT" | tail -5
    notify "❌ فشل التحديث التلقائي للمكتبات:
$(echo "$OUT" | tail -3)"
fi

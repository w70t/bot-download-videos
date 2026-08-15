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
# مهم: نقرأ المسار من cmdline (وليس /proc/PID/exe) لأن python داخل venv مجرد
# رابط رمزي لبايثون النظام — تتبّع الرابط يفقد سياق الـvenv فنحدّث بيئة خاطئة.
MAIN_PID="$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null | tr -d ' ')"
MAIN_PID="${MAIN_PID:-0}"
PY=""
if [ "$MAIN_PID" != "0" ] && [ -n "$MAIN_PID" ] && [ -r "/proc/$MAIN_PID/cmdline" ]; then
    ARG0="$(tr '\0' '\n' < "/proc/$MAIN_PID/cmdline" | head -1)"
    if [ -n "$ARG0" ] && [ -x "$ARG0" ]; then
        PY="$ARG0"
    elif [ -e "/proc/$MAIN_PID/exe" ]; then
        PY="$(readlink -f "/proc/$MAIN_PID/exe")"
    fi
    RUN_USER="$(ps -o user= -p "$MAIN_PID" | tr -d ' ')"
fi
if [ -z "$PY" ]; then
    if [ -x "$BOT_DIR/venv/bin/python" ]; then
        PY="$BOT_DIR/venv/bin/python"
    else
        PY="$(command -v python3)"
    fi
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
# yt-dlp 2026.07.04 يدعم curl_cffi حتى سلسلة 0.15.x. إبقاء القيد منفصلاً
# عن PKGS مهم: عناصر PKGS أسماء حزم صافية تُستخدم في pip show وتقارير الإصدارات،
# بينما هذا المتطلب خاص بعملية التثبيت ويمنع المحدث من جلب 0.16 غير المتوافق.
CURL_CFFI_REQUIREMENT="curl_cffi<0.16"
read -r -a PKG_ARGS <<< "$PKGS"
# القيد قد يخفّض إصدار curl_cffi حتى لو استُبعد اسمه من PKGS المخصّصة؛ أضفه
# لقائمة القياس أيضاً كي يُكتشف التغيير وتتم إعادة التشغيل ويظهر في الإشعار.
CURL_CFFI_REPORTED=0
for package in "${PKG_ARGS[@]}"; do
    if [ "$package" = "curl_cffi" ] || [ "$package" = "curl-cffi" ]; then
        CURL_CFFI_REPORTED=1
        break
    fi
done
if [ "$CURL_CFFI_REPORTED" = "0" ]; then
    PKG_ARGS+=("curl_cffi")
fi
INSTALL_ARGS=()
for package in "${PKG_ARGS[@]}"; do
    if [ "$package" = "yt-dlp" ]; then
        # extra الافتراضي يجلب yt-dlp-ejs المطابق لتحديات YouTube JavaScript.
        INSTALL_ARGS+=("yt-dlp[default]")
    elif [ "$package" = "curl_cffi" ] || [ "$package" = "curl-cffi" ]; then
        INSTALL_ARGS+=("$CURL_CFFI_REQUIREMENT")
    else
        INSTALL_ARGS+=("$package")
    fi
done

ver() { run_py -m pip show "$1" 2>/dev/null | awk '/^Version:/{print $2}'; }

pip_upgrade() {
    OUT="$(run_py -m pip install -U "${INSTALL_ARGS[@]}" 2>&1)" && return 0
    # بايثون النظام في Debian يمنع pip افتراضياً (PEP 668) — تجاوز المنع
    if echo "$OUT" | grep -q 'externally-managed-environment'; then
        OUT="$(run_py -m pip install -U "${INSTALL_ARGS[@]}" --break-system-packages 2>&1)" && return 0
    fi
    return 1
}

echo "===== $(date '+%F %T') فحص تحديث المكتبات [$PKGS] (python: $PY, user: $RUN_USER) ====="
declare -A OLDV
for p in "${PKG_ARGS[@]}"; do OLDV[$p]="$(ver "$p")"; done

if pip_upgrade; then
    CHANGES=""
    for p in "${PKG_ARGS[@]}"; do
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

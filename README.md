
# 🤖 بوت تحميل الفيديوهات من تيليجرام

[![GitHub](https://img.shields.io/badge/GitHub-telegram--downloader--bot-blue?logo=github)](https://github.com/YOUR_USERNAME/telegram-downloader-bot)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-12%2B-blue?logo=postgresql)](https://www.postgresql.org/)

بوت متطور لتحميل الفيديوهات والصور من مختلف المنصات (YouTube, Facebook, Instagram, TikTok, Twitter/X, Threads وغيرها) ورفعها على تيليجرام مع دعم ملفات حتى 2GB، وكاش ذكي، ونظام إدارة أعضاء متكامل.

---

## 📚 أدلة التثبيت والاستخدام

- **⚡ [دليل البدء السريع](QUICK_START.md)** - ابدأ في 5 دقائق!
- **📖 [دليل التثبيت الكامل](INSTALLATION_GUIDE.md)** - شرح مفصل خطوة بخطوة
- **🔧 [المشاكل الشائعة وحلولها](#️-المشاكل-الشائعة-وحلولها)** - حلول مشاكل PostgreSQL والتشغيل

> **⚠️ مهم جداً:** راجع قسم [المشاكل الشائعة](#️-المشاكل-الشائعة-وحلولها) و[دليل التثبيت الكامل](INSTALLATION_GUIDE.md) لتجنب مشكلة مصادقة PostgreSQL الشائعة!

---

## ✨ المميزات الرئيسية

### 📥 التحميل والوسائط
- ✅ **تحميل من منصات متعددة**: YouTube, Facebook, Instagram, TikTok, Twitter/X, Threads, Reddit, Pinterest, Snapchat وغيرها
- ✅ **تحميل الصور** 🖼️: صور إنستغرام (كاروسيل/ألبوم) وسلايدشو تيك توك تُرسَل كألبوم تلقائياً عبر `gallery-dl`
- ✅ **رفع ملفات كبيرة**: يدعم رفع ملفات حتى **2GB**، وفيديوهات طويلة (3 ساعات+)
- ✅ **جودات متعددة**: جودة عالية، متوسطة، أو صوت فقط (MP3)
- ✅ **معالجة الفيديو**: تحويل تلقائي إلى H.264/AAC مع `faststart` + مصغّرة (thumbnail) لمنع تجمّد الصورة عبر `ffmpeg`
- ✅ **كاش ذكي** ⚡: أي رابط (فيديو أو صور) حُمِّل سابقاً يُعاد إرساله فوراً من معرّف الملف (file_id) **بلا إعادة تحميل أو رفع** — يخفّف الضغط على الجهاز

### 👥 إدارة الأعضاء
- ✅ **استبيان إجباري**: يُسأل العضو عن **الجنس** (رجل/امرأة) + أسئلة أدمن قابلة للتخصيص قبل أول تحميل
- ✅ **نظام حظر متدرّج**: تحذير / حظر دائم مع شاشة **تعهّد** للعودة، وأزرار تحكّم للأدمن أسفل كل سجل
- ✅ **حظر الحسابات المصدر**: منع تحميل أي محتوى من حساب ناشر معيّن (`/blockacc`)
- ✅ **رفض المحتوى الإباحي/الحسّاس**: كشف تلقائي مع رسالة واضحة للمحتوى المقيّد بالعمر
- ✅ **حدود يومية + مكافآت**: حدّ تحميل يومي لغير المشتركين مع رصيد إضافي

### 🎁 التفاعل والنمو
- ✅ **نظام إحالات**: "ادعُ أصدقاءك" مع مكافأة تحميلات لكل دعوة ناجحة
- ✅ **سجل التحميلات**: زر "تحميلاتي" يعرض للعضو تاريخ تحميلاته
- ✅ **تذكير الأعضاء الخاملين**: رسالة عودة تلقائية بعد فترة خمول

### 🛠️ التشغيل والإدارة
- ✅ **قنوات سجلات متخصّصة**: سجل التحميلات (مع تفاصيل العضو والجنس)، سجل الأخطاء، الأعضاء الجدد، الاستبيان، والنسخ الاحتياطي
- ✅ **نظام اشتراكات**: إدارة اشتراكات المستخدمين مع PostgreSQL
- ✅ **نظام طوابير**: معالجة التحميلات بشكل منظّم لتجنّب الازدحام
- ✅ **دعم متعدد اللغات**: عربي وإنجليزي
- ✅ **نسخ احتياطي تلقائي**: نسخ دوري لقاعدة البيانات يُرسَل لقناة مخصّصة

---

## 📦 التثبيت السريع

### 1. المتطلبات الأساسية

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git ffmpeg postgresql postgresql-contrib
```

### 2. تحميل المشروع

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/telegram-downloader-bot.git
cd telegram-downloader-bot
```

> **👉 استبدل `YOUR_USERNAME`** باسم المستخدم الفعلي على GitHub

### 3. إعداد البيئة والمكتبات

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. إعداد PostgreSQL ⚠️ **خطوة حاسمة!**

> **🚨 تحذير:** هذه الخطوة سببت مشاكل للكثيرين! اتبعها بدقة.

#### 4.1 - تثبيت PostgreSQL

```bash
# تحديث قائمة الحزم
sudo apt update
```

```bash
# تثبيت PostgreSQL وأدواته الإضافية
sudo apt install -y postgresql postgresql-contrib
```

**ماذا سيحدث؟** 
- سيتم تثبيت قاعدة بيانات PostgreSQL على جهازك
- قد يستغرق الأمر 1-3 دقائق

---

#### 4.2 - تفعيل وتشغيل خدمة PostgreSQL

```bash
# تشغيل خدمة PostgreSQL
sudo systemctl start postgresql
```

```bash
# تفعيل التشغيل التلقائي عند بدء النظام
sudo systemctl enable postgresql
```

```bash
# التحقق من حالة الخدمة
sudo systemctl status postgresql
```

**النتيجة المتوقعة:**
- ستظهر رسالة: `● postgresql.service - PostgreSQL RDBMS`
- وحالة: `Active: active (running)`
- اضغط `q` للخروج من عرض الحالة

---

#### 4.3 - إنشاء مستخدم قاعدة البيانات

> **🔑 مهم:** استبدل `YOUR_STRONG_PASSWORD` بكلمة مرور قوية من اختيارك!

```bash
# إنشاء مستخدم جديد مع كلمة مرور
sudo -u postgres psql -c "CREATE USER bot_user WITH PASSWORD 'YOUR_STRONG_PASSWORD';"
```

**مثال:**
```bash
sudo -u postgres psql -c "CREATE USER bot_user WITH PASSWORD 'MyBotPass2024!';"
```

**النتيجة المتوقعة:**
```
CREATE ROLE
```

**⚠️ إذا ظهر خطأ "role already exists":**
```bash
# تحديث كلمة المرور للمستخدم الموجود
sudo -u postgres psql -c "ALTER USER bot_user WITH PASSWORD 'YOUR_STRONG_PASSWORD';"
```

---

#### 4.4 - إنشاء قاعدة البيانات

```bash
# إنشاء قاعدة بيانات للبوت
sudo -u postgres psql -c "CREATE DATABASE telegram_bot;"
```

**النتيجة المتوقعة:**
```
CREATE DATABASE
```

**⚠️ إذا ظهر خطأ "database already exists":**
- لا مشكلة، القاعدة موجودة مسبقاً ✅
- انتقل للخطوة التالية

---

#### 4.5 - منح الصلاحيات للمستخدم

```bash
# إعطاء المستخدم bot_user كامل الصلاحيات على قاعدة telegram_bot
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE telegram_bot TO bot_user;"
```

**النتيجة المتوقعة:**
```
GRANT
```

---

#### 4.6 - اختبار الاتصال بقاعدة البيانات (اختياري)

```bash
# الاتصال بقاعدة البيانات للتأكد من نجاح الإعداد
psql -U bot_user -h localhost -d telegram_bot
```

**سيطلب منك:** كلمة المرور التي أنشأتها في الخطوة 4.3
- أدخل كلمة المرور واضغط Enter

**النتيجة المتوقعة:**
```
telegram_bot=>
```

**للخروج:**
- اكتب `\q` واضغط Enter

---

**💡 مهم جداً:** 
- احفظ كلمة المرور! ستحتاجها في ملف `.env` في الخطوة التالية
- تأكد أن كلمة المرور في `.env` **مطابقة تماماً** لما استخدمته هنا

### 5. إنشاء ملف `.env`

```bash
cp env.example .env
nano .env
```

**املأ المعلومات التالية:**

```bash
# من @BotFather
BOT_TOKEN=YOUR_BOT_TOKEN

# من https://my.telegram.org/apps  
PYROGRAM_API_ID=YOUR_API_ID
PYROGRAM_API_HASH=YOUR_API_HASH

# من @userinfobot
ADMIN_ID=YOUR_TELEGRAM_ID

# PostgreSQL (نفس كلمة المرور من الخطوة 4!)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=telegram_bot
POSTGRES_USER=bot_user
POSTGRES_PASSWORD=YOUR_STRONG_PASSWORD

# قنوات اختيارية (اتركها فارغة إذا لم تحتاجها)
LOG_CHANNEL_ID=            # سجل التحميلات (فيديو/صور مع تفاصيل العضو والجنس)
ERROR_LOG_CHANNEL_ID=      # سجل الأخطاء
NEW_MEMBERS_CHANNEL_ID=    # إشعار الأعضاء الجدد
SURVEY_CHANNEL_ID=         # إجابات استبيان الأعضاء
BACKUP_CHANNEL_ID=         # النسخ الاحتياطي التلقائي لقاعدة البيانات

# إعدادات اختيارية إضافية
BINANCE_PAY_ID=            # لعرض زر دعم/دفع Binance (اتركه فارغاً لإخفائه)
SUPPORT_USERNAME=          # يوزر الدعم الذي يظهر للأعضاء
REFERRAL_BONUS=1           # عدد التحميلات الممنوحة لكل دعوة ناجحة
REFERRAL_MINUTES=5         # قيمة أولية فقط؛ تُدار لاحقاً من لوحة الأدمن (🎁 دقائق مكافأة الدعوة)
GALLERY_DL_MAX_IMAGES=30   # أقصى عدد صور تُحمَّل من منشور واحد
AUTO_BACKUP_HOURS=12       # فترة النسخ الاحتياطي التلقائي (بالساعات)
REMINDER_INACTIVE_DAYS=7   # عدد أيام الخمول قبل إرسال تذكير العودة
```

> 💡 القنوات كلها اختيارية؛ اترك أي متغيّر فارغاً لتعطيل ميزته دون أن يتأثّر البوت.

**احفظ:** `Ctrl+O` ثم `Enter` ثم `Ctrl+X`

### 6. إنشاء الجداول

```bash
source venv/bin/activate
python3 setup_postgres.py
```

**✅ يجب أن ترى:** `✅ تم إنشاء جميع الجداول بنجاح!`

### 7. تشغيل البوت

```bash
python3 bot.py
```

**✅ يجب أن ترى:**
```
============================================================
🤖 Telegram Video Downloader Bot (Standalone)
============================================================
✅ يرفع حتى 2GB
✅ تم إنشاء قاعدة بيانات الاشتراكات
Connected! Production DC2 - IPv4
```

---

## 🗂️ بنية المشروع

| الملف | الوظيفة |
|---|---|
| `bot.py` | نقطة التشغيل: عميل Pyrogram وجميع معالجات الأوامر والأزرار ومسار التحميل والرفع |
| `url_utils.py` | أدوات الروابط: حماية SSRF، مفاتيح الكاش، استخراج الروابط من النصوص، تحديد المنصة |
| `link_resolvers.py` | تحويل الروابط الخاصة: سناب سبوت لايت، وروابط الأغاني (Shazam/Apple Music/Spotify) لبحث يوتيوب |
| `content_filter.py` | فلتر المحتوى الإباحي وحظر الحسابات المصدر |
| `cookies_manager.py` | اختيار ملفات الكوكيز حسب المنصة والتحقق من صلاحيتها |
| `video_processing.py` | ffmpeg/ffprobe: توليد المصغّرات وتجهيز الفيديو لتلجرام (H.264/AAC + faststart) |
| `download_errors.py` | تصنيف أخطاء yt-dlp (DRM، حظر جغرافي، مشاكل كوكيز، محتوى مقيّد) |
| `queue_manager.py` | طوابير التحميل لكل مستخدم مع حد زمني بين الطلبات |
| `subscription_db.py` | طبقة PostgreSQL: الأعضاء والاشتراكات والإعدادات والكاش |
| `translations.py` | نصوص الواجهة (عربي/إنجليزي) |
| `pg_backup.py` | النسخ الاحتياطي لقاعدة البيانات |
| `tests/` | اختبارات الوحدات (pytest) للدوال النقيّة |

### 🧪 تشغيل الاختبارات

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -q
```

---

## 🎯 الحصول على المعلومات المطلوبة

### `BOT_TOKEN`
1. افتح Telegram → ابحث عن `@BotFather`
2. أرسل: `/newbot`
3. اتبع التعليمات وانسخ الـ Token

### `PYROGRAM_API_ID` و `PYROGRAM_API_HASH`
1. افتح: https://my.telegram.org/apps
2. سجل دخول برقم هاتفك
3. أنشئ تطبيق جديد
4. انسخ `api_id` و `api_hash`

### `ADMIN_ID`
1. افتح Telegram → ابحث عن `@userinfobot`
2. أرسل: `/start`
3. انسخ رقمك التعريفي

---

## 🔑 أوامر الأدمن

| الأمر | الوظيفة |
|-------|---------|
| `/start` | القائمة الرئيسية (وللأدمن تظهر لوحات التحكم) |
| `/dlstats` | إحصائيات التحميل العامة |
| `/realusers` | فحص فوري للأعضاء: يحذف من حظر البوت ويعرض العدد الحقيقي + الداخلين/الخارجين |
| `/history` | عرض سجل تحميلاتك |
| `/banned` | قائمة الأعضاء المحظورين (مع أزرار رفع الحظر) |
| `/unban <id>` | رفع الحظر عن عضو يدوياً |
| `/blockacc <حساب>` | حظر حساب ناشر (منع تحميل محتواه) |
| `/unblockacc <حساب>` | رفع الحظر عن حساب ناشر |
| `/blockedaccs` | عرض قائمة الحسابات المحظورة |
| `/cookies` | لوحة إدارة ملفات الـ Cookies للمنصات |
| `/backup` | إنشاء نسخة احتياطية فورية لقاعدة البيانات |

**لوحات تحكّم إضافية** (أزرار داخل تيليجرام للأدمن): البث الجماعي 📢، إدارة الاشتراك الإجباري وقنواته، إدارة أسئلة الاستبيان، ولوحة صحّة المنصات (تجميع الأخطاء حسب المنصة).

---

## ⚠️ المشاكل الشائعة وحلولها

### ❌ `password authentication failed for user "bot_user"`

**السبب:** كلمة المرور في `.env` لا تطابق PostgreSQL

**الحل:**
```bash
# حدّث كلمة المرور في PostgreSQL
sudo -u postgres psql -c "ALTER USER bot_user WITH PASSWORD 'NEW_PASSWORD';"

# حدّث .env بنفس الكلمة
nano .env
# غيّر: POSTGRES_PASSWORD=NEW_PASSWORD
```

📖 **للتفاصيل:** راجع [دليل التثبيت الكامل](INSTALLATION_GUIDE.md)

### ❌ `PEER_ID_INVALID` في السجلات

**السبب:** البوت يحاول الإرسال لقنوات غير موجودة

**الحل:** افتح `.env` واترك القنوات فارغة:
```bash
LOG_CHANNEL_ID=
ERROR_LOG_CHANNEL_ID=
NEW_MEMBERS_CHANNEL_ID=
```

### ❌ `ModuleNotFoundError`

**الحل:**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

---

## 🚀 التشغيل الدائم على Raspberry Pi (systemd)

هذا القسم يضمن أن البوت:
- ✅ **يشتغل تلقائياً عند إقلاع الجهاز** (حتى لو انقطعت الكهرباء ورجعت)
- ✅ **يعيد تشغيل نفسه تلقائياً** إذا انهار أو توقف لأي سبب
- ✅ **ينتظر الشبكة وقاعدة البيانات** قبل أن يبدأ (لا يفشل عند الإقلاع)

> 💡 في الأمثلة أدناه اسم الخدمة `bot7` والمستخدم `YOUR_USERNAME` ومجلد
> المشروع `~/bot7` — **عدّلها حسب جهازك**.

### 1. إنشاء ملف الخدمة

```bash
sudo nano /etc/systemd/system/bot7.service
```

**المحتوى:**

```ini
[Unit]
Description=Telegram Video Downloader Bot
# لا تبدأ إلا بعد جاهزية الشبكة وقاعدة البيانات
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/bot7
# يفضَّل التشغيل من البيئة الافتراضية (venv) حتى تنطبق الإصدارات
# المثبّتة في requirements.txt على البوت فعلياً
ExecStart=/home/YOUR_USERNAME/bot7/venv/bin/python bot.py
# إعادة تشغيل تلقائية عند أي انهيار أو توقف، بعد انتظار 10 ثوانٍ
Restart=always
RestartSec=10
# لا تستسلم مهما تكررت الأعطال (افتراضياً systemd يتوقف بعد 5 محاولات سريعة)
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
```

### 2. التفعيل (مرة واحدة فقط)

```bash
sudo systemctl daemon-reload      # اقرأ ملف الخدمة الجديد/المعدّل
sudo systemctl enable bot7        # ⬅️ التشغيل التلقائي عند كل إقلاع
sudo systemctl start bot7         # شغّله الآن
sudo systemctl status bot7        # تأكد أنه "active (running)"
```

> ⚠️ بدون `systemctl enable` البوت **لن يشتغل** بعد إعادة تشغيل الجهاز!
> تأكد أنه مفعّل: `systemctl is-enabled bot7` → يجب أن تطبع `enabled`.

### 3. أوامر التشغيل اليومية

| الأمر | الوظيفة |
|---|---|
| `sudo systemctl status bot7` | حالة البوت الآن |
| `sudo systemctl restart bot7` | إعادة تشغيل يدوية |
| `sudo systemctl stop bot7` | إيقاف مؤقت |
| `sudo systemctl start bot7` | تشغيل بعد الإيقاف |
| `journalctl -u bot7 -n 30 --no-pager` | آخر 30 سطراً من السجلات |
| `journalctl -u bot7 -f` | متابعة السجلات مباشرة (اخرج بـ Ctrl+C) |
| `systemctl is-enabled bot7` | هل التشغيل التلقائي عند الإقلاع مفعّل؟ |

### 4. اختبار أن كل شيء يعمل

```bash
# جرّب إعادة تشغيل الجهاز كاملاً
sudo reboot

# بعد أن يرجع الجهاز (دقيقة تقريباً) اتصل به وتأكد
sudo systemctl status bot7
```

إذا ظهر `active (running)` فالبوت رجع لوحده بنجاح ✅

---

## 🔄 التحديث التلقائي لـ yt-dlp

`yt-dlp` يحتاج تحديثاً دورياً لمواكبة تغييرات المنصات (يوتيوب/تيك توك...).
السكربت `update_ytdlp.sh` المرفق يتكفّل بذلك:

- يكتشف بيئة بايثون التي يعمل بها البوت **فعلياً** ويحدّثها
- يعيد تشغيل البوت **فقط إذا نزل إصدار جديد** (لا يقطع تحميلات جارية بلا داعٍ)
- يرسل **إشعار تلجرام للأدمن** بنتيجة كل تحديث (نجاح/فشل)

**التفعيل (فحص كل 6 ساعات):**

```bash
chmod +x ~/bot7/update_ytdlp.sh
( sudo crontab -l 2>/dev/null | grep -v 'yt-dlp' ; \
  echo '0 */6 * * * /home/YOUR_USERNAME/bot7/update_ytdlp.sh >> /home/YOUR_USERNAME/bot7/ytdlp_update.log 2>&1' \
) | sudo crontab -
sudo crontab -l   # للتأكد من الحفظ
```

**مراقبة سجل التحديثات:**

```bash
tail -20 ~/bot7/ytdlp_update.log
```

**تحديث فوري بدون انتظار:** من داخل البوت اضغط زر `🔄 تحديث yt-dlp`
في لوحة الأدمن (أو أرسل `/update`) — يحدّث فعلياً ويعيد التشغيل عند الحاجة.

> 💡 السكربت صامت عندما لا يوجد تحديث جديد. لو تريد إشعاراً في كل فحص
> حتى بدون جديد، أضف `NOTIFY_NO_CHANGE=1` قبل مسار السكربت في سطر cron.

---

## 📁 هيكل المشروع

```
.
├── bot.py                          # الملف الرئيسي: المعالجات ومسار التحميل والرفع
├── url_utils.py                    # أدوات الروابط (SSRF، كاش، استخراج، منصات)
├── link_resolvers.py               # سناب سبوت لايت + روابط الأغاني
├── content_filter.py               # فلتر المحتوى الإباحي وحظر الحسابات
├── cookies_manager.py              # اختيار ملفات الكوكيز والتحقق منها
├── video_processing.py             # ffmpeg/ffprobe (مصغّرات وتجهيز الفيديو)
├── download_errors.py              # تصنيف أخطاء yt-dlp
├── subscription_db.py              # إدارة قاعدة البيانات (اشتراكات، كاش، استبيان، حظر)
├── translations.py                 # نظام الترجمة (عربي/إنجليزي)
├── queue_manager.py                # نظام الطوابير
├── pg_backup.py                    # النسخ الاحتياطي
├── setup_postgres.py               # إعداد قاعدة البيانات
├── update_ytdlp.sh                 # التحديث التلقائي لـ yt-dlp (cron)
├── requirements.txt                # المكتبات المطلوبة (إصدارات مثبّتة)
├── requirements-dev.txt            # أدوات التطوير والاختبار
├── env.example                     # مثال ملف البيئة
├── run.sh                          # سكربت تشغيل مختصر
├── .gitignore                      # ملفات محمية
├── README.md                       # هذا الملف
├── QUICK_START.md                  # دليل البدء السريع
├── INSTALLATION_GUIDE.md           # دليل التثبيت الكامل
├── tests/                          # اختبارات الوحدات (pytest)
├── videos/                         # مجلد الوسائط المؤقتة (فيديو/صور)
└── cookies/                        # مجلد ملفات Cookies للمنصات
```

---

## 🔐 الأمان

> **⚠️ لا ترفع أبداً:**
> - ملف `.env` (معلومات سرية)
> - ملفات `.session` (جلسات Telegram)
> - ملفات `backup_*.sql` (نسخ احتياطية)
> - مجلد `cookies/` (ملفات حساسة)

تأكد دائماً من `.gitignore` قبل الرفع على GitHub!

---

## 🤝 المساهمة

المشروع مفتوح المصدر! للمساهمة:

1. Fork المشروع
2. أنشئ branch: `git checkout -b feature/amazing-feature`
3. Commit: `git commit -m 'Add feature'`
4. Push: `git push origin feature/amazing-feature`
5. افتح Pull Request

---

## 🖥️ تشغيل البوت وإدارته 24/7 (Raspberry Pi / Linux)

> هذا القسم مرجع سريع لكل الأوامر حتى لا تنساها. الأمثلة تفترض أن المستخدم
> `abdalwahab` والمجلد `~/bot7` (أي `/home/abdalwahab/bot7`). عدّل الاسم/المسار
> إن كانا مختلفين عندك.

### ▶️ التشغيل اليدوي (للتجربة فقط)

```bash
cd ~/bot7
python3 bot.py
```

يعمل البوت طالما النافذة مفتوحة، ويتوقف عند إغلاقها أو إطفاء الجهاز. للتشغيل
الدائم استخدم خدمة systemd بالأسفل. ⬇️

---

### 🔁 التشغيل 24/7 + الإقلاع التلقائي بعد إطفاء الجهاز (systemd) — المُوصى به

هذه الطريقة تجعل البوت:
- يعمل في الخلفية **24 ساعة**.
- **يعيد تشغيل نفسه تلقائياً** إذا تعطّل (Crash).
- **يبدأ تلقائياً** بعد إعادة تشغيل/انقطاع كهرباء الجهاز.

**1) أنشئ ملف الخدمة (مرة واحدة فقط):**

```bash
sudo nano /etc/systemd/system/bot7.service
```

**2) الصق هذا المحتوى** (عدّل `User` و `WorkingDirectory` إن لزم):

```ini
[Unit]
Description=Telegram Download Bot (bot7)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=abdalwahab
WorkingDirectory=/home/abdalwahab/bot7
ExecStart=/usr/bin/python3 /home/abdalwahab/bot7/bot.py
Restart=always
RestartSec=5
StandardOutput=append:/home/abdalwahab/bot7/bot.log
StandardError=append:/home/abdalwahab/bot7/bot.log

[Install]
WantedBy=multi-user.target
```

احفظ بـ `Ctrl+O` ثم `Enter`، واخرج بـ `Ctrl+X`.

**3) فعّل الخدمة وشغّلها (مرة واحدة):**

```bash
sudo systemctl daemon-reload          # إعادة قراءة ملفات الخدمات
sudo systemctl enable bot7            # تشغيل تلقائي عند إقلاع الجهاز
sudo systemctl start bot7             # تشغيل البوت الآن
```

تم! ✅ البوت الآن يعمل 24/7 وسيعود تلقائياً بعد أي إطفاء أو تعطّل.

---

### 🎛️ أوامر التحكم اليومية

| الإجراء | الأمر |
|---------|-------|
| ▶️ تشغيل | `sudo systemctl start bot7` |
| ⏹️ إيقاف | `sudo systemctl stop bot7` |
| 🔄 إعادة تشغيل | `sudo systemctl restart bot7` |
| 📊 الحالة | `sudo systemctl status bot7` |
| 🚫 إلغاء التشغيل التلقائي | `sudo systemctl disable bot7` |
| ✅ تفعيل التشغيل التلقائي | `sudo systemctl enable bot7` |

**عرض السجلات (Logs) لمتابعة الأخطاء:**

```bash
# آخر السجلات لحظة بلحظة (اخرج بـ Ctrl+C)
journalctl -u bot7 -f

# أو من ملف السجل المباشر
tail -f ~/bot7/bot.log
```

---

### ⬆️ تحديث كود البوت (سحب آخر نسخة من GitHub)

```bash
cd ~/bot7
git fetch origin
git checkout main && git pull origin main   # أو اسم الفرع الذي تستخدمه
sudo systemctl restart bot7                  # أعد التشغيل لتطبيق التحديث
```

> لتحديث ملفات محددة فقط من فرع معيّن:
> ```bash
> cd ~/bot7
> git fetch origin <اسم-الفرع>
> git checkout origin/<اسم-الفرع> -- bot.py subscription_db.py translations.py
> sudo systemctl restart bot7
> ```

---

### 📦 تحديث المكتبات (مهم — خصوصاً yt-dlp)

مكتبة **yt-dlp** تحتاج تحديثاً دورياً لأن المنصات (يوتيوب/فيسبوك...) تغيّر أنظمتها
باستمرار. إذا فشل التحميل فجأة، أول حل هو تحديثها:

```bash
cd ~/bot7

# تحديث yt-dlp فقط (الأكثر أهمية)
python3 -m pip install -U yt-dlp

# أو تحديث كل المكتبات من ملف المتطلبات
python3 -m pip install -U -r requirements.txt

sudo systemctl restart bot7   # أعد التشغيل بعد التحديث
```

> إن كنت تستخدم بيئة افتراضية (venv) فعّلها أولاً: `source venv/bin/activate`.

**التأكد من إصدار ffmpeg** (مطلوب للدمج والمعاينة وحذف التجمّد):

```bash
ffmpeg -version        # إن لم يكن مثبتاً: sudo apt install -y ffmpeg
```

---

### 🆘 حل سريع للمشاكل الشائعة

| المشكلة | الحل |
|---------|------|
| فشل التحميل من منصة | `python3 -m pip install -U yt-dlp` ثم `sudo systemctl restart bot7` |
| البوت لا يردّ | `sudo systemctl status bot7` ثم راجع `journalctl -u bot7 -f` |
| تعديل المتغيّرات (التوكن/الأدمن) | عدّل ملف `.env` ثم `sudo systemctl restart bot7` |
| البوت لا يبدأ بعد الإقلاع | `sudo systemctl enable bot7` |
| رسالة "محتوى مقيّد" على إنستغرام | المنشور مقيّد بالعمر؛ حدّث `cookies/instagram.txt` بحساب +18 مفعّل عنده "عرض المحتوى الحسّاس" |

---

## 📜 الترخيص

هذا المشروع مرخص تحت رخصة MIT - انظر ملف [LICENSE](LICENSE) للتفاصيل.

---

## 📞 الدعم

**واجهت مشكلة؟**

1. راجع [المشاكل الشائعة وحلولها](#️-المشاكل-الشائعة-وحلولها)
2. افتح [Issue جديد](https://github.com/YOUR_USERNAME/telegram-downloader-bot/issues)
3. راجع [Issues المفتوحة](https://github.com/YOUR_USERNAME/telegram-downloader-bot/issues)

---

## 🌟 إذا أعجبك المشروع

اضغط ⭐ لدعم المشروع!

---

**صُنع بـ ❤️ للمجتمع العربي**

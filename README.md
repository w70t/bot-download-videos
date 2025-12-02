# 🤖 بوت تحميل الفيديوهات من تيليجرام

[![GitHub](https://img.shields.io/badge/GitHub-w70t%2Ftelegram--downloader--bot-blue?logo=github)](https://github.com/w70t/telegram-downloader-bot)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-12%2B-blue?logo=postgresql)](https://www.postgresql.org/)


# 🤖 بوت تحميل الفيديوهات من تيليجرام

[![GitHub](https://img.shields.io/badge/GitHub-telegram--downloader--bot-blue?logo=github)](https://github.com/YOUR_USERNAME/telegram-downloader-bot)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-12%2B-blue?logo=postgresql)](https://www.postgresql.org/)

بوت متطور لتحميل الفيديوهات من مختلف المنصات (YouTube, Facebook, Instagram, TikTok, وغيرها) ورفعها على تيليجرام مع دعم ملفات حتى 2GB.

---

## 📚 أدلة التثبيت والاستخدام

- **⚡ [دليل البدء السريع](QUICK_START.md)** - ابدأ في 5 دقائق!
- **📖 [دليل التثبيت الكامل](INSTALLATION_GUIDE.md)** - شرح مفصل خطوة بخطوة
- **🔧 [حل مشاكل PostgreSQL](POSTGRESQL_TROUBLESHOOTING.md)** - حل المشكلة الشائعة

> **⚠️ مهم جداً:** اقرأ دليل [حل مشاكل PostgreSQL](POSTGRESQL_TROUBLESHOOTING.md) لتجنب مشكلة المصادقة الشائعة!

---

## ✨ المميزات الرئيسية

- ✅ **تحميل من منصات متعددة**: YouTube, Facebook, Instagram, TikTok, Twitter, Reddit, Pinterest, Snapchat
- ✅ **رفع ملفات كبيرة**: يدعم رفع ملفات حتى **2GB**
- ✅ **فيديوهات طويلة**: يحمل فيديوهات حتى 3 ساعات+
- ✅ **جودات متعددة**: اختيار بين جودة عالية، متوسطة، أو صوت فقط (128kbps MP3)
- ✅ **نظام اشتراكات**: إدارة اشتراكات المستخدمين مع PostgreSQL
- ✅ **إشعارات تلقائية**: إرسال تنبيهات للأدمن عن الأخطاء والأعضاء الجدد
- ✅ **نظام طوابير**: معالجة التحميلات بشكل منظم لتجنب الازدحام
- ✅ **دعم متعدد اللغات**: عربي وإنجليزي
- ✅ **نسخ احتياطي تلقائي**: نسخ احتياطي لقاعدة البيانات PostgreSQL

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
LOG_CHANNEL_ID=
ERROR_LOG_CHANNEL_ID=
NEW_MEMBERS_CHANNEL_ID=
```

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

📖 **للتفاصيل:** اقرأ [POSTGRESQL_TROUBLESHOOTING.md](POSTGRESQL_TROUBLESHOOTING.md)

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

## 🚀 تشغيل مستمر (systemd)

**إنشاء خدمة:**

```bash
sudo nano /etc/systemd/system/telegram-bot.service
```

**المحتوى:**

```ini
[Unit]
Description=Telegram Video Downloader Bot
After=network.target postgresql.service

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/telegram-downloader-bot
Environment="PATH=/home/YOUR_USERNAME/telegram-downloader-bot/venv/bin"
ExecStart=/home/YOUR_USERNAME/telegram-downloader-bot/venv/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**تفعيل:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot
sudo systemctl start telegram-bot
sudo systemctl status telegram-bot
```

---

## 📁 هيكل المشروع

```
.
├── bot.py                          # الملف الرئيسي للبوت
├── subscription_db.py              # إدارة قاعدة البيانات
├── translations.py                 # نظام الترجمة
├── queue_manager.py                # نظام الطوابير
├── pg_backup.py                    # النسخ الاحتياطي
├── setup_postgres.py               # إعداد قاعدة البيانات
├── requirements.txt                # المكتبات المطلوبة
├── env.example                     # مثال ملف البيئة
├── .gitignore                      # ملفات محمية
├── README.md                       # هذا الملف
├── QUICK_START.md                  # دليل البدء السريع
├── INSTALLATION_GUIDE.md           # دليل التثبيت الكامل
├── POSTGRESQL_TROUBLESHOOTING.md   # حل مشاكل PostgreSQL
├── downloads/                      # مجلد التحميلات المؤقتة
├── videos/                         # مجلد الفيديوهات المؤقتة
└── cookies/                        # مجلد ملفات Cookies
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

## 📜 الترخيص

هذا المشروع مرخص تحت رخصة MIT - انظر ملف [LICENSE](LICENSE) للتفاصيل.

---

## 📞 الدعم

**واجهت مشكلة؟**

1. راجع [استكشاف الأخطاء](POSTGRESQL_TROUBLESHOOTING.md)
2. افتح [Issue جديد](https://github.com/YOUR_USERNAME/telegram-downloader-bot/issues)
3. راجع [Issues المفتوحة](https://github.com/YOUR_USERNAME/telegram-downloader-bot/issues)

---

## 🌟 إذا أعجبك المشروع

اضغط ⭐ لدعم المشروع!

---

**صُنع بـ ❤️ للمجتمع العربي**

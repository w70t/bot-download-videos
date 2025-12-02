# ⚡ دليل البدء السريع - Quick Start Guide

> **للمستخدمين الذين يريدون تشغيل البوت بأسرع وقت ممكن**

---

## 📦 التثبيت في 5 دقائق

### 1️⃣ تثبيت المتطلبات

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git ffmpeg postgresql postgresql-contrib
```

---

### 2️⃣ تحميل المشروع

```bash
cd ~ && git clone https://github.com/YOUR_USERNAME/telegram-downloader-bot.git && cd telegram-downloader-bot
```

> استبدل `YOUR_USERNAME` باسم المستخدم على GitHub

---

### 3️⃣ تثبيت المكتبات

```bash
python3 -m venv venv && source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt
```

---

### 4️⃣ إعداد PostgreSQL

```bash
# إنشاء مستخدم (استبدل YOUR_PASSWORD بكلمة مرور قوية)
sudo -u postgres psql -c "CREATE USER bot_user WITH PASSWORD 'YOUR_PASSWORD';" || sudo -u postgres psql -c "ALTER USER bot_user WITH PASSWORD 'YOUR_PASSWORD';"

# إنشاء قاعدة البيانات
sudo -u postgres psql -c "CREATE DATABASE telegram_bot;" 2>/dev/null || echo "Database exists"

# منح الصلاحيات
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE telegram_bot TO bot_user;"
```

---

### 5️⃣ إنشاء ملف `.env`

```bash
cp env.example .env && nano .env
```

**عدّل المعلومات التالية:**

```bash
BOT_TOKEN=احصل_عليه_من_@BotFather
PYROGRAM_API_ID=احصل_عليه_من_my.telegram.org/apps
PYROGRAM_API_HASH=احصل_عليه_من_my.telegram.org/apps
ADMIN_ID=احصل_عليه_من_@userinfobot
POSTGRES_PASSWORD=كلمة_المرور_من_الخطوة_4
```

**احفظ:** `Ctrl+O` ثم `Enter` ثم `Ctrl+X`

---

### 6️⃣ إنشاء الجداول

```bash
source venv/bin/activate && python3 setup_postgres.py
```

---

### 7️⃣ تشغيل البوت

```bash
python3 bot.py
```

---

## 🎯 الحصول على المعلومات المطلوبة

### `BOT_TOKEN`
1. افتح Telegram → ابحث عن `@BotFather`
2. أرسل: `/newbot`
3. اتبع التعليمات
4. انسخ الـ Token

### `PYROGRAM_API_ID` و `PYROGRAM_API_HASH`
1. افتح: https://my.telegram.org/apps
2. سجل دخول برقم هاتفك
3. أنشئ تطبيق جديد
4. انسخ `api_id` و `api_hash`

### `ADMIN_ID`
1. افتح Telegram → ابحث عن `@userinfobot`
2. أرسل: `/start`
3. سيرد برقمك التعريفي

### `POSTGRES_PASSWORD`
- استخدم كلمة مرور قوية (مثال: `MyBot2024!@#`)
- **نفس** الكلمة المستخدمة في الخطوة 4

---

## ⚠️ المشاكل الشائعة

### `password authentication failed`

```bash
# حل سريع:
sudo -u postgres psql -c "ALTER USER bot_user WITH PASSWORD 'YOUR_NEW_PASSWORD';"
# ثم حدّث .env بنفس الكلمة
nano .env
```

### `ModuleNotFoundError`

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### `PostgreSQL not running`

```bash
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

---

## 🚀 تشغيل مستمر

### باستخدام screen

```bash
screen -S bot
cd ~/telegram-downloader-bot
source venv/bin/activate
python3 bot.py
# اضغط: Ctrl+A ثم D للخروج
# للعودة: screen -r bot
```

---

## 📚 المزيد من المعلومات

- **الدليل الكامل:** [INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md)
- **حل مشاكل PostgreSQL:** [POSTGRESQL_TROUBLESHOOTING.md](POSTGRESQL_TROUBLESHOOTING.md)
- **الـ README:** [README.md](README.md)

---

**🎉 الآن البوت يعمل! استمتع!**

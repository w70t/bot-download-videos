# 🔧 حل مشاكل PostgreSQL

دليل لحل أكثر مشاكل PostgreSQL شيوعاً عند تشغيل البوت. ابدأ من المشكلة التي تواجهها.

---

## ❌ المشكلة #1: `password authentication failed for user "bot_user"`

أكثر مشكلة شيوعاً! السبب أن كلمة المرور في ملف `.env` **لا تطابق** كلمة المرور في PostgreSQL.

### الحل

**1. حدّث كلمة المرور في PostgreSQL:**

```bash
sudo -u postgres psql -c "ALTER USER bot_user WITH PASSWORD 'كلمة_مرور_جديدة';"
```

**2. حدّث نفس الكلمة في `.env`:**

```bash
nano .env
```

تأكد أن السطر مطابق تماماً (بدون مسافات أو علامات اقتباس):

```bash
POSTGRES_PASSWORD=كلمة_مرور_جديدة
```

**3. أعد تشغيل البوت.**

> 💡 **نصيحة:** تجنّب الرموز الخاصة مثل `@` و `:` و `/` في كلمة المرور لتفادي مشاكل في صيغة الاتصال.

---

## ❌ المشكلة #2: `could not connect to server: Connection refused`

خدمة PostgreSQL غير قيد التشغيل.

### الحل

```bash
# تحقق من الحالة
sudo systemctl status postgresql

# شغّل الخدمة
sudo systemctl start postgresql

# فعّل التشغيل التلقائي عند الإقلاع
sudo systemctl enable postgresql
```

تأكد أيضاً أن `POSTGRES_HOST` و `POSTGRES_PORT` في `.env` صحيحان (عادة `localhost` و `5432`).

---

## ❌ المشكلة #3: `peer authentication failed for user "bot_user"`

PostgreSQL يستخدم مصادقة `peer` بدلاً من كلمة المرور للاتصالات المحلية.

### الحل

**1. افتح ملف الإعدادات** (غيّر رقم الإصدار حسب جهازك، مثل 14 أو 15 أو 16):

```bash
sudo nano /etc/postgresql/*/main/pg_hba.conf
```

**2. ابحث عن أسطر مثل:**

```
local   all   all   peer
```

**3. غيّر `peer` إلى `md5`:**

```
local   all   all   md5
```

**4. أعد تشغيل PostgreSQL:**

```bash
sudo systemctl restart postgresql
```

> 💡 البديل الأسهل: استخدم `POSTGRES_HOST=localhost` في `.env` (اتصال TCP) بدلاً من الاتصال عبر socket المحلي.

---

## ❌ المشكلة #4: `database "telegram_bot" does not exist`

لم يتم إنشاء قاعدة البيانات بعد.

### الحل

```bash
sudo -u postgres psql -c "CREATE DATABASE telegram_bot;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE telegram_bot TO bot_user;"
```

---

## ❌ المشكلة #5: `permission denied for schema public` (PostgreSQL 15+)

في PostgreSQL 15 فما فوق، صلاحيات `GRANT ALL ON DATABASE` لا تكفي لإنشاء الجداول داخل schema الـ `public`.

### الحل

```bash
sudo -u postgres psql -d telegram_bot -c "GRANT ALL ON SCHEMA public TO bot_user;"
sudo -u postgres psql -d telegram_bot -c "ALTER DATABASE telegram_bot OWNER TO bot_user;"
```

---

## ❌ المشكلة #6: `role "bot_user" already exists`

المستخدم موجود مسبقاً — هذه ليست مشكلة. فقط حدّث كلمة مروره:

```bash
sudo -u postgres psql -c "ALTER USER bot_user WITH PASSWORD 'كلمة_المرور';"
```

---

## ❌ المشكلة #7: `ModuleNotFoundError: No module named 'psycopg2'`

مكتبة الاتصال بـ PostgreSQL غير مثبّتة.

### الحل

```bash
source venv/bin/activate
pip install -r requirements.txt
```

إذا استمرت المشكلة، ثبّتها يدوياً:

```bash
pip install psycopg2-binary
```

---

## 🔍 التحقق من سلامة الإعداد

اختبر الاتصال يدوياً بنفس بيانات `.env`:

```bash
psql -U bot_user -h localhost -d telegram_bot
```

- إذا طُلبت منك كلمة المرور ودخلت إلى `telegram_bot=>` فالإعداد سليم ✅
- للخروج اكتب `\q`

ثم أنشئ الجداول:

```bash
source venv/bin/activate
python3 setup_postgres.py
```

يجب أن ترى: `✅ تم إنشاء جميع الجداول بنجاح!`

---

## 📞 ما زالت المشكلة قائمة؟

1. راجع سجلّات PostgreSQL: `sudo journalctl -u postgresql -n 50`
2. راجع سجلّ البوت: `cat bot_standalone.log`
3. افتح [Issue جديد](https://github.com/w70t/bot-download-videos/issues) مع نص الخطأ كاملاً.

---

**بالتوفيق! 🚀**

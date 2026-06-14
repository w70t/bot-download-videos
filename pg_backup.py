"""
نظام النسخ الاحتياطي لقاعدة بيانات PostgreSQL
=================================================
تصدير قاعدة البيانات كملف SQL أو JSON
"""

import os
import subprocess
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

load_dotenv()
logger = logging.getLogger(__name__)

# PostgreSQL Configuration
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432'),
    'database': os.getenv('POSTGRES_DB', 'telegram_bot'),
    'user': os.getenv('POSTGRES_USER', 'bot_user'),
    'password': os.getenv('POSTGRES_PASSWORD')
}


def create_sql_backup():
    """
    إنشاء نسخة احتياطية SQL باستخدام pg_dump
    
    Returns:
        tuple: (success: bool, file_path: str or error_message: str)
    """
    try:
        # اسم ملف النسخة الاحتياطية مع التاريخ والوقت
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_postgres_{timestamp}.sql"
        backup_path = os.path.join(os.getcwd(), backup_filename)
        
        # إعداد بيئة التنفيذ مع كلمة المرور
        env = os.environ.copy()
        if POSTGRES_CONFIG['password']:
            env['PGPASSWORD'] = POSTGRES_CONFIG['password']
        
        # بناء أمر pg_dump
        cmd = [
            'pg_dump',
            '-h', POSTGRES_CONFIG['host'],
            '-p', str(POSTGRES_CONFIG['port']),
            '-U', POSTGRES_CONFIG['user'],
            '-d', POSTGRES_CONFIG['database'],
            '-F', 'p',  # Plain text format
            '-f', backup_path
        ]
        
        logger.info(f"🔄 بدء إنشاء نسخة احتياطية SQL: {backup_filename}")
        
        # تنفيذ الأمر
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=60  # timeout بعد دقيقة
        )
        
        if result.returncode == 0:
            logger.info(f"✅ تم إنشاء النسخة الاحتياطية بنجاح: {backup_path}")
            return True, backup_path
        else:
            error_msg = result.stderr or "خطأ غير معروف"
            logger.error(f"❌ فشل pg_dump: {error_msg}")
            return False, f"pg_dump error: {error_msg}"
            
    except FileNotFoundError:
        logger.warning("⚠️ pg_dump غير موجود، سيتم استخدام طريقة JSON البديلة")
        return False, "pg_dump not found"
    except subprocess.TimeoutExpired:
        logger.error("❌ انتهت مهلة pg_dump")
        return False, "pg_dump timeout"
    except Exception as e:
        logger.error(f"❌ خطأ في create_sql_backup: {e}")
        return False, str(e)


def create_json_backup():
    """
    إنشاء نسخة احتياطية JSON (طريقة بديلة)
    
    Returns:
        tuple: (success: bool, file_path: str or error_message: str)
    """
    try:
        # اسم ملف النسخة الاحتياطية
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_postgres_{timestamp}.json"
        backup_path = os.path.join(os.getcwd(), backup_filename)
        
        logger.info(f"🔄 بدء إنشاء نسخة احتياطية JSON: {backup_filename}")
        
        # الاتصال بقاعدة البيانات
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            backup_data = {
                'backup_date': datetime.now().isoformat(),
                'database': POSTGRES_CONFIG['database'],
                'tables': {}
            }

            # قائمة الجداول المطلوب نسخها
            tables = ['users', 'payments', 'settings', 'daily_downloads']

            for table_name in tables:
                try:
                    # استخراج بيانات الجدول - استخدام sql.Identifier لتفادي أي حقن
                    cursor.execute(
                        sql.SQL('SELECT * FROM {}').format(sql.Identifier(table_name))
                    )
                    rows = cursor.fetchall()

                    # تحويل إلى قائمة من القواميس
                    backup_data['tables'][table_name] = [dict(row) for row in rows]

                    logger.info(f"✅ تم نسخ جدول {table_name}: {len(rows)} صف")

                except Exception as table_error:
                    logger.warning(f"⚠️ خطأ في نسخ جدول {table_name}: {table_error}")
                    backup_data['tables'][table_name] = []
        finally:
            conn.close()
        
        # حفظ البيانات كملف JSON
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2, default=str)
        
        logger.info(f"✅ تم إنشاء النسخة الاحتياطية JSON بنجاح: {backup_path}")
        return True, backup_path
        
    except Exception as e:
        logger.error(f"❌ خطأ في create_json_backup: {e}")
        return False, str(e)


def create_backup(prefer_sql=True):
    """
    إنشاء نسخة احتياطية (محاولة SQL أولاً، ثم JSON)
    
    Args:
        prefer_sql: تفضيل تنسيق SQL إذا كان متاحاً
    
    Returns:
        tuple: (success: bool, file_path: str or error_message: str)
    """
    if prefer_sql:
        success, result = create_sql_backup()
        if success:
            return success, result
        
        # إذا فشل SQL، محاولة JSON
        logger.info("🔄 محاولة النسخ الاحتياطي بتنسيق JSON...")
        return create_json_backup()
    else:
        return create_json_backup()


def cleanup_old_backups(max_age_hours=24):
    """
    حذف ملفات النسخ الاحتياطي القديمة
    
    Args:
        max_age_hours: العمر الأقصى بالساعات للملفات (افتراضي: 24 ساعة)
    """
    try:
        import glob
        import time
        
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        # البحث عن ملفات النسخ الاحتياطي
        backup_patterns = ['backup_postgres_*.sql', 'backup_postgres_*.json']
        
        deleted_count = 0
        for pattern in backup_patterns:
            for backup_file in glob.glob(pattern):
                file_age = current_time - os.path.getmtime(backup_file)
                
                if file_age > max_age_seconds:
                    try:
                        os.remove(backup_file)
                        logger.info(f"🗑️ تم حذف نسخة احتياطية قديمة: {backup_file}")
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"❌ خطأ في حذف {backup_file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✅ تم حذف {deleted_count} ملف نسخ احتياطي قديم")
            
    except Exception as e:
        logger.error(f"❌ خطأ في cleanup_old_backups: {e}")


if __name__ == "__main__":
    # اختبار النظام
    logging.basicConfig(level=logging.INFO)
    
    print("🧪 اختبار نظام النسخ الاحتياطي...")
    success, result = create_backup()
    
    if success:
        print(f"✅ نجح! الملف: {result}")
        print(f"📦 حجم الملف: {os.path.getsize(result) / 1024:.2f} KB")
    else:
        print(f"❌ فشل: {result}")

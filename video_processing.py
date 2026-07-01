# -*- coding: utf-8 -*-
"""
معالجة الفيديو - Video Processing
=================================
توليد المصغّرات، فحص الترميز بـ ffprobe، وتجهيز الفيديو لتلجرام
(H.264/AAC + faststart) عبر ffmpeg.
"""

import os
import json
import logging
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)


def get_file_size_mb(file_path):
    """الحصول على حجم الملف بالميغابايت"""
    return os.path.getsize(file_path) / (1024 * 1024)


def generate_video_thumbnail(video_path, duration=None):
    """يولّد صورة مصغّرة (JPEG) للفيديو حتى تظهر معاينة ثابتة في تلجرام
    بدل الإطار الأسود/المتجمّد. يرجع مسار المصغّر أو None عند الفشل."""
    try:
        thumb_path = os.path.splitext(video_path)[0] + '.thumb.jpg'
        # نأخذ لقطة بعد ثانية واحدة (أو 10% من المدة للفيديوهات الأطول)
        ss = 1.0
        if duration and duration > 4:
            ss = min(3.0, duration / 10.0)
        cmd = [
            'ffmpeg', '-y', '-ss', str(ss), '-i', video_path,
            '-frames:v', '1', '-vf', 'scale=320:-2',
            '-q:v', '4', thumb_path,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
    except Exception as e:
        logger.warning(f"⚠️ تعذّر توليد المصغّر: {e}")
    return None


def probe_video(video_path):
    """يفحص الفيديو بـ ffprobe ويرجع (vcodec, acodec, width, height, duration).
    القيم غير المتوفرة تكون None."""
    try:
        out = subprocess.run(
            ['ffprobe', '-v', 'error',
             '-show_entries', 'stream=codec_type,codec_name,width,height:format=duration',
             '-of', 'json', video_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60
        ).stdout.decode('utf-8', 'ignore')
        data = json.loads(out or '{}')
        vcodec = acodec = width = height = None
        for s in data.get('streams', []):
            if s.get('codec_type') == 'video' and vcodec is None:
                vcodec = (s.get('codec_name') or '').lower()
                width = s.get('width')
                height = s.get('height')
            elif s.get('codec_type') == 'audio' and acodec is None:
                acodec = (s.get('codec_name') or '').lower()
        duration = None
        try:
            duration = int(float(data.get('format', {}).get('duration')))
        except (TypeError, ValueError):
            pass
        return vcodec, acodec, width, height, duration
    except Exception as e:
        logger.warning(f"⚠️ تعذّر فحص الفيديو بـ ffprobe: {e}")
        return None, None, None, None, None


def finalize_video(video_path):
    """يجهّز الفيديو لتلجرام لكل المنصات (وليس يوتيوب فقط) ويرجع
    (width, height, duration) الحقيقية من الملف:
    - يضمن ترميز H.264/AAC: ينسخ إن كان متوافقاً، وإلا يُعيد الترميز (سبب
      تجمّد الصورة في فيسبوك/منصات أخرى تستخدم VP9/AV1).
    - +faststart: نقل moov atom للبداية ليُعاين ويُشغّل فوراً.
    - creation_time = الآن ليظهر المقطع بترتيب وقت التحميل في المعرض.
    """
    vcodec, acodec, width, height, duration = probe_video(video_path)

    # هل الترميز متوافق مع مشغّل تلجرام؟ (None = غير معروف، نكتفي بالنسخ)
    v_compatible = vcodec in ('h264', 'avc1', None)
    a_compatible = acodec in ('aac', 'mp4a', None)
    v_args = ['-c:v', 'copy'] if v_compatible else \
        ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p']
    a_args = ['-c:a', 'copy'] if a_compatible else ['-c:a', 'aac', '-b:a', '128k']
    if not v_compatible:
        logger.info(f"🎞️ إعادة ترميز الفيديو إلى H.264 (المصدر: {vcodec})")

    tmp = os.path.splitext(video_path)[0] + '.fixed.mp4'
    try:
        now_iso = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        cmd = (
            ['ffmpeg', '-y', '-i', video_path, '-map', '0:v?', '-map', '0:a?']
            + v_args + a_args
            + ['-movflags', '+faststart', '-metadata', f'creation_time={now_iso}', tmp]
        )
        # إعادة الترميز قد تستغرق وقتاً أطول من النسخ
        timeout = 3600 if not v_compatible else 900
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, video_path)
            # أعد الفحص بعد التحويل للحصول على الأبعاد الصحيحة
            nv, na, nw, nh, nd = probe_video(video_path)
            width = nw or width
            height = nh or height
            duration = nd or duration
    except Exception as e:
        logger.warning(f"⚠️ تعذّر تجهيز الفيديو لتلجرام: {e}")
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
    # تحديث تاريخ الملف نفسه إلى الآن (مهم لمعرض أندرويد)
    try:
        os.utime(video_path, None)
    except Exception:
        pass

    return width, height, duration

# -*- coding: utf-8 -*-
"""اختبارات تجهيز الفيديو لتلجرام (finalize_video).

نتحقق من بناء أمر ffmpeg بلا تشغيل ffmpeg فعلي: نستبدل probe_video
و subprocess.run بـ mock ونفحص الوسائط المُمرّرة. الهدف الأساسي: التأكد
من إضافة مسار صوت صامت (anullsrc) للفيديو بلا صوت حتى لا يعرضه تلجرام
كصورة متحركة (GIF)، وعدم إضافته حين يوجد صوت أصلاً.
"""

import os
from unittest import mock

import video_processing


def _run_finalize(tmp_path, probe_result):
    """يشغّل finalize_video على ملف وهمي مع probe_video/subprocess مُستبدلين،
    ويعيد قائمة وسائط ffmpeg الملتقطة."""
    video_path = os.path.join(str(tmp_path), 'clip.mp4')
    with open(video_path, 'wb') as f:
        f.write(b'\x00')  # ملف غير فارغ يكفي لـ os.utime

    captured = {}

    def fake_run(cmd, *a, **k):
        captured['cmd'] = cmd
        return mock.Mock(returncode=0)

    with mock.patch.object(video_processing, 'probe_video', return_value=probe_result), \
         mock.patch.object(video_processing.subprocess, 'run', side_effect=fake_run):
        video_processing.finalize_video(video_path)

    return captured.get('cmd', [])


def test_silent_video_gets_anullsrc(tmp_path):
    # فيديو H.264 بلا مسار صوت (acodec=None)
    cmd = _run_finalize(tmp_path, ('h264', None, 1080, 1920, 30))
    assert 'anullsrc=channel_layout=stereo:sample_rate=44100' in cmd
    assert '-shortest' in cmd
    # الصوت يُرمَّز AAC (لا نسخ) لأنه مُولّد جديد
    assert '-c:a' in cmd and 'aac' in cmd


def test_video_with_audio_no_anullsrc(tmp_path):
    # فيديو H.264 + AAC: لا حاجة لصوت صامت، ولا إعادة ترميز
    cmd = _run_finalize(tmp_path, ('h264', 'aac', 1080, 1920, 30))
    joined = ' '.join(cmd)
    assert 'anullsrc' not in joined
    assert '-shortest' not in cmd
    # الصوت المتوافق يُنسخ كما هو
    assert 'copy' in cmd


def test_incompatible_audio_reencoded_not_silenced(tmp_path):
    # فيديو H.264 بصوت opus (غير متوافق): يُعاد ترميزه AAC بلا anullsrc
    cmd = _run_finalize(tmp_path, ('h264', 'opus', 720, 1280, 15))
    joined = ' '.join(cmd)
    assert 'anullsrc' not in joined
    assert '-c:a' in cmd and 'aac' in cmd


def test_probe_failure_does_not_silence_audio(tmp_path):
    # فشل ffprobe كلياً (كل القيم None): لا نعرف إن كان ثمة صوت، فلا نحقن
    # صوتاً صامتاً حتى لا نُسقط صوتاً موجوداً — ننسخ v/a بأمان.
    cmd = _run_finalize(tmp_path, (None, None, None, None, None))
    joined = ' '.join(cmd)
    assert 'anullsrc' not in joined
    assert '-shortest' not in cmd
    assert '-map' in cmd and '0:a?' in cmd  # مسار الصوت الأصلي محفوظ إن وُجد


def test_faststart_and_metadata_strip_always(tmp_path):
    for probe in [('h264', None, 100, 100, 5), ('h264', 'aac', 100, 100, 5)]:
        cmd = _run_finalize(tmp_path, probe)
        assert '+faststart' in cmd
        assert '-map_metadata' in cmd

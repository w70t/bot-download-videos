# -*- coding: utf-8 -*-
"""حواجز رجوع لإعدادات محدث مكتبات التحميل."""

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / 'update_ytdlp.sh').read_text(
    encoding='utf-8')


def test_updater_caps_curl_cffi_without_polluting_version_package_names():
    assert 'CURL_CFFI_REQUIREMENT="curl_cffi<0.16"' in SCRIPT
    assert 'INSTALL_ARGS+=("$CURL_CFFI_REQUIREMENT")' in SCRIPT
    assert 'pip install -U "${INSTALL_ARGS[@]}"' in SCRIPT
    assert 'PKG_ARGS+=("curl_cffi")' in SCRIPT

    # تقارير OLDV/NEWP تمر على أسماء PKGS الأصلية لا متطلبات مثل <0.16.
    assert SCRIPT.count('for p in "${PKG_ARGS[@]}"; do') == 2
    assert 'ver "$p"' in SCRIPT

import os
import sys

# إتاحة استيراد وحدات المشروع من جذر المستودع عند تشغيل pytest من أي مكان
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

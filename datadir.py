"""مكان ملفات البيانات (الأسعار وشموع الساعة).
على ريلواي: لو فيه Volume متركّب، الملفات بتتحفظ عليه ومش بتتمسح مع كل رفع.
على الجهاز: نفس الفولدر."""
import os

DIR = os.environ.get("DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or "."
os.makedirs(DIR, exist_ok=True)


def D(name):
    return os.path.join(DIR, name)

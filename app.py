"""
سيرفر صغير لـ Railway:
- بيعرض صفحة موجات القطاعات على الرابط الرئيسي.
- بيحدّث الأسعار والصفحة أول ما يشتغل، وبعدها كل يوم الساعة ٤ و٨ مساءً بتوقيت القاهرة.
- لو حطيتي متغير APP_PASSWORD في Railway، الصفحة هتطلب اسم مستخدم (أي اسم) والباسورد ده.
"""
import base64
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

import update

CAIRO = ZoneInfo("Africa/Cairo")
HOURS = {16, 20}
PASSWORD = os.environ.get("APP_PASSWORD", "")
state = {"last": None, "running": False}
lock = threading.Lock()

WAIT = """<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta http-equiv="refresh" content="30">
<title>بيتحدث</title></head><body style="font-family:Tahoma,sans-serif;padding:40px;background:#f4f6f8;color:#14213a">
<h2>الصفحة بتتجهز</h2><p>السيرفر بينزّل الأسعار وبيحسب الموجات. ده بياخد كام دقيقة أول مرة، والصفحة هتتحدث لوحدها.</p></body></html>"""


def refresh():
    with lock:
        if state["running"]:
            return
        state["running"] = True
    try:
        if update.run():
            state["last"] = datetime.now(CAIRO)
    finally:
        state["running"] = False


def scheduler():
    done = set()
    while True:
        now = datetime.now(CAIRO)
        key = (now.date(), now.hour)
        if now.hour in HOURS and key not in done:
            done.add(key)
            refresh()
        time.sleep(60)


class H(BaseHTTPRequestHandler):
    def _auth(self):
        if not PASSWORD:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                if base64.b64decode(h[6:]).decode().split(":", 1)[1] == PASSWORD:
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="egx"')
        self.end_headers()
        return False

    def do_GET(self):
        if self.path.startswith("/health"):
            body = f"ok last={state['last']} running={state['running']}".encode()
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(body); return
        if not self._auth():
            return
        if self.path.startswith("/refresh"):
            threading.Thread(target=refresh, daemon=True).start()
            self.send_response(302); self.send_header("Location", "/"); self.end_headers(); return
        page = "egx_sectors.html"
        body = open(page, "rb").read() if os.path.exists(page) else WAIT.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=refresh, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    port = int(os.environ.get("PORT", 8000))
    print(f"شغال على البورت {port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()

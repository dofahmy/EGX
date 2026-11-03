"""
سيرفر صغير لـ Railway:
- بيعرض صفحة موجات القطاعات على الرابط الرئيسي.
- بيحدّث الأسعار والصفحة أول ما يشتغل، وبعدها كل يوم الساعة ٩ الصبح و٤ العصر و٨ بالليل بتوقيت القاهرة (ياهو ساعات بيتأخر في نشر الجلسة).
- لو حطيتي متغير APP_PASSWORD في Railway، الصفحة هتطلب اسم مستخدم (أي اسم) والباسورد ده.
"""
import base64
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

import gold_web
import update

CAIRO = ZoneInfo("Africa/Cairo")
HOURS = {9, 16, 20}
PASSWORD = os.environ.get("APP_PASSWORD", "")
state = {"last": None, "running": False}
hourly = {"proc": None}


def run_hourly(offline=False):
    """بيشغّل اختبار فريم الساعة في الخلفية، والمخرج بيتكتب في hourly_log.txt"""
    import subprocess
    import sys
    if hourly["proc"] is not None and hourly["proc"].poll() is None:
        return
    log = open("hourly_log.txt", "w", encoding="utf-8")
    cmd = [sys.executable, "-u", "egx_hourly.py"] + (["--offline"] if offline else [])
    hourly["proc"] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                      env=dict(os.environ, PYTHONIOENCODING="utf-8"))
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
        try:
            gold_web.run(lambda m: print(m, flush=True))
        except Exception as e:
            print("[دهب] فشل:", e, flush=True)
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
            u = update.status
            body = (f"ok last={state['last']} running={state['running']} prices_until={u['last_price_date']} source={u['source']} "
                    f"tickers_updated={u['tickers_updated']} error={u['error']}\n"
                    f"gold_until={gold_web.status['gold_until']} local_until={gold_web.status['local_until']} "
                    f"local_added={gold_web.status['local_added']} gold_error={gold_web.status['error']}").encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers(); self.wfile.write(body); return
        if not self._auth():
            return
        if self.path.split("?")[0] == "/refresh":
            threading.Thread(target=refresh, daemon=True).start()
            self.send_response(302); self.send_header("Location", "/"); self.end_headers(); return
        if self.path.startswith("/hourly-run"):
            run_hourly(offline="offline" in self.path and os.path.exists("prices_1h.csv"))
            self.send_response(302); self.send_header("Location", "/hourly"); self.end_headers(); return
        if self.path.startswith("/hourly"):
            p = hourly["proc"]
            running = p is not None and p.poll() is None
            txt = open("hourly_log.txt", encoding="utf-8").read() if os.path.exists("hourly_log.txt") else "لسه ماشتغلش. افتحي /hourly-run"
            head = ("<p>شغال... الصفحة بتتحدث كل دقيقة.</p>" if running else
                    '<p>خلص أو مش شغال. <a href="/hourly-run">شغّليه تاني</a> — '
                    '<a href="/hourly-run?offline">من الشموع المحفوظة بس</a></p>')
            import html as _h
            body = (f'<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
                    f'{"<meta http-equiv=refresh content=60>" if running else ""}<title>اختبار فريم الساعة</title></head>'
                    f'<body style="font-family:Tahoma,sans-serif;padding:20px">{head}'
                    f'<pre style="direction:rtl;white-space:pre-wrap;font-size:13px">{_h.escape(txt)}</pre></body></html>').encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(body); return
        if self.path.startswith("/refresh-gold"):
            threading.Thread(target=gold_web.run, daemon=True).start()
            self.send_response(302); self.send_header("Location", "/gold"); self.end_headers(); return
        page = "gold_waves.html" if self.path.startswith("/gold") else "egx_sectors.html"
        if os.path.exists(page):
            body = open(page, "rb").read()
        else:
            err = update.status["error"]
            body = WAIT.replace("</body>", (f'<p style="color:#b4372f">آخر محاولة: {err}</p>' if err else "") + "</body>").encode()
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

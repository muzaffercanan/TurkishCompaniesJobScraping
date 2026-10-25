"""Otomatik tarama: uygulama (siyah pencere) acikken belirli aralikla hizli tarama baslatir.
Ayarlar data/config.json icinde 'auto' anahtarinda durur. 'Bana uygun' yeni ilan bulunursa scanner masaustu bildirimi gonderir."""
import datetime as dt
import threading
import time

from . import db, scanner, search
from .util import log

HOURS = (6, 12, 24, 48)
DEFAULTS = dict(enabled=True, hours=12, notify=True)
RETRY_MINUTES = 60      # son tarama hicbir kaynagi okuyamadiysa (ornegin internet yok) bu kadar sonra tekrar dene
FIRST_CHECK_SECONDS = 90   # uygulama acilinca arayuz yerlessin diye ilk kontrol gecikir
CHECK_SECONDS = 60
FULL_MODES = ('hizli', 'tam')  # yalniz tam yenilemeler sayilir; tek firma ya da yalniz program taramasi sayaci sifirlamaz


def settings():
    cfg = search.load_config().get('auto') or {}
    hours = cfg.get('hours')
    return dict(enabled=bool(cfg.get('enabled', DEFAULTS['enabled'])), hours=hours if hours in HOURS else DEFAULTS['hours'],
                notify=bool(cfg.get('notify', DEFAULTS['notify'])))


def save(patch):
    """Gecerli anahtarlari birlestirip kaydeder; gecersiz degerler yok sayilir. Dondurur: yeni ayarlar."""
    cur = settings()
    if 'enabled' in patch:
        cur['enabled'] = bool(patch['enabled'])
    if 'notify' in patch:
        cur['notify'] = bool(patch['notify'])
    if patch.get('hours') in HOURS:
        cur['hours'] = patch['hours']
    cfg = search.load_config()
    cfg['auto'] = cur
    search.save_config(cfg)
    return cur


def last_full_scan(con):
    r = con.execute(f"SELECT finished, ok FROM scans WHERE mode IN ({','.join('?' * len(FULL_MODES))}) AND finished IS NOT NULL "
                    "ORDER BY id DESC LIMIT 1", FULL_MODES).fetchone()
    return (dt.datetime.fromisoformat(r['finished']), r['ok']) if r else (None, None)


def next_due(cfg, last, ok):
    """Siradaki otomatik tarama zamani; kapaliysa ya da hic tarama yapilmamissa None (ilk tarama elle yapilir)."""
    if not cfg['enabled'] or last is None:
        return None
    return last + (dt.timedelta(minutes=RETRY_MINUTES) if not ok else dt.timedelta(hours=cfg['hours']))


def status(con=None):
    cfg = settings()
    last, ok = last_full_scan(con or db.tl())
    nxt = next_due(cfg, last, ok)
    return dict(cfg, last_at=last.isoformat(timespec='seconds') if last else None, next_at=nxt.isoformat(timespec='seconds') if nxt else None,
                running=bool(scanner.STATE['running']))


def tick(now=None):
    """Zamani gelmisse ve baska tarama calismiyorsa hizli taramayi baslatir. Dondurur: baslatildi mi."""
    if scanner.STATE['running']:
        return False
    con = db.connect()
    try:
        cfg = settings()
        nxt = next_due(cfg, *last_full_scan(con))
    finally:
        con.close()
    return bool(nxt and (now or dt.datetime.now()) >= nxt and scanner.start('hizli', auto=True))


def _loop():
    time.sleep(FIRST_CHECK_SECONDS)
    while True:
        try:
            tick()
        except Exception:  # noqa: BLE001 - zamanlayici hicbir kosulda olmemeli
            log.error('otomatik tarama zamanlayicisi hatasi', exc_info=True)
        time.sleep(CHECK_SECONDS)


def start_thread():
    threading.Thread(target=_loop, name='otomatik-tarama', daemon=True).start()

"""Liste uc noktasi aciklama vermeyen kaynaklarda ilan detayini cek (yalnizca yeni ve Turkiye'deki ilanlar icin;
yuzlerce istekle siteleri yormamak ve engellenmemek icin sinirli)."""
import json
import re
import time

from .util import HttpError, fetch, text

MAX_PER_COMPANY = 40


def _workday(url):
    _, _, t = fetch(url, headers={'Accept': 'application/json'}, timeout=20)
    d = json.loads(t).get('jobPostingInfo', {})
    posted = d.get('startDate') or None
    return text(d.get('jobDescription') or ''), (posted[:10] if posted else None)


def _smartrecruiters(url):
    _, _, t = fetch(url, headers={'Accept': 'application/json'}, timeout=20)
    d = json.loads(t)
    secs = (d.get('jobAd') or {}).get('sections') or {}
    return text(' '.join((v or {}).get('text', '') for v in secs.values())), None


def _page(url):
    """Genel ilan sayfasi: betik/stil cikarilmis duz metin."""
    _, _, h = fetch(url, timeout=15, tries=1, max_bytes=1_500_000)
    h = re.sub(r'<(script|style|nav|footer|header)\b.*?</\1>', ' ', h, flags=re.S | re.I)
    return text(h)[:15000], None


KINDS = {'workday': _workday, 'smartrecruiters': _smartrecruiters, 'page': _page}


def fetch_detail(kind, url):
    """(aciklama, yayin_tarihi) ya da hata durumunda (None, None)"""
    try:
        return KINDS[kind](url)
    except (HttpError, ValueError, KeyError):
        return None, None


def pace():
    time.sleep(0.5)

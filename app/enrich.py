"""Liste uc noktasi aciklama vermeyen kaynaklarda ilan detayini cek (yalnizca yeni ve Turkiye'deki ilanlar icin;
yuzlerce istekle siteleri yormamak ve engellenmemek icin sinirli)."""
import json
import re
import time

from . import generic
from .util import HttpError, fetch, text

MAX_PER_COMPANY = 40


def _workday(url):
    _, _, t = fetch(url, headers={'Accept': 'application/json'}, timeout=20)
    d = json.loads(t).get('jobPostingInfo', {})
    posted = d.get('startDate') or None
    return text(d.get('jobDescription') or ''), (posted[:10] if posted else None), None


def _smartrecruiters(url):
    _, _, t = fetch(url, headers={'Accept': 'application/json'}, timeout=20)
    d = json.loads(t)
    secs = (d.get('jobAd') or {}).get('sections') or {}
    return text(' '.join((v or {}).get('text', '') for v in secs.values())), None, None


def _page(url):
    """Genel ilan sayfasi. Sayfada schema.org JobPosting varsa aciklama, yayin tarihi ve konum oradan (yapilandirilmis);
    yoksa betik/stil cikarilmis duz metin."""
    _, final, h = fetch(url, timeout=15, tries=1, max_bytes=1_500_000, robots=True)
    ld = [j for j in generic.jsonld_jobs(final, h) if j['desc']]
    if ld:
        j = ld[0]
        return j['desc'][:15000], j['posted'], j['location'] or None
    h = re.sub(r'<(script|style|nav|footer|header)\b.*?</\1>', ' ', h, flags=re.S | re.I)
    return text(h)[:15000], None, None


def _rippling(url):
    _, _, t = fetch(url, headers={'Accept': 'application/json'}, timeout=20)
    d = json.loads(t)
    desc = d.get('description')
    body = text(' '.join(str(v) for v in desc.values())) if isinstance(desc, dict) else text(str(desc or ''))
    posted = d.get('createdOn') or None
    return body[:15000], (posted[:10] if posted else None), None


def _eightfold(url):
    d = json.loads(fetch(url, headers={'Accept': 'application/json'}, timeout=20, robots=True)[2]).get('data') or {}
    return text(d.get('jobDescription') or '')[:15000], None, None


def _oracle(url):
    d = (json.loads(fetch(url, headers={'Accept': 'application/json'}, timeout=20)[2]).get('items') or [{}])[0]
    body = ' '.join(d.get(k) or '' for k in ('ExternalDescriptionStr', 'ExternalResponsibilitiesStr', 'ExternalQualificationsStr'))
    posted = d.get('ExternalPostedStartDate') or None
    return text(body)[:15000], (posted[:10] if posted else None), None


KINDS = {'workday': _workday, 'smartrecruiters': _smartrecruiters, 'rippling': _rippling, 'eightfold': _eightfold, 'oracle': _oracle,
         'page': _page}


def fetch_detail(kind, url):
    """(aciklama, yayin_tarihi, konum) ya da hata durumunda (None, None, None). Konum yalnizca sayfa veriyorsa doludur."""
    try:
        return KINDS[kind](url)
    except (HttpError, ValueError, KeyError):
        return None, None, None


def pace():
    time.sleep(0.25)

"""Arama API'si ile web sitesi bulma (sitesi bilinmeyen ya da alan adi artik calismayan firmalar).
Saglayici: Brave Search API (anahtar uygulamanin Firmalar sekmesinden girilir, data/config.json'da saklanir).
Her firma icin tek sorgu; sonuc sayfasi firma adini tasimiyorsa kabul edilmez (sites.verify ile ayni siki kurallar)."""
import json
import os
import time
import urllib.parse

from . import db, sites
from .util import HttpError, core_tokens, fetch, host_of

CONFIG = os.path.join(db.ROOT, 'data', 'config.json')
SKIP_HOSTS = ('linkedin.', 'facebook.', 'instagram.', 'twitter.', 'x.com', 'youtube.', 'wikipedia.', 'crunchbase.', 'kariyer.net',
              'eleman.net', 'secretcv.', 'youthall.', 'glassdoor.', 'indeed.', 'teknopark', 'teknokent', 'cyberpark', 'itucekirdek',
              'ticaretsicil', 'firmasec', 'bilgiedin', 'sirketlistesi', 'kurumsalbilgi', 'tobb.org', 'zoominfo', 'dnb.com', 'apollo.io',
              'rocketreach', 'yelp.', 'google.', 'apple.com', 'play.google', 'tripadvisor', 'sahibinden', 'hepsiburada', 'trendyol.com')


def load_config():
    try:
        with open(CONFIG, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + '.tmp'  # once gecici dosyaya yaz: zamanlayici yarim yazilmis ayar okumasin
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CONFIG)


def brave(query, key):
    url = 'https://api.search.brave.com/res/v1/web/search?' + urllib.parse.urlencode({'q': query, 'country': 'TR', 'count': 8})
    _, _, t = fetch(url, headers={'Accept': 'application/json', 'X-Subscription-Token': key}, timeout=20)
    return [(r.get('url', ''), r.get('title', '')) for r in (json.loads(t).get('web') or {}).get('results', [])]


def candidates_for(rows):
    """Sitesi yok ya da sitesi DNS'te cozulmuyor (alan adi artik yok) firmalar."""
    out = []
    for r in rows:
        if r['merged_into'] or r['status'] in ('ilan-sitesi', 'mukerrer'):
            continue
        dead = r['status'] == 'erisilemedi' and 'NAME_NOT_RESOLVED' in (r['status_note'] or '')
        if not r['website'] or dead:
            out.append(r)
    return out


def run(progress=None, log=print, limit=None):
    cfg = load_config()
    key = (cfg.get('brave_api_key') or '').strip()
    if not key:
        raise RuntimeError('Arama API anahtari girilmemis (Firmalar sekmesi > Arama API anahtari)')
    con = db.tl()
    rows = candidates_for([dict(r) for r in con.execute('SELECT * FROM companies')])
    if limit:
        rows = rows[:limit]
    found = 0
    for i, r in enumerate(rows):
        if progress:
            progress(i, len(rows), r['name'])
        if not core_tokens(r['name']):
            continue
        try:
            results = brave(f'{r["name"]} resmi web sitesi', key)
        except HttpError as e:
            if e.status in (401, 403, 422):
                raise RuntimeError(f'Arama API anahtari gecersiz ya da kota bitti ({e.status})')
            log(f'{r["name"]}: arama hatasi {e}')
            time.sleep(2)
            continue
        site = None
        for url, _title in results:
            h = host_of(url)
            if not h or any(s in h for s in SKIP_HOSTS):
                continue
            ok = sites.verify(f'https://{h}', r['name'])
            if ok:
                site = ok
                break
        if site:
            found += 1
            db.write(con, "UPDATE companies SET website=?, website_source='arama', checked_at=NULL, status=NULL, status_note=NULL, "
                          "career_url=NULL WHERE id=?", (site, r['id']))
            log(f'{r["name"]}: site bulundu {site}')
        time.sleep(1.1)  # saglayicinin saniyelik sinirina uy
    if progress:
        progress(len(rows), len(rows), '')
    log(f'arama bitti: {len(rows)} firmanin {found} tanesine site bulundu')
    return found, len(rows)

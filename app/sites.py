"""Web sitesi bilinmeyen firmalar icin site kesfi.
1) Teknokent rehberleri (ITU Cekirdek, Marmara Teknokent) -> ad/site eslesmesi
2) Alan adi tahmini + dogrulama (sayfada firma adi gecmeli, park edilmis alan adi olmamali)
Kullanim: python -m app.sites"""
import re
import socket
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import db
from .util import HttpError, core_tokens, fetch, name_key, norm, text

SOCIAL = re.compile(r'facebook|twitter|instagram|linkedin|youtube|x\.com|wa\.me|google|apple\.com|bunny\.net|itucekirdek|marmarateknokent')
PARKED = re.compile(r'domain (is )?for sale|bu alan ad[ıi] sat[ıi]l[ıi]k|satılık alan adı|parked (free|domain)|godaddy|sedo\.com|'
                    r'dan\.com|hugedomains|domain parking|this domain|alan adı tescil|hosting hesabı|coming soon|yakında hizmetinizde|'
                    r'index of /|default web page|apache2 (ubuntu|debian) default|it works!', re.I)


def harvest_itu():
    out, page = [], 1
    while page < 60:
        try:
            _, _, t = fetch(f'https://girisimler.itucekirdek.com/?page={page}')
        except HttpError:
            break
        cards = t.split('rounded-lg shadow-lg overflow-hidden')[1:]
        if not cards:
            break
        for c in cards:
            h3 = re.search(r'<h3[^>]*>(.*?)</h3>', c, flags=re.S)
            site = next((u for u in re.findall(r'href="(https?://[^"]+)"[^>]*target="_blank"', c) if not SOCIAL.search(u)), None)
            if h3 and site:
                out.append((text(h3.group(1)), site))
        page += 1
    return out


def harvest_marmara():
    _, _, t = fetch('https://marmarateknokent.com.tr/firmalar/')
    out = []
    for site, name in re.findall(r'elementor-post__title">\s*<a href="([^"]+)"[^>]*>(.*?)</a>', t, flags=re.S):
        site = site.split('#')[0]
        if site.startswith('http') and not SOCIAL.search(site):
            out.append((text(name), site))
    return out


def _match(con, pairs, source):
    """Rehberden gelen (ad, site) ciftlerini sitesi olmayan firmalarla eslestir."""
    rows = con.execute('SELECT id, name FROM companies WHERE website IS NULL').fetchall()
    by_key, by_first = {}, {}
    for r in rows:
        by_key.setdefault(name_key(r['name']), []).append(r['id'])
        c = core_tokens(r['name'])
        if c and len(c[0]) >= 5:
            by_first.setdefault(c[0], []).append(r['id'])
    n = 0
    for name, site in pairs:
        ids = by_key.get(name_key(name))
        if not ids:
            c = core_tokens(name)
            ids = by_first.get(c[0]) if c and len(c[0]) >= 5 else None
        if ids and len(ids) == 1:
            db.write(con, 'UPDATE companies SET website=?, website_source=? WHERE id=? AND website IS NULL', (site, source, ids[0]))
            n += 1
    return n


TLDS = ('.com.tr', '.com', '.io', '.ai', '.net', '.co', '.tech', '.app', '.net.tr')


def candidates(name):
    c = core_tokens(name)
    if not c or len(c[0]) < 3:
        return []
    stems = [c[0]]
    if len(c) > 1:
        stems += [c[0] + c[1], c[0] + '-' + c[1]]
    out = []
    for s in stems:
        for tld in TLDS:
            out.append(f'https://{s}{tld}')
            if tld in ('.com.tr', '.com') and len(out) > 14:
                break
    return out[:16]


def resolves(url):
    try:
        socket.getaddrinfo(urllib.parse.urlparse(url).netloc, 443)
        return True
    except OSError:
        return False


def verify(url, name):
    """Sayfa gercekten bu firmaya mi ait? Ad gecmeli, park sayfasi olmamali."""
    if not resolves(url):
        return None
    try:
        st, final, t = fetch(url, timeout=8, tries=1, max_bytes=400_000)
    except HttpError:
        return None
    if st != 200 or PARKED.search(t[:60000]):
        return None
    c = core_tokens(name)
    body = norm(text(t[:200000]))
    title = norm(text((re.search(r'<title[^>]*>(.*?)</title>', t, flags=re.S | re.I) or [None, ''])[1]))
    if not ok_page(c, title, body, final):
        return None
    return final


def _has(tok, s):
    return re.search(rf'(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])', s) is not None


FOREIGN_PATH = re.compile(r'/(sv|de|fr|es|it|nl|pl|ru|pt|ja|zh|ar|fi|da|no|cs|hu|ro)(/|$)', re.I)


def ok_page(c, title, body, final_url):
    """Siki dogrulama: kisa/genel kelimeler baska sitelere denk gelmesin."""
    if not c or FOREIGN_PATH.search(urllib.parse.urlparse(final_url).path):
        return False
    first = c[0]
    if len(c) >= 2:
        # iki ayirt edici kelime de sayfada (tam kelime) gecmeli, en az biri baslikta ya da ikisi birlikte metinde
        both_body = _has(first, body) and _has(c[1], body)
        return both_body and (_has(first, title) or _has(c[1], title) or len(first) >= 6)
    return (len(first) >= 5 and _has(first, title)) or (len(first) >= 7 and _has(first, body))


def guess_one(row):
    for u in candidates(row['name']):
        ok = verify(u, row['name'])
        if ok:
            return row['id'], ok
    return row['id'], None


def run(log=print):
    con = db.connect()
    db.import_excel(con)
    before = con.execute('SELECT COUNT(*) FROM companies WHERE website IS NULL').fetchone()[0]
    log(f'sitesi bilinmeyen firma: {before}')
    for label, fn, src in (('ITU Cekirdek', harvest_itu, 'rehber:itu'), ('Marmara Teknokent', harvest_marmara, 'rehber:marmara')):
        try:
            pairs = fn()
            log(f'{label}: {len(pairs)} ad/site cifti, eslesen {_match(con, pairs, src)}')
        except HttpError as e:
            log(f'{label}: HATA {e}')
    rows = con.execute('SELECT id, name FROM companies WHERE website IS NULL').fetchall()
    log(f'alan adi tahmini deneniyor: {len(rows)} firma')
    found = 0
    with ThreadPoolExecutor(32) as ex:
        for cid, site in ex.map(guess_one, rows):
            if site:
                found += 1
                db.write(con, "UPDATE companies SET website=?, website_source='tahmin' WHERE id=?", (site, cid))
    after = con.execute('SELECT COUNT(*) FROM companies WHERE website IS NULL').fetchone()[0]
    log(f'tahminle bulunan: {found} | hala sitesi bilinmeyen: {after} (baslangic {before})')
    return before, after


GAME_WORDS = {'games', 'game', 'studio', 'studios', 'studyo', 'oyun', 'entertainment', 'interactive', 'play', 'technology',
              'technologies', 'teknoloji', 'teknolojileri', 'publishing', 'labs', 'softworks', 'inc', 'gaming', 'global', 'turkey'}


def candidates_game(name):
    """Oyun stüdyolari icin: loomgames.com, loom.games, loomgames.io, loomstudio.com, loom.gg ..."""
    name = re.sub(r'\(.*?\)|/.*$', ' ', name or '')
    toks = [t for t in re.split(r'[^a-z0-9]+', norm(name)) if t]
    core = [t for t in toks if t not in GAME_WORDS and t not in ('ve', 'as', 'ltd', 'sti')]
    if not core:
        return []
    c = ''.join(core[:2])
    suf = [t for t in toks if t in ('games', 'game', 'studio', 'studios')][:1]
    stems = [c + suf[0], c + '-' + suf[0]] if suf else []
    stems += [c + 'games', c]
    out = []
    for st in dict.fromkeys(stems):
        for tld in ('.com', '.games', '.io', '.gg', '.co', '.com.tr', '.net', '.studio'):
            out.append(f'https://{st}{tld}')
    return out[:18]


def verify_game(url, name):
    if not resolves(url):
        return None
    try:
        st, final, t = fetch(url, timeout=8, tries=1, max_bytes=400_000)
    except HttpError:
        return None
    if st != 200 or PARKED.search(t[:60000]):
        return None
    body = norm(text(t[:200000]))
    title = norm(text((re.search(r'<title[^>]*>(.*?)</title>', t, flags=re.S | re.I) or [None, ''])[1]))
    core = [x for x in re.split(r'[^a-z0-9]+', norm(re.sub(r'\(.*?\)|/.*$', ' ', name))) if x and x not in GAME_WORDS]
    if not core or FOREIGN_PATH.search(urllib.parse.urlparse(final).path):
        return None
    gamey = re.search(r'(?<![a-z])(game|games|oyun|play|studio|mobile)(?![a-z])', title + ' ' + body[:20000])
    return final if (_has(core[0], title) or (len(core[0]) >= 6 and _has(core[0], body))) and gamey else None


def guess_game(row):
    for u in candidates_game(row['name']):
        ok = verify_game(u, row['name'])
        if ok:
            return row['id'], ok
    return row['id'], None


def run_games(log=print):
    con = db.connect()
    rows = con.execute("SELECT id, name FROM companies WHERE category='Oyun' AND website IS NULL").fetchall()
    found = 0
    with ThreadPoolExecutor(24) as ex:
        for cid, site in ex.map(guess_game, rows):
            if site:
                found += 1
                db.write(con, "UPDATE companies SET website=?, website_source='tahmin' WHERE id=?", (site, cid))
    log(f'oyun firmalari: {len(rows)} sitesiz firmanin {found} tanesine site bulundu')


def reverify(log=print):
    """Tahminle bulunmus siteleri siki kurallarla yeniden dogrula; gecemeyenleri sil ve yeniden tahmin et."""
    con = db.connect()
    rows = con.execute("SELECT id, name, website FROM companies WHERE website_source='tahmin'").fetchall()

    def chk(r):
        return r['id'], verify(r['website'], r['name'])
    dropped = 0
    with ThreadPoolExecutor(32) as ex:
        for cid, ok in ex.map(chk, rows):
            if not ok:
                dropped += 1
                db.write(con, 'UPDATE companies SET website=NULL, website_source=NULL WHERE id=?', (cid,))
    log(f'yeniden dogrulama: {len(rows)} tahminin {dropped} tanesi elendi')
    rows = con.execute('SELECT id, name FROM companies WHERE website IS NULL').fetchall()
    found = 0
    with ThreadPoolExecutor(32) as ex:
        for cid, site in ex.map(guess_one, rows):
            if site:
                found += 1
                db.write(con, "UPDATE companies SET website=?, website_source='tahmin' WHERE id=?", (site, cid))
    left = con.execute('SELECT COUNT(*) FROM companies WHERE website IS NULL').fetchone()[0]
    log(f'yeniden tahminle bulunan: {found} | sitesi bilinmeyen: {left}')


if __name__ == '__main__':
    if '--reverify' in sys.argv:
        reverify()
    elif '--games' in sys.argv:
        run_games()
    else:
        run()
    sys.exit(0)

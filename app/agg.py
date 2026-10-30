"""Is platformlarinin genel aramalari: Turkiye'de ilan veren (listemizde olan ya da olmayan) firmalari bulur.
  workable-tr     : jobs.workable.com aramasi (location=Turkey). Ilan basina firma adi/sitesi gelir ama firmanin Workable hesap
                    adi gelmez; bu yuzden aramanin kendisi kaynaktir: ilanlar firmalara dagitilir (scanner.scan_aggregators).
  smartrecruiters : jobs.smartrecruiters.com aramasi Turkiye sehirleriyle; firma kimligi gelir. Yeni firmalar SmartRecruiters
                    hesabiyla (yalnizca Turkiye ilanlari) eklenir, ilanlari normal okuyucu okur (scanner.discover_smartrecruiters).
Ikisi de herkese acik, anahtarsiz uc noktalar; robots.txt'ye uyulur."""
import json
import re
import time
import urllib.parse

from . import ats
from .util import TR_PLACE, fetch, host_of, norm, text


def workable_turkey(max_pages=60):
    """[{id,title,location,team,url,posted,remote,desc, company:{key,name,website}}] - yalnizca konumu Turkiye olanlar."""
    out, tok, pages = [], None, 0
    while pages < max_pages:
        u = 'https://jobs.workable.com/api/v1/jobs?location=Turkey' + (f'&pageToken={urllib.parse.quote(tok)}' if tok else '')
        d = json.loads(fetch(u, headers={'Accept': 'application/json'}, robots=True)[2])
        for j in d.get('jobs') or []:
            loc = j.get('location') or {}
            where = ', '.join(x for x in (loc.get('city'), loc.get('subregion'), loc.get('countryName')) if x) or ', '.join(j.get('locations') or [])
            if not TR_PLACE.search(norm(where)):
                continue
            co = j.get('company') or {}
            body = ' '.join(j.get(k) or '' for k in ('description', 'requirementsSection', 'benefitsSection'))
            out.append(dict(id=j['id'], title=j.get('title', ''), location=where, team=j.get('department') or '', url=j.get('url', ''),
                            posted=ats._d(j.get('created')), remote=j.get('workplace') == 'remote', desc=text(body)[:15000],
                            company=dict(key=co.get('id') or co.get('title'), name=(co.get('title') or '').strip(), website=co.get('website') or '')))
        tok, pages = d.get('nextPageToken'), pages + 1
        if not tok or not d.get('jobs'):
            break
        time.sleep(0.5)
    return out


SR_TERMS = ('Turkey', 'Türkiye', 'Istanbul', 'Ankara', 'Izmir', 'Kocaeli', 'Bursa', 'Antalya', 'Gebze', 'Tekirdag', 'Eskisehir')


def smartrecruiters_companies(max_per_term=1000):
    """SmartRecruiters genel aramasinda Turkiye'de ilani gorunen firmalar: {kimlik: ad}. Arama konumu degil metni eslestirir;
    ilanin ulkesi 'tr' olanlar sayilir. Firmalarin Turkiye ilan sayisi okuyucunun ulke filtresiyle ayrica dogrulanir."""
    found = {}
    for term in SR_TERMS:
        off = 0
        while off < max_per_term:
            d = json.loads(fetch(f'https://jobs.smartrecruiters.com/sr-jobs/search?keyword={urllib.parse.quote(term)}&limit=100&offset={off}')[2])
            rows = d.get('content') or []
            for j in rows:
                if (j.get('location') or {}).get('country') == 'tr':
                    co = j.get('company') or {}
                    found.setdefault(co.get('identifier'), (co.get('name') or co.get('identifier') or '').strip())
            off += len(rows)
            if not rows or off >= (d.get('totalFound') or 0):
                break
            time.sleep(0.3)
    found.pop(None, None)
    return found


# Listede olmayan firma ancak basliginda yazilim/teknik rol gecen bir ilani varsa eklenir. scanner.TECH'ten dar: 'analyst',
# 'engineer', 'digital', 'IT' tek basina yetmez (insaat muhendisi, IT musteri hizmetleri, 'AI trainer' ilanlari elensin).
SOFTWARE = re.compile(r'software|yazilim|developer|gelistirici|programmer|programci|backend|back-end|frontend|front-end|full.?stack|'
                      r'devops|\bsre\b|data (?:engineer|scientist|analyst)|veri (?:bilim|muhendis|analist)|machine learning|'
                      r'\b(?:ml|ai|llm) engineer|yapay zeka|\bqa\b|test (?:engineer|automation|otomasyon)|mobile|android|\bios\b|'
                      r'embedded|firmware|gomulu|cyber|siber|security engineer|cloud engineer|game (?:developer|designer|programmer)|'
                      r'oyun (?:gelistir|tasarim)|\bunity\b|unreal|(?:server|platform|network|site reliability) engineer|database|'
                      r'\.net\b|\bjava\b|python|golang|react|node\.?js')


def is_software(title):
    return bool(SOFTWARE.search(norm(title)))


def _key(name):
    """Eslestirme anahtari: hukuki ekler (Ltd, A.S., Inc...) atilir, digerleri kalir ('Digital Planet' != 'PLANET S.A.')."""
    from .util import LEGAL, tokens
    return ' '.join(t for t in tokens(re.sub(r'\(.*?\)', ' ', name or '')) if t not in LEGAL)


def _label(host):
    """Alan adinin firma parcasi: 'vertigogames.co' ve 'vertigogames.com' -> 'vertigogames'."""
    parts = [p for p in host.split('.') if p not in ('www', 'com', 'co', 'net', 'org', 'io', 'tr', 'gr', 'ch', 'uk', 'ai', 'app', 'games')]
    return parts[-1] if parts else ''


def company_index(con):
    """Listemizdeki firmalari eslestirmek icin: (site alan adi -> satir, ad anahtari -> satir, alan adi parcasi -> satir)."""
    by_host, by_name, by_label = {}, {}, {}
    for r in con.execute('SELECT * FROM companies WHERE merged_into IS NULL'):
        h = host_of(r['website'] or '')
        if h:
            by_host.setdefault(h, r)
            if len(_label(h)) >= 8:  # kisa parcalar (planet, games) baska firmalarla cakisabilir
                by_label.setdefault(_label(h), r)
        by_name.setdefault(_key(r['name']), r)
    return by_host, by_name, by_label


def match(company, index):
    """Ayni site, ayni (hukuki eksiz) ad ya da ayni uzun alan adi parcasi."""
    by_host, by_name, by_label = index
    h = host_of(company.get('website') or '')
    return ((by_host.get(h) if h else None) or by_name.get(_key(company.get('name') or ''))
            or (by_label.get(_label(h)) if h and len(_label(h)) >= 8 else None))


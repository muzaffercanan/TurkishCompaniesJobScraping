"""Firmaya ozel ilan okuyucular (ATS'i olmayan kariyer portallari).
Her okuyucu [{id,title,location,team,url,posted,remote}] dondurur. Hicbiri login gerektirmez, yalnizca herkese acik sayfa/uc noktalari okunur.
Yeni firma eklemek: bir fonksiyon yaz, REGISTRY'e ekle, ats_manual.json'a {"firma":..,"ats":"custom","slug":"<REGISTRY anahtari>"} ekle."""
import datetime as dt, html, json, re, time, urllib.parse

from . import dom
from .util import fetch


def _open(url, data=None, method=None, headers=None, tries=2):
    """Ortak HTTP katmani (sertifika dogrulama, sunucu basina sinir, 429 beklemesi). Firma sitesi oldugu icin robots.txt'ye uyulur."""
    return fetch(url, data=data, method=method, headers=headers, timeout=30, tries=tries, max_bytes=20_000_000, robots=True)[2]


def _txt(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


def _tr_title(s):
    """TAMAMEN BUYUK HARFLI basligi Turkce kurallarina gore 'Bas Harfi Buyuk' yap (i/I ve nokta sorunu olmadan)."""
    if not s or s != s.upper():
        return s
    if not re.search(r'[ÇĞİÖŞÜ]', s):  # Turkce ozel harf yok: Ingilizce olabilir (ASSOCIATE -> Associate, "ı" olmasin)
        return ' '.join(w[:1] + w[1:].lower() if len(w) > 2 else w for w in s.split(' '))
    def word(w):
        lw = w.replace('İ', 'i').replace('I', 'ı').lower()
        return {'i': 'İ', 'ı': 'I'}.get(lw[:1], lw[:1].upper()) + lw[1:] if len(lw) > 2 else w
    return ' '.join(word(w) for w in s.split(' '))


def _dmy(s):
    """'9.09.2026' veya '15.09.2026' -> '2026-09-09'"""
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(20\d\d)', s or '')
    return f'{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}' if m else None


# --------------------------------------------------------------------------- Turkcell
def turkcell():
    base = 'https://kariyerim.turkcell.com.tr/_layouts/15/Career.Sharepoint/Handlers/JobPostingHandler.ashx'
    q = urllib.parse.urlencode({'Operation': 'GetPosts', 'JobName': '', 'Team': '', 'Location': '', 'PositionType': '', 'PageIndex': 0,
                                'SortBy': 'JobName', 'IsAscending': 'false'})
    rows = json.loads(_open(f'{base}?{q}', data=b'', method='POST', headers={'X-Requested-With': 'XMLHttpRequest'}))['result']
    out = []
    for r in rows:
        title = re.sub(r'^\d+\s*-\s*', '', r.get('JobName', '')).strip()
        if (r.get('Title') or '').strip() == 'Yeni Mezun':
            title += ' (Yeni Mezun)'
        if 'Yarı' in (r.get('PositionType') or ''):
            title += ' (Yarı zamanlı)'
        out.append(dict(id=str(r['JobID']), title=_tr_title(title), location=f"{r.get('Location', '')}, Türkiye".strip(', '),
                        team=r.get('Team') or '', url=r.get('PortalURL') or 'https://kariyerim.turkcell.com.tr/kariyer-firsatlari',
                        posted=(r.get('JobPublishDate') or '')[:10] or None, remote=False,
                        desc=_txt((r.get('StringJobQualification') or '') + ' ' + (r.get('StringJobDescription') or ''))))
    return out


# --------------------------------------------------------------------------- Garanti BBVA
def garanti():
    """Ilan kartlari (div.job-card): baslik h2, adres /ilan/<R..>/<no>/..., sirket .job-card__company, konum .job-card__location.
    Not: kariyer.garantibbva.com.tr robots.txt'si arama motorlari disindaki botlari engelliyor; izin verene kadar okunmaz."""
    base = 'https://kariyer.garantibbva.com.tr'
    out = []
    for card in dom.parse(_open(base + '/tum-kariyer-firsatlari')).find_all('div', cls='job-card'):
        link = next((a for a in card.find_all('a') if re.match(r'/ilan/R\d+/\d+/', a.get('href', ''))), None)
        if not link:
            continue
        rid, no = link.get('href').split('/')[2:4]
        h2, company, loc, date = card.find('h2'), card.find(cls='job-card__company'), card.find(cls='job-card__location'), card.find(cls='job-card__date')
        out.append(dict(id=f'{rid}/{no}', title=h2.text() if h2 else no, location=loc.text()[:60] if loc else '',
                        team=company.text() if company else '', url=base + link.get('href'), posted=_dmy(date.text() if date else card.text()),
                        remote=False))
    return out


# --------------------------------------------------------------------------- HAVELSAN
def havelsan():
    d = json.loads(_open('https://gwkariyer.havelsan.com.tr/hr-all/applicationService/application/getDashboardAnnouncementsJson'))
    out = []
    for a in d:
        if a.get('status') != 'ACTIVE' or a.get('hidden'):
            continue
        det = a.get('announcementDetailForApplicantModel') or {}
        bd = a.get('beginDate') or [None]
        posted = f'{bd[0]}-{bd[1]:02d}-{bd[2]:02d}' if len(bd) == 3 else None
        out.append(dict(id=str(det.get('id') or a.get('announcementName')), title=_tr_title((a.get('announcementName') or '').strip()),
                        location='Ankara, Türkiye', team=a.get('workingType') or '',
                        url='https://kariyer.havelsan.com.tr/#/humanresources/recruitment/public/announcement', posted=posted, remote=False,
                        desc=_txt(det.get('detail') or '')))
    return out


# --------------------------------------------------------------------------- Turk Telekom (RSS)
def turktelekom():
    x = _open('https://basvuru.turktelekomkariyer.com.tr/rss/ilan.aspx')
    out = []
    for it in re.findall(r'<item>(.*?)</item>', x, flags=re.S):
        g = lambda tag: _txt((re.search(rf'<{tag}[^>]*>(.*?)</{tag}>', it, flags=re.S) or [None, ''])[1])
        pub = g('pubDate')
        try:
            posted = dt.datetime.strptime(pub[:25], '%a, %d %b %Y %H:%M:%S').strftime('%Y-%m-%d')
        except ValueError:
            posted = _dmy(pub)
        out.append(dict(id=g('guid') or g('link'), title=g('title'), location=g('location') or 'Türkiye', team=g('category'), url=g('link'), posted=posted, remote=False))
    return out


# --------------------------------------------------------------------------- Amazon
def amazon():
    out, off = [], 0
    while True:
        d = json.loads(_open(f'https://www.amazon.jobs/en/search.json?result_limit=100&offset={off}&sort=recent&normalized_country_code%5B%5D=TUR'))
        jobs = d.get('jobs', [])
        for j in jobs:
            title = j.get('title', '')
            if j.get('is_intern'):
                title += ' (Intern)'
            if j.get('university_job'):
                title += ' (University)'
            try:
                posted = dt.datetime.strptime(re.sub(r'\s+', ' ', j.get('posted_date', '')), '%B %d, %Y').strftime('%Y-%m-%d')
            except ValueError:
                posted = None
            out.append(dict(id=str(j.get('id_icims') or j.get('id')), title=title, location=j.get('normalized_location') or j.get('location', ''),
                            team=j.get('job_category') or j.get('team') or '', url='https://www.amazon.jobs' + j.get('job_path', ''), posted=posted, remote=False,
                            desc=_txt(' '.join(j.get(k) or '' for k in ('basic_qualifications', 'preferred_qualifications', 'description_short')))))
        off += len(jobs)
        if not jobs or off >= d.get('hits', 0):
            return out
        time.sleep(0.5)


# --------------------------------------------------------------------------- Roketsan
def roketsan():
    """Ilan tablosu: her satirda a.PL (baslik, /<kod>.job), span.location ve yayin tarihi hucresi."""
    base = 'https://kariyer.roketsan.com.tr'
    out = []
    for a in dom.parse(_open(base + '/jobs')).find_all('a', cls='PL'):
        m = re.match(r'/([a-z0-9]+)\.job$', a.get('href', ''))
        row = a.closest('tr')
        if not m or row is None:
            continue
        loc, date = row.find('span', cls='location'), row.find('td', align='center')
        city = loc.text() if loc else ''  # bazi satirlarda konum yok (eski regex bu satiri sonraki ilanla birlestiriyordu)
        out.append(dict(id=m.group(1), title=a.text(), location=f'{city}, Türkiye' if city else 'Türkiye', team='', url=base + a.get('href'),
                        posted=_dmy(date.text() if date else ''), remote=False))
    return out


# --------------------------------------------------------------------------- Baykar
def baykar():
    base = 'https://kariyer.baykartech.com'
    h = {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
    out = []
    for typ, tag in ((1, ''), (304, ' (Staj programı)')):
        page = 1
        while True:
            d = json.loads(_open(f'{base}/tr/basvuru/serializerProgram/?page={page}&search=&program_category_ids=&type={typ}', headers=h))
            for r in d.get('results', []):
                if r.get('stop_application') or r.get('visible') is False:
                    continue
                title = (r.get('text') or r.get('title_text') or '').strip()  # text = pozisyon adi, title_text = unvan turu
                out.append(dict(id=f"{typ}:{r['id']}", title=title + tag, location='Türkiye', team=(r.get('category') or {}).get('text', ''),
                                url=f"{base}/tr/acik-pozisyonlar/detay/{r.get('new_slug')}", posted=None, remote=False))
            if not d.get('next'):
                break
            page += 1
            time.sleep(0.4)
    return out


REGISTRY = {'turkcell': turkcell, 'garanti': garanti, 'havelsan': havelsan, 'turktelekom': turktelekom, 'amazon': amazon, 'roketsan': roketsan, 'baykar': baykar}

if __name__ == '__main__':  # python -m app.custom [turkcell ...]  -> her okuyucuyu canli dene
    import sys
    for name, fn in REGISTRY.items():
        if len(sys.argv) > 1 and name not in sys.argv[1:]:
            continue
        try:
            rows = fn()
            print(f'## {name}: {len(rows)} ilan')
            for r in rows[:3]:
                print('   ', {k: (str(v)[:48] if v is not None else None) for k, v in r.items() if k != 'remote'})
        except Exception as e:  # noqa
            print(f'## {name}: HATA {e}')

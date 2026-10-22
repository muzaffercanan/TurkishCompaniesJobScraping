"""Firmaya ozel ilan okuyucular (ATS'i olmayan kariyer portallari).
Her okuyucu [{id,title,location,team,url,posted,remote}] dondurur. Hicbiri login gerektirmez, yalnizca herkese acik sayfa/uc noktalari okunur.
Yeni firma eklemek: bir fonksiyon yaz, REGISTRY'e ekle, ats_manual.json'a {"firma":..,"ats":"custom","slug":"<REGISTRY anahtari>"} ekle."""
import datetime as dt, html, json, re, ssl, time, urllib.parse, urllib.request

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0 (compatible; ilan-izleyici)', 'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8'}


def _open(url, data=None, method=None, headers=None, tries=2):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:  # noqa
            last = e
            time.sleep(1)
    raise RuntimeError(f'{type(last).__name__}: {last}')


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
                        posted=(r.get('JobPublishDate') or '')[:10] or None, remote=False))
    return out


# --------------------------------------------------------------------------- Garanti BBVA
def garanti():
    base = 'https://kariyer.garantibbva.com.tr'
    t = _open(base + '/tum-kariyer-firsatlari')
    out = []
    for c in t.split('job-card job-card--white job-card-jobs-content')[1:]:
        m = re.search(r'href=(/ilan/(R\d+)/(\d+)/[^ >]+)', c)
        if not m:
            continue
        h2 = re.search(r'<h2[^>]*>(.*?)</h2>', c, flags=re.S)
        company = re.search(r'class="?o-link o-link--primary"?>(.*?)</a>', c, flags=re.S)
        after = c[company.end():] if company else ''
        # sirket adindan sonra gelen ilk kisa metin konumdur: "Ankara", "Istanbul (Hibrit)" ...
        parts = [p for p in (_txt(x) for x in re.split(r'<[^>]+>', after)) if p]
        loc = parts[0] if parts and len(parts[0]) < 60 else ''
        title = _txt(h2.group(1)) if h2 else m.group(3)
        comp = _txt(company.group(1)) if company else ''
        out.append(dict(id=m.group(2) + '/' + m.group(3), title=title, location=loc, team=comp, url=base + m.group(1), posted=_dmy(_txt(c)), remote=False))
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
                        url='https://kariyer.havelsan.com.tr/#/humanresources/recruitment/public/announcement', posted=posted, remote=False))
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
                            team=j.get('job_category') or j.get('team') or '', url='https://www.amazon.jobs' + j.get('job_path', ''), posted=posted, remote=False))
        off += len(jobs)
        if not jobs or off >= d.get('hits', 0):
            return out
        time.sleep(0.5)


# --------------------------------------------------------------------------- Roketsan
def roketsan():
    base = 'https://kariyer.roketsan.com.tr'
    t = _open(base + '/jobs')
    out = []
    for m in re.finditer(r'<a href="(/([a-z0-9]+)\.job)" class="PL">(.*?)</a><span class=location>(.*?)</span>.*?<td align="center">\s*([^<]*?)\s*</td>', t, flags=re.S):
        out.append(dict(id=m.group(2), title=_txt(m.group(3)), location=_txt(m.group(4)) + ', Türkiye', team='', url=base + m.group(1), posted=_dmy(m.group(5)), remote=False))
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

if __name__ == '__main__':  # python scripts/adapters.py  -> her okuyucuyu dene
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

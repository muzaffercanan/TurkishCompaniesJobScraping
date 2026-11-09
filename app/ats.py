"""ATS (aday takip sistemi) tespiti ve okuyucular.
detect(text) -> (ats, slug, extra) ; fetch_jobs(ats, slug, extra) -> [ {id,title,location,team,url,posted,remote} ]
Okuyuculari olan ATS'ler herkese acik, anahtarsiz uc noktalar kullanir. Okuyucusu olmayanlar 'generic' ayristiriciya duser."""
import datetime as dt
import json
import re
import time
import urllib.parse

from . import dom
from .util import TR_PLACE, HttpError, fetch, fetch_json, norm, text


class Jobs(list):
    """Okuyucu sonucu ve ek bilgisi. note: firma durum notuna eklenir. confirmed: kaynak listeyi dogruladi; bos olsa bile
    okuyucu bozulmasi degildir, onceki ilanlar kapatilabilir (or. Workday ulke filtresinde Turkiye hic yok)."""

    def __init__(self, items=(), note='', confirmed=False):
        super().__init__(items)
        self.note, self.confirmed = note, confirmed


def _d(s):
    m = re.match(r'(\d{4}-\d{2}-\d{2})', s or '')
    return m.group(1) if m else None


def _ms(v):
    try:
        return dt.datetime.fromtimestamp(int(v) / 1000).strftime('%Y-%m-%d')
    except (TypeError, ValueError, OSError):
        return None


# ------------------------------------------------------------------ tespit kaliplari
# (ats, regex) - ilk grup slug, varsa ikinci grup ek bilgi (or. workday site adi)
PATTERNS = [
    ('lever', r'(?:jobs|api)\.lever\.co/(?:v0/postings/)?([A-Za-z0-9_.-]+)'),
    ('greenhouse', r'(?:boards|job-boards)(?:-api)?\.greenhouse\.io/(?:v1/boards/|embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)'),
    ('greenhouse', r'greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)'),
    ('ashby', r'jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)'),
    ('workable', r'apply\.workable\.com/([A-Za-z0-9_-]+)'),
    ('workable', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.workable\.com'),
    ('smartrecruiters', r'(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)'),
    ('recruitee', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.recruitee\.com'),
    ('personio', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.jobs\.personio\.(de|com)'),
    ('bamboohr', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.bamboohr\.com'),
    ('breezy', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.breezy\.hr'),
    ('pinpoint', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.pinpointhq\.com'),
    ('teamtailor', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.teamtailor\.com'),
    ('workday', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)'),
    ('successfactors', r'(career\d*\.successfactors\.(?:com|eu))/career\?company=([A-Za-z0-9_-]+)'),
    ('rippling', r'ats\.rippling\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)/jobs'),
    ('talentics', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.talentics\.app'),
    # okuyucusu olmayanlar (genel ayristirici kullanilir, ama hangi sistem oldugu kaydedilir)
    ('comeet', r'comeet\.(?:co|com)/jobs/([A-Za-z0-9_-]+)'),
    ('icims', r'(careers?-[A-Za-z0-9-]{1,63})\.icims\.com'),
    ('jobvite', r'jobs\.jobvite\.com/([A-Za-z0-9_-]+)'),
    ('join', r'join\.com/companies/([A-Za-z0-9_-]+)'),
    ('homerun', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.homerun\.co'),
    ('manatal', r'careers-page\.com/([A-Za-z0-9_-]+)'),
    ('zohorecruit', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.zohorecruit\.(?:com|eu)'),
    ('freshteam', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.freshteam\.com'),
    ('jazzhr', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.applytojob\.com'),
    ('oracle', r'(?<![A-Za-z0-9.-])([A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,4}\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z]{2}/sites/([A-Za-z0-9_-]+)'),
    ('kolayik', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63}\.)?kolayik\.com'),
    ('peoplise', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63}\.)?peoplise\.com'),
    ('peoplebox', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.peoplebox\.biz'),
    ('hrpeak', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.hrpeak\.com'),
    ('hrpanda', r'(?<![A-Za-z0-9-])([A-Za-z0-9-]{1,63})\.hrpanda\.co(?![A-Za-z0-9])'),
    ('kariyer.net', r'kariyer\.net/(?:firma-profil|is-ilanlari?)/([A-Za-z0-9_-]+)'),
    ('linkedin', r'linkedin\.com/company/([A-Za-z0-9_-]+)/jobs'),
]
PATTERNS = [(a, re.compile(p, re.I)) for a, p in PATTERNS]
BAD_SLUG = {'embed', 'api', 'v1', 'jobs', 'job', 'www', 'careers', 'career', 'apply', 'static', 'assets', 'cdn', 'js', 'images',
            'app', 'help', 'support', 'blog', 'en', 'tr', 'de', 'careers-analytics', 'analytics', 'widget', 'portal',
            'dashboard', 'uploads'}
READERS = {'lever', 'greenhouse', 'ashby', 'workable', 'smartrecruiters', 'recruitee', 'personio', 'bamboohr', 'breezy',
           'pinpoint', 'teamtailor', 'workday', 'successfactors', 'manatal', 'jazzhr', 'rippling', 'eightfold', 'talentbrew', 'talentics', 'oracle', 'phenom', 'avature', 'hrpanda'}
REDIRECT_ONLY = {'kariyer.net', 'linkedin'}


def has_reader(ats, extra=None):
    """Bu ATS icin calisan bir okuyucu var mi? (SuccessFactors'un yalnizca RMK sitelerini okuyabiliyoruz)"""
    if ats == 'successfactors':
        return bool(extra) and 'successfactors' not in extra
    return ats in READERS


_DATA_URI = re.compile(r'data:[a-z/+.-]+;base64,[A-Za-z0-9+/=]{64,}|[A-Za-z0-9+/=]{2000,}')
_RMK_SIG = re.compile(r'j2w\.(?:kickstart|init)|class=["\'][^"\']*jobTitle-link', re.I)
_TB_SIG = re.compile(r'tbcdn\.talentbrew\.com/company/(\d+)/', re.I)
_EF_SIG = re.compile(r'static\.vscdn\.net|eightfold\.ai|/api/pcsx/', re.I)


def detect(blob):
    """Sayfa HTML'i + linkler + son URL icinde ATS izi ara. Okuyucusu olan ATS'ler oncelikli."""
    blob = _DATA_URI.sub(' ', blob)  # gomulu base64 verisi: hem gereksiz hem regex'i yavaslatir
    found = []
    u0 = re.match(r'\s*https?://([A-Za-z0-9.-]+)', blob)
    phost = u0.group(1).lower() if u0 else ''
    pslug = next((p for p in phost.split('.') if p not in BAD_SLUG), phost.split('.')[0]) if phost else ''
    if phost and 'recruitee.com' not in phost and 'careers-analytics.recruitee.com' in blob:
        found.append(('recruitee', pslug, phost))
    if phost and 'successfactors' not in phost and _RMK_SIG.search(blob):
        found.append(('successfactors', pslug, phost))
    tb = _TB_SIG.search(blob)
    if phost and tb:  # Radancy TalentBrew: firma numarasi CDN adresinde
        found.append(('talentbrew', phost, tb.group(1)))
    if phost and 'talentics.app' not in phost and 'cdn.talentics.app' in blob:  # firma alan adinda Talentics sayfasi
        found.append(('talentics', pslug, phost))
    if phost and 'phenompeople' in blob:  # Phenom: dil/bolge adresten (/global/en/ -> en_global)
        lm = re.match(r'\s*https?://[^/]+/([a-z]{2,10})/([a-z]{2})/', blob)
        found.append(('phenom', phost, f'{lm.group(2)}_{lm.group(1)}' if lm else 'en_global'))
    if phost and _EF_SIG.search(blob):  # Eightfold: sitenin kendi /api/pcsx ucu
        dom_m = re.search(r'[?&]domain=([a-z0-9-]+(?:\.[a-z0-9-]+)+)', blob)
        found.append(('eightfold', phost, dom_m.group(1) if dom_m else '.'.join(phost.split('.')[-2:])))
    for ats, rx in PATTERNS:
        for m in rx.finditer(blob):
            g = [x for x in m.groups() if x is not None]
            slug = (g[0] or '').strip('.').lower() if g else ''
            if ats in ('workday',):
                slug, extra = m.group(1).lower(), f'{m.group(2)}|{m.group(3)}'
            elif ats in ('successfactors', 'oracle'):
                slug, extra = m.group(2), m.group(1)
            else:
                extra = None
            if ats not in ('kolayik', 'peoplise') and (not slug or slug in BAD_SLUG):
                continue
            found.append((ats, urllib.parse.unquote(slug), extra))
            break
    if not found:
        return None
    rank = lambda f: (0 if has_reader(f[0], f[2]) else 2 if f[0] in REDIRECT_ONLY else 1)
    return sorted(found, key=rank)[0]


# ------------------------------------------------------------------ okuyucular
def lever(slug, extra=None):
    out = []
    for j in fetch_json(f'https://api.lever.co/v0/postings/{slug}?mode=json'):
        c = j.get('categories') or {}
        desc = ' '.join([j.get('descriptionPlain') or ''] + [text(x.get('content', '')) for x in (j.get('lists') or [])]
                        + [j.get('additionalPlain') or ''])
        out.append(dict(id=j['id'], title=j.get('text', ''), location=c.get('location') or ', '.join(c.get('allLocations') or []),
                        team=c.get('team') or '', url=j.get('hostedUrl', ''), posted=_ms(j.get('createdAt')),
                        remote=j.get('workplaceType') == 'remote', desc=desc))
    return out


def greenhouse(slug, extra=None):
    import html as _html
    d = fetch_json(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true', max_bytes=60_000_000, timeout=60)
    return [dict(id=str(j['id']), title=j.get('title', ''), location=(j.get('location') or {}).get('name', ''),
                 team=', '.join(x.get('name', '') for x in (j.get('departments') or [])),
                 url=j.get('absolute_url', ''), posted=_d(j.get('first_published') or j.get('updated_at')), remote=False,
                 desc=text(_html.unescape(j.get('content') or ''))) for j in d['jobs']]


def ashby(slug, extra=None):
    d = fetch_json(f'https://api.ashbyhq.com/posting-api/job-board/{slug}')
    return [dict(id=j['id'], title=j.get('title', ''), location=j.get('location') or '', team=j.get('department') or '',
                 url=j.get('jobUrl', ''), posted=_d(j.get('publishedAt')), remote=bool(j.get('isRemote')),
                 desc=j.get('descriptionPlain') or text(j.get('descriptionHtml') or ''))
            for j in d['jobs'] if j.get('isListed', True)]


def workable(slug, extra=None):
    d = fetch_json(f'https://apply.workable.com/api/v1/widget/accounts/{slug}')
    return [dict(id=j.get('shortcode') or j.get('url'), title=j.get('title', ''),
                 location=', '.join(x for x in (j.get('city'), j.get('country')) if x), team=j.get('department') or '',
                 url=j.get('url', ''), posted=_d(j.get('published_on')), remote=bool(j.get('telecommuting'))) for j in d.get('jobs', [])]


def smartrecruiters(slug, extra=None):
    """extra='tr': yalnizca Turkiye ilanlari (API ulke filtresi; Bosch gibi binlerce ilanli cok uluslu hesaplar icin)."""
    out, off = [], 0
    country = '&country=tr' if extra == 'tr' else ''
    while True:
        d = fetch_json(f'https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={off}{country}')
        for j in d.get('content', []):
            loc = j.get('location') or {}
            out.append(dict(id=j['id'], title=j.get('name', ''), location=', '.join(x for x in (loc.get('city'), loc.get('country')) if x),
                            team=(j.get('department') or {}).get('label', ''), url=f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                            posted=_d(j.get('releasedDate')), remote=bool(loc.get('remote')),
                            detail=('smartrecruiters', f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{j['id']}")))
        off += 100
        if off >= d.get('totalFound', 0):
            return out


def recruitee(slug, extra=None):
    host = extra or f'{slug}.recruitee.com'
    d = fetch_json(f'https://{host}/api/offers/')
    return [dict(id=str(j['id']), title=j.get('title', ''), location=j.get('location') or j.get('city') or '', team=j.get('department') or '',
                 url=j.get('careers_url', ''), posted=_d(j.get('published_at') or j.get('created_at')), remote=bool(j.get('remote')),
                 desc=text((j.get('description') or '') + ' ' + (j.get('requirements') or '')))
            for j in d['offers']]


def personio(slug, extra=None):
    tld = extra if extra in ('de', 'com') else 'de'
    _, _, x = fetch(f'https://{slug}.jobs.personio.{tld}/xml?language=tr')
    out = []
    for p in re.findall(r'<position>(.*?)</position>', x, flags=re.S):
        g = lambda t: text((re.search(rf'<{t}>(.*?)</{t}>', p, flags=re.S) or [None, ''])[1])
        jid = g('id')
        out.append(dict(id=jid, title=g('name'), location=g('office'), team=g('department'),
                        url=f'https://{slug}.jobs.personio.{tld}/job/{jid}', posted=_d(g('createdAt')), remote=False,
                        desc=text(' '.join(re.findall(r'<value>(.*?)</value>', p, flags=re.S)))))
    return out


def bamboohr(slug, extra=None):
    d = fetch_json(f'https://{slug}.bamboohr.com/careers/list')
    out = []
    for j in d.get('result', []):
        loc = j.get('location') or {}
        out.append(dict(id=str(j['id']), title=j.get('jobOpeningName', ''), location=', '.join(x for x in (loc.get('city'), loc.get('state')) if x),
                        team=j.get('departmentLabel') or '', url=f"https://{slug}.bamboohr.com/careers/{j['id']}", posted=None,
                        remote=bool(j.get('isRemote'))))
    return out


def breezy(slug, extra=None):
    d = fetch_json(f'https://{slug}.breezy.hr/json')
    return [dict(id=j.get('id') or j.get('friendly_id'), title=j.get('name', ''), location=(j.get('location') or {}).get('name', ''),
                 team=(j.get('department') or ''), url=j.get('url', ''), posted=_d(j.get('published_date')),
                 remote=bool((j.get('location') or {}).get('is_remote')), desc=text(j.get('description') or '')) for j in d]


def pinpoint(slug, extra=None):
    d = fetch_json(f'https://{slug}.pinpointhq.com/postings.json')
    return [dict(id=str(j['id']), title=j.get('title', ''), location=(j.get('location') or {}).get('name', ''),
                 team=(j.get('department') or {}).get('name', '') if isinstance(j.get('department'), dict) else '',
                 url=j.get('url', ''), posted=None, remote=j.get('workplace_type') == 'remote') for j in d.get('data', [])]


def teamtailor(slug, extra=None):
    host = extra or f'{slug}.teamtailor.com'
    _, _, x = fetch(f'https://{host}/jobs.rss')
    out = []
    for it in re.findall(r'<item>(.*?)</item>', x, flags=re.S):
        g = lambda t: text((re.search(rf'<{t}[^>]*>(.*?)</{t}>', it, flags=re.S) or [None, ''])[1])
        link = g('link')
        try:
            posted = dt.datetime.strptime(g('pubDate')[:25], '%a, %d %b %Y %H:%M:%S').strftime('%Y-%m-%d')
        except ValueError:
            posted = None
        out.append(dict(id=g('guid') or link, title=g('title'), location=g('tt:location') or g('location'), team=g('tt:department'),
                        url=link, posted=posted, remote=False, desc=g('description')))
    return out


_TURKEY = re.compile(r'^(turkiye|turkey|turkei|tuerkei|tuerkiye|turqu|turchia)')  # norm() ile sadelestirilmis ulke adi (arayuz dili degisebilir)
_WD_MANY = re.compile(r'^\d+\s+\S+$')  # "2 Locations" / "3 Konum": birden fazla konum, gercek yer adi degil


def _wd_country(facets):
    """Workday filtrelerinde ulke filtresi (ic ice olabilir: locationMainGroup > locationCountry).
    Dondurur: (parametre, [Turkiye deger id'leri], degerlerin toplam ilan sayisi) ya da ulke filtresi yoksa None."""
    for f in facets or []:
        param, vals = f.get('facetParameter') or '', f.get('values') or []
        if 'country' in param.lower():
            ids = [v['id'] for v in vals if v.get('id') and _TURKEY.match(norm(v.get('descriptor')))]
            return param, ids, sum(v.get('count') or 0 for v in vals)
        sub = _wd_country([v for v in vals if 'facetParameter' in v])
        if sub:
            return sub
    return None


def _wd_places(facets):
    """Ulke filtresi olmayan hesaplarda konum filtresi (or. Mastercard 'locations': 'Besiktas, Istanbul Turkey').
    Dondurur: (parametre, [Turkiye'deki konum id'leri], degerlerin toplam ilan sayisi) ya da konum filtresi yoksa None."""
    for f in facets or []:
        param, vals = f.get('facetParameter') or '', f.get('values') or []
        if param.lower() in ('locations', 'location', 'primarylocation'):
            ids = [v['id'] for v in vals if v.get('id') and TR_PLACE.search(norm(v.get('descriptor')))]
            return param, ids, sum(v.get('count') or 0 for v in vals)
        sub = _wd_places([v for v in vals if 'facetParameter' in v])
        if sub:
            return sub
    return None


def _wd_location(j, turkey=False):
    """Konum metni; bazi hesaplar locationsText vermiyor: o zaman adresteki konum parcasi (/job/<konum>/...).
    Turkiye filtresiyle alinan ilanlara ulke eklenir (bolge 'Turkiye' olsun)."""
    loc = (j.get('locationsText') or '').strip()
    if not loc or _WD_MANY.match(loc):
        m = re.match(r'/job/([^/]+)/', j.get('externalPath') or '')
        loc = urllib.parse.unquote(m.group(1)).replace('-', ' ').strip() if m else loc
    if turkey and not re.search(r'turkiye|turkey', norm(loc)):
        loc = f'{loc}, Türkiye' if loc else 'Türkiye'
    return loc


def _wd_page(api, off, facets):
    body = json.dumps({'appliedFacets': facets, 'limit': 20, 'offset': off, 'searchText': ''}).encode()
    _, _, t = fetch(api, data=body, method='POST', headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
    return json.loads(t)


def workday(slug, extra=None):
    """Workday CXS uc noktasi (sayfali). Hesapta ulke filtresi (yoksa konum filtresi) varsa yalnizca Turkiye ilanlari alinir:
    cok uluslu hesaplarda (Accenture, Samsung, Mastercard) binlerce yurt disi ilani gelmesin ve 2000 sonuc sinirina takilinmasin."""
    wd, site = (extra or 'wd3|External').split('|')
    base = f'https://{slug}.{wd}.myworkdayjobs.com'
    api = f'{base}/wday/cxs/{slug}/{site}/jobs'
    d = _wd_page(api, 0, {})
    total_all, facets = d.get('total') or 0, {}
    country = _wd_country(d.get('facets')) or _wd_places(d.get('facets'))  # konum degerleri cok konumlu ilanlarda toplami asar
    if country:
        param, ids, counted = country
        if ids:
            facets = {param: ids}
            d = _wd_page(api, 0, facets)
        elif counted >= 0.95 * total_all:  # ulke filtresi ilanlarin (neredeyse) tamamini kapsiyor ve Turkiye yok: kesin bos
            # (Samsung: 658 ilanin 649'unda ulke var; ulkesiz birkac ilan Turkiye olsaydi filtrede 'Turkiye' degeri cikardi)
            return Jobs(note=f"Turkiye'de ilani yok (toplam {total_all})", confirmed=True)
    out, off, total = [], 0, None
    while True:
        if total is None:  # Workday toplam ilan sayisini YALNIZCA ilk sayfada dogru verir (sonrakilerde 0)
            total = d.get('total') or 0
        posts = d.get('jobPostings', [])
        for j in posts:
            path = j.get('externalPath', '')
            out.append(dict(id=path or j.get('title'), title=j.get('title', ''), location=_wd_location(j, bool(facets)), team='',
                            url=f'{base}/{site}{path}', posted=None, remote=False,
                            detail=('workday', f'{base}/wday/cxs/{slug}/{site}{path}')))
        off += 20
        if not posts or off >= total or off >= 3000:
            break
        time.sleep(0.6)
        d = _wd_page(api, off, facets)
    return Jobs(out, note=f'Turkiye filtresi: {len(out)} / {total_all} ilan') if facets else out


def successfactors(slug, extra=None):
    """SAP SuccessFactors RMK kariyer siteleri: arama sayfasi HTML'i (sayfalanir).
    extra = sunucu ya da 'sunucu|Turkey': cok uluslu sitelerde (EY, Vestas) yalnizca konum aramasina uyan ilanlar okunur."""
    host, _, where = (extra or '').partition('|')
    if not host or 'successfactors' in host:
        raise HttpError('okuyucu-yok', slug, 'SuccessFactors klasik portal (genel ayristirici kullanilacak)')
    locq = f'&locationsearch={urllib.parse.quote(where)}' if where else ''
    out, seen, start = [], set(), 0
    while start < 1000:
        _, _, t = fetch(f'https://{host}/search/?q={locq}&sortColumn=referencedate&sortDirection=desc&startrow={start}', robots=True)
        doc, found = dom.parse(t), 0
        # her ilan bir satir (tr.data-row); satir yoksa sayfadaki tum a.jobTitle-link (masaustu + mobil kopyalari tekillesir)
        for row in doc.find_all('tr', cls='data-row') or doc.find_all('a', cls='jobTitle-link'):
            a = row if row.tag == 'a' else row.find('a', cls='jobTitle-link')
            if a is None or not a.get('href') or a.get('href') in seen:
                continue
            seen.add(a.get('href'))
            found += 1
            loc = (row if row.tag != 'a' else a.closest('tr') or a.parent).find('span', cls='jobLocation')
            out.append(dict(id=a.get('href'), title=a.text(), location=loc.text() if loc else '', team='',
                            url=urllib.parse.urljoin(f'https://{host}', a.get('href')), posted=None, remote=False))
        if found < 10:
            break
        start += found
    return out


def manatal(slug, extra=None):
    """Manatal kariyer sayfalari (careers-page.com/<slug>): herkese acik JSON, sayfali."""
    out, url = [], f'https://www.careers-page.com/api/v1.0/c/{slug}/jobs/'
    while url and len(out) < 2000:
        d = fetch_json(url)
        for j in d.get('results', []):
            loc = j.get('location_display') or ', '.join(x for x in (j.get('city'), j.get('country')) if x)
            out.append(dict(id=str(j['id']), title=j.get('position_name', ''), location=loc or '', team='',
                            url=f"https://www.careers-page.com/{slug}/job/{j.get('hash') or j['id']}", posted=None, remote=False,
                            desc=text(j.get('description') or '')))
        url = d.get('next')
    return out


def jazzhr(slug, extra=None):
    """JazzHR (<slug>.applytojob.com/apply): sunucuda uretilen liste sayfasi."""
    _, _, t = fetch(f'https://{slug}.applytojob.com/apply', robots=True)
    out = []
    for item in dom.parse(t).find_all('li', cls='list-group-item'):
        a = next((x for x in item.find_all('a') if re.search(r'applytojob\.com/apply/[A-Za-z0-9]{6,}/', x.get('href', ''))), None)
        if a is None:
            continue
        href = a.get('href')
        info = item.find('ul', cls='list-group-item-text')  # konum (ve varsa bolum) satiri
        out.append(dict(id=re.search(r'/apply/([A-Za-z0-9]{6,})/', href).group(1), title=a.text(), location=info.text() if info else '',
                        team='', url=href, posted=None, remote=False, detail=('page', href)))
    return out


def rippling(slug, extra=None):
    """Rippling ATS (ats.rippling.com/<slug>/jobs): herkese acik JSON liste ucu."""
    d = fetch_json(f'https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs')
    out = []
    for j in d if isinstance(d, list) else d.get('items', []):
        uid = j.get('uuid') or j.get('id')
        loc = (j.get('workLocation') or {}).get('label') or ', '.join(x.get('name', '') for x in (j.get('locations') or []) if x.get('name'))
        dept = j.get('department') or {}
        out.append(dict(id=str(uid), title=j.get('name', ''), location=loc or '', team=dept.get('label') or dept.get('name') or '',
                        url=j.get('url') or f'https://ats.rippling.com/{slug}/jobs/{uid}', posted=_d(j.get('createdOn')), remote='remote' in norm(loc),
                        detail=('rippling', f'https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs/{uid}')))
    return out


def eightfold(slug, extra=None):
    """Eightfold AI kariyer siteleri (Microsoft, Ericsson, Vodafone): sitenin kendi arama ucu, 'Turkey' konum filtresiyle.
    slug = kariyer sitesinin sunucusu (jobs.vodafone.com), extra = Eightfold alan adi (vodafone.com)."""
    host, domain = slug, extra or '.'.join(slug.split('.')[-2:])
    out, start, total = [], 0, None
    while start < 1000:
        d = fetch_json(f'https://{host}/api/pcsx/search?domain={domain}&query=&location=Turkey&start={start}', robots=True).get('data') or {}
        if total is None:
            total = d.get('count') or 0
        posts = d.get('positions') or []
        for j in posts:
            # konum filtresi bulanik (yakin/benzer yerler de gelir): konumlarindan biri Turkiye olmayan ilan alinmaz; Turkiye basa
            locs = sorted(j.get('locations') or [], key=lambda x: not TR_PLACE.search(norm(x)))
            if not any(TR_PLACE.search(norm(x)) for x in locs + (j.get('standardizedLocations') or [])):
                continue
            out.append(dict(id=str(j['id']), title=j.get('name', ''), location='; '.join(locs[:3]), team=j.get('department') or '',
                            url=f"https://{host}{j.get('positionUrl') or '/careers/job/' + str(j['id'])}",
                            posted=_ms((j.get('postedTs') or 0) * 1000) if j.get('postedTs') else None,
                            remote=j.get('workLocationOption') == 'remote',
                            detail=('eightfold', f"https://{host}/api/pcsx/position_details?position_id={j['id']}&domain={domain}&hl=en")))
        start += len(posts)
        if not posts or start >= total:
            break
        time.sleep(0.4)
    return Jobs(out, note=f'Turkiye filtresi: {len(out)} ilan', confirmed=True)  # bos sonuc: sitede Turkiye ilani yok


def _orc_turkey(host):
    """Oracle Recruiting Cloud: hesabin cografya kaydindaki Turkiye kimligi (ulke duzeyi, Level 1) ya da None."""
    for term in ('T%C3%BCrkiye', 'Turkey'):
        d = fetch_json(f'https://{host}/hcmRestApi/resources/latest/recruitingCESearchAutoSuggestions'
                       f'?expand=all&onlyData=true&finder=findByLoc;string={term}&limit=20')
        hit = next((i for i in d.get('items') or [] if i.get('Level') == 1 and _TURKEY.match(norm(i.get('Country') or i.get('Name')))), None)
        if hit:
            return hit['Id']
    return None


def oracle(slug, extra=None):
    """Oracle Recruiting Cloud (JPMorgan, Uber, Fortinet, Nokia...): CandidateExperience REST ucu, Turkiye konum kimligiyle.
    slug = site numarasi (CX_1001), extra = sunucu (jpmc.fa.oraclecloud.com)."""
    site, host = slug, extra
    loc = _orc_turkey(host)
    if not loc:
        return Jobs(note="Turkiye konumu yok", confirmed=True)
    out, off, total = [], 0, None
    while off < 1000:
        finder = f'findReqs;siteNumber={site},limit=25,locationId={loc},offset={off},sortBy=POSTING_DATES_DESC'
        d = fetch_json(f'https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true'
                       f'&expand=requisitionList.secondaryLocations&finder={urllib.parse.quote(finder, safe="=,;")}')['items'][0]
        if total is None:
            total = d.get('TotalJobsCount') or 0
        reqs = d.get('requisitionList') or []
        for j in reqs:
            url = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{j['Id']}"
            out.append(dict(id=str(j['Id']), title=j.get('Title', ''), location=j.get('PrimaryLocation') or 'Türkiye', team=j.get('JobFamily') or '',
                            url=url, posted=_d(j.get('PostedDate')), remote=(j.get('WorkplaceTypeCode') or '') == 'ORA_REMOTE',
                            detail=('oracle', f'https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?expand=all'
                                              f'&onlyData=true&finder=ById;Id=%22{j["Id"]}%22,siteNumber={site}')))
        off += len(reqs)
        if not reqs or off >= total:
            break
        time.sleep(0.4)
    return Jobs(out, note=f'Turkiye filtresi: {len(out)} ilan', confirmed=True)


def _ph_search(host, lang, sel, start, size):
    country = lang.split('_')[1]
    body = {'lang': lang, 'deviceType': 'desktop', 'country': country, 'pageName': 'search-results', 'ddoKey': 'refineSearch',
            'sortBy': '', 'subsearch': '', 'from': start, 'jobs': True, 'counts': True, 'all_fields': ['country'], 'size': size,
            'clearAll': False, 'jdsource': 'facets', 'isSliderEnable': False, 'siteType': 'external', 'keywords': '', 'global': True,
            'selected_fields': sel, 'locationData': {}}
    _, _, t = fetch(f'https://{host}/widgets', data=json.dumps(body).encode(), method='POST', robots=True,
                    headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
    return (json.loads(t).get('refineSearch') or {})


def phenom(slug, extra=None):
    """Phenom kariyer siteleri (DHL, Cisco, UPS, Siemens Healthineers...): sitenin /widgets arama ucu, ulke filtresiyle.
    Ulke degeri siteye gore 'Turkey' ya da 'Türkiye': once ulke dagilimindan bulunur. slug = sunucu, extra = dil (en_global)."""
    host, lang = slug, extra or 'en_global'
    first = _ph_search(host, lang, {}, 0, 1)
    aggs = (first.get('data') or {}).get('aggregations') or []
    vals = [k for a in aggs if a.get('field') == 'country' for k, v in (a.get('value') or {}).items() if v and _TURKEY.match(norm(k))]
    if not vals:
        return Jobs(note=f"Turkiye'de ilani yok (toplam {first.get('totalHits') or 0})", confirmed=True)
    base = f"https://{host}/{lang.split('_')[1]}/{lang.split('_')[0]}/job/"
    out, start, total = [], 0, None
    while start < 1000:
        d = _ph_search(host, lang, {'country': vals}, start, 50)
        if total is None:
            total = d.get('totalHits') or 0
        jobs = (d.get('data') or {}).get('jobs') or []
        for j in jobs:
            jid = j.get('jobId') or j.get('jobSeqNo')
            out.append(dict(id=str(jid), title=j.get('title', ''), location=j.get('location') or j.get('cityStateCountry') or 'Türkiye',
                            team=j.get('category') or ', '.join(j.get('multi_category') or []), url=base + urllib.parse.quote(str(jid)),
                            posted=_d(j.get('postedDate')), remote=False,  # descriptionTeaser kisa: aciklama detay sayfasindan
                            detail=('page', base + urllib.parse.quote(str(jid)))))
        start += len(jobs)
        if not jobs or start >= total:
            break
        time.sleep(0.4)
    return Jobs(out, note=f'Turkiye filtresi: {len(out)} / {first.get("totalHits") or 0} ilan', confirmed=True)


def _av_turkey_filter(host, path):
    """Avature arama sayfasinda ulke secim kutusu sayfada hazirsa (<option>Turkiye</option>) Turkiye filtresi: 'alan=deger'."""
    for sel in dom.parse(fetch(f'https://{host}/{path}', robots=True)[2]).find_all('select'):
        opt = next((o for o in sel.find_all('option') if _TURKEY.match(norm(o.text()))), None)
        if opt is not None and opt.get('value'):
            name = sel.get('name') or ''
            return f'{name[:-2]}=%5B{opt.get("value")}%5D' if name.endswith('[]') else f'{name}={opt.get("value")}'
    return None


def avature(slug, extra=None):
    """Avature kariyer siteleri (Siemens, Siemens Energy...): sunucuda uretilen arama sayfasi, Turkiye filtresiyle, sayfali.
    slug = sunucu, extra = arama sayfasinin yolu; Turkiye filtresi yolda hazir olabilir (Siemens: ulke kutusu sonradan yuklenir,
    '?42386=%5B811999%5D&listFilterMode=1'), yoksa sayfadaki ulke secim kutusundan bulunur."""
    host, path = slug, extra or 'careers/SearchJobs'
    if '=' not in path:
        flt = _av_turkey_filter(host, path)
        if not flt:
            return Jobs(note='Turkiye filtresi bulunamadi')
        path = f"{path}{'&' if '?' in path else '?'}{flt}&listFilterMode=1"
    out, seen, off = [], set(), 0
    while off < 600:
        _, _, t = fetch(f'https://{host}/{path}&folderOffset={off}&jobOffset={off}', robots=True)
        found = 0
        for a in dom.parse(t).find_all('a'):
            m = re.search(r'/(?:JobDetail|FolderDetail)/(?:[^/?#]+/)?(\d+)/?$', a.get('href') or '')
            if not m or m.group(1) in seen or not a.text() or not (a.closest('h3') or a.closest('h2')):
                continue
            seen.add(m.group(1))
            found += 1
            art = a.closest('article') or a.closest('li') or a.parent
            loc = next((n for n in art.iter() if 'list-item-location' in n.classes or any('location' in c.lower() for c in n.classes)), None)
            fam = next((n for n in art.iter() if any('family' in c.lower() or 'department' in c.lower() for c in n.classes)), None)
            loc = loc.text().replace(' ,', ',') if loc else ''
            if not TR_PLACE.search(norm(loc)):  # Turkiye filtresiyle geldi: 'Multiple Locations' gibi metinlere ulke eklenir
                loc = f'{loc}, Türkiye' if loc else 'Türkiye'
            out.append(dict(id=m.group(1), title=a.text(), location=loc, team=fam.text() if fam else '', url=a.get('href'), posted=None,
                            remote=False, detail=('page', a.get('href'))))
        if not found:
            break
        off += found
        time.sleep(0.4)
    return Jobs(out, note=f'Turkiye filtresi: {len(out)} ilan', confirmed=True)


TB_TURKEY = 298795  # GeoNames: Turkiye (TalentBrew ulke sayfalarinin adresinde)


def talentbrew(slug, extra=None):
    """Radancy TalentBrew kariyer siteleri (Citi, IQVIA, Dell...): arama uclari robots.txt ile kapali, ulke sayfasi
    (/location/turkey-jobs/<org>/298795/2) acik. slug = site sunucusu, extra = TalentBrew firma numarasi."""
    host, org = slug, extra
    out, seen, page, pages = [], set(), 1, 1
    while page <= min(pages, 30):
        _, _, t = fetch(f'https://{host}/location/turkey-jobs/{org}/{TB_TURKEY}/2' + (f'?p={page}' if page > 1 else ''), robots=True)
        m = re.search(r'data-total-pages="(\d+)"', t)
        pages = int(m.group(1)) if m else 1
        for a in dom.parse(t).find_all('a'):
            href, jid = a.get('href') or '', a.get('data-job-id')
            if not jid or '/job/' not in href or jid in seen:
                continue
            seen.add(jid)
            item = a.closest('li') or a.parent
            loc = next((n for n in item.iter() if any('location' in c for c in n.classes)), None)
            title = (a.find('h2') or a.find('h3') or a).text()
            out.append(dict(id=jid, title=title, location=loc.text() if loc else 'Türkiye', team='',
                            url=urllib.parse.urljoin(f'https://{host}/', href), posted=None, remote=False,
                            detail=('page', urllib.parse.urljoin(f'https://{host}/', href))))
        page += 1
        time.sleep(0.4)
    return Jobs(out, confirmed=True)  # ulke sayfasi bos: Turkiye ilani yok


def talentics(slug, extra=None):
    """Talentics / Kolay IK ise alim sayfalari (<slug>.talentics.app ya da firma alan adi): sunucuda uretilen liste.
    Her ilan: a.job-link-title (baslik) + a.job-link-props ('Konum • Ekip • Calisma turu'). 'Genel basvuru' ilan sayilmaz."""
    host = extra or f'{slug}.talentics.app'
    doc = dom.parse(fetch(f'https://{host}/', robots=True)[2])
    groups = {}
    for a in doc.find_all('a'):
        href = a.get('href') or ''
        if re.match(r'(?:https?://[^/]+)?/jobs/[0-9a-f-]{20,}', href):
            groups.setdefault(href.split('/jobs/')[1].split('?')[0], []).append(a)
    out = []
    for jid, links in groups.items():
        title_a = next((a for a in links if 'job-link-title' in a.classes or a.find('h5') or a.find('h4') or a.find('h3')), None)
        props_a = next((a for a in links if any('props' in c for c in a.classes)), None)
        texts = [a.text() for a in links if a.get('role') != 'button']
        title = title_a.text() if title_a else (texts[0] if texts else '')
        if not title or re.search(r'genel basvuru|general application|acik basvuru', norm(title)):
            continue
        parts = [p.strip() for p in (props_a.text() if props_a else '').split('•')]
        out.append(dict(id=jid, title=title, location=parts[0] if parts else '', team=parts[1] if len(parts) > 1 else '',
                        url=f'https://{host}/jobs/{jid}', posted=None, remote='remote' in norm(parts[0] if parts else ''),
                        detail=('page', f'https://{host}/jobs/{jid}')))
    return out


def hrpanda(slug, extra=None):
    """HrPanda (<slug>.hrpanda.co, Turk ATS): Next.js sayfasindaki __NEXT_DATA__ yayindaki ilanlarin tamamini tasir."""
    host = extra or f'{slug}.hrpanda.co'
    _, _, t = fetch(f'https://{host}/', robots=True)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
    if not m:
        raise HttpError('ayristirilamadi', host, '__NEXT_DATA__ yok')
    props = json.loads(m.group(1)).get('props', {}).get('pageProps', {})
    rows = ((props.get('listingsData') or {}).get('getPublishedJobListings') or {}).get('jobListings') or []
    out = []
    for j in rows:
        if j.get('status') not in (None, 'PUBLISHED'):
            continue
        work = ((j.get('workType') or {}).get('name') or '')
        dept = j.get('department')
        out.append(dict(id=j['id'], title=(j.get('name') or '').strip(), location=j.get('location') or '',
                        team=dept.get('name', '') if isinstance(dept, dict) else (dept or ''), url=f"https://{host}/{j.get('slug') or j['id']}",
                        posted=_d(j.get('createdAt')), remote=work.lower() == 'remote',
                        desc=text((j.get('description') or '') + ' ' + (j.get('jobRequirements') or ''))))
    return out


FETCHERS = {'lever': lever, 'greenhouse': greenhouse, 'ashby': ashby, 'workable': workable, 'smartrecruiters': smartrecruiters,
            'recruitee': recruitee, 'personio': personio, 'bamboohr': bamboohr, 'breezy': breezy, 'pinpoint': pinpoint,
            'teamtailor': teamtailor, 'workday': workday, 'successfactors': successfactors, 'manatal': manatal, 'jazzhr': jazzhr,
            'rippling': rippling, 'eightfold': eightfold, 'talentbrew': talentbrew, 'talentics': talentics,
            'oracle': oracle, 'phenom': phenom, 'avature': avature,
            'hrpanda': hrpanda}


def fetch_jobs(ats, slug, extra=None):
    fn = FETCHERS.get(ats)
    if not fn:
        raise KeyError(ats)
    return fn(slug, extra)

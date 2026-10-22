"""ATS (aday takip sistemi) tespiti ve okuyucular.
detect(text) -> (ats, slug, extra) ; fetch_jobs(ats, slug, extra) -> [ {id,title,location,team,url,posted,remote} ]
Okuyuculari olan ATS'ler herkese acik, anahtarsiz uc noktalar kullanir. Okuyucusu olmayanlar 'generic' ayristiriciya duser."""
import datetime as dt
import json
import re
import time
import urllib.parse

from .util import HttpError, fetch, fetch_json, text


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
    ('kariyer.net', r'kariyer\.net/(?:firma-profil|is-ilanlari?)/([A-Za-z0-9_-]+)'),
    ('linkedin', r'linkedin\.com/company/([A-Za-z0-9_-]+)/jobs'),
]
PATTERNS = [(a, re.compile(p, re.I)) for a, p in PATTERNS]
BAD_SLUG = {'embed', 'api', 'v1', 'jobs', 'job', 'www', 'careers', 'career', 'apply', 'static', 'assets', 'cdn', 'js', 'images',
            'app', 'help', 'support', 'blog', 'en', 'tr', 'de'}
READERS = {'lever', 'greenhouse', 'ashby', 'workable', 'smartrecruiters', 'recruitee', 'personio', 'bamboohr', 'breezy',
           'pinpoint', 'teamtailor', 'workday', 'successfactors', 'manatal', 'jazzhr'}
REDIRECT_ONLY = {'kariyer.net', 'linkedin'}


def has_reader(ats, extra=None):
    """Bu ATS icin calisan bir okuyucu var mi? (SuccessFactors'un yalnizca RMK sitelerini okuyabiliyoruz)"""
    if ats == 'successfactors':
        return bool(extra) and 'successfactors' not in extra
    return ats in READERS


_DATA_URI = re.compile(r'data:[a-z/+.-]+;base64,[A-Za-z0-9+/=]{64,}|[A-Za-z0-9+/=]{2000,}')


def detect(blob):
    """Sayfa HTML'i + linkler + son URL icinde ATS izi ara. Okuyucusu olan ATS'ler oncelikli."""
    blob = _DATA_URI.sub(' ', blob)  # gomulu base64 verisi: hem gereksiz hem regex'i yavaslatir
    found = []
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
    rank = lambda f: (0 if f[0] in READERS else 2 if f[0] in REDIRECT_ONLY else 1)
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
    out, off = [], 0
    while True:
        d = fetch_json(f'https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={off}')
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
    d = fetch_json(f'https://{slug}.recruitee.com/api/offers/')
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


def workday(slug, extra=None):
    wd, site = (extra or 'wd3|External').split('|')
    base = f'https://{slug}.{wd}.myworkdayjobs.com'
    api = f'{base}/wday/cxs/{slug}/{site}/jobs'
    out, off, total = [], 0, None
    while off < 3000:
        body = json.dumps({'appliedFacets': {}, 'limit': 20, 'offset': off, 'searchText': ''}).encode()
        _, _, t = fetch(api, data=body, method='POST', headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        d = json.loads(t)
        if total is None:  # Workday toplam ilan sayisini YALNIZCA ilk sayfada dogru verir (sonrakilerde 0)
            total = d.get('total') or 0
        posts = d.get('jobPostings', [])
        for j in posts:
            path = j.get('externalPath', '')
            out.append(dict(id=path or j.get('title'), title=j.get('title', ''), location=j.get('locationsText', ''), team='',
                            url=f'{base}/{site}{path}', posted=None, remote=False,
                            detail=('workday', f'{base}/wday/cxs/{slug}/{site}{path}')))
        off += 20
        if not posts or off >= total:
            break
        time.sleep(0.6)
    return out


def successfactors(slug, extra=None):
    """SAP SuccessFactors RMK kariyer siteleri: arama sayfasi HTML'i (sayfalanir)."""
    host = extra if extra and 'successfactors' not in extra else None
    if not host:
        raise HttpError('okuyucu-yok', slug, 'SuccessFactors klasik portal (genel ayristirici kullanilacak)')
    out, start = [], 0
    while start < 1000:
        _, _, t = fetch(f'https://{host}/search/?q=&sortColumn=referencedate&sortDirection=desc&startrow={start}')
        rows = re.findall(r'<a[^>]+class="jobTitle-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', t, flags=re.S)
        locs = re.findall(r'<span class="jobLocation">\s*(.*?)\s*</span>', t, flags=re.S)
        for i, (href, title) in enumerate(rows):
            out.append(dict(id=href, title=text(title), location=text(locs[i]) if i < len(locs) else '', team='',
                            url=urllib.parse.urljoin(f'https://{host}', href), posted=None, remote=False))
        if len(rows) < 10:
            break
        start += len(rows)
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
    _, _, t = fetch(f'https://{slug}.applytojob.com/apply')
    out = []
    for m in re.finditer(r'<a href="(https?://[^"]*applytojob\.com/apply/([A-Za-z0-9]{6,})/[^"]*)"[^>]*>(.*?)</a>\s*</h3>(.*?)</li>\s*</ul>',
                         t, flags=re.S):
        loc = text(re.sub(r'<i[^>]*></i>', '', m.group(4)))
        out.append(dict(id=m.group(2), title=text(m.group(3)), location=loc, team='', url=m.group(1), posted=None, remote=False,
                        detail=('page', m.group(1))))
    return out


FETCHERS = {'lever': lever, 'greenhouse': greenhouse, 'ashby': ashby, 'workable': workable, 'smartrecruiters': smartrecruiters,
            'recruitee': recruitee, 'personio': personio, 'bamboohr': bamboohr, 'breezy': breezy, 'pinpoint': pinpoint,
            'teamtailor': teamtailor, 'workday': workday, 'successfactors': successfactors, 'manatal': manatal, 'jazzhr': jazzhr}


def fetch_jobs(ats, slug, extra=None):
    fn = FETCHERS.get(ats)
    if not fn:
        raise KeyError(ats)
    return fn(slug, extra)

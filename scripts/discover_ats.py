"""Firma listesindeki firmalar halka acik ATS (ilan) API'lerinde var mi? -> ats_found.json
Token harcamaz: sadece HTTP istekleri. Kullanim: python scripts/discover_ats.py"""
import json, re, ssl, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

import openpyxl

XLSX = 'Turkiye_Yazilim_Firmalari_v2.xlsx'
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0 (compatible; ilan-izleyici)'}
TR = str.maketrans({'İ': 'i', 'I': 'i', 'ı': 'i', 'ş': 's', 'Ş': 's', 'ğ': 'g', 'Ğ': 'g', 'ü': 'u', 'Ü': 'u', 'ö': 'o', 'Ö': 'o', 'ç': 'c', 'Ç': 'c'})
STOP = {'yazilim', 'bilisim', 'teknoloji', 'teknolojileri', 'turkiye', 'turkey', 'as', 'ltd', 'sti', 'games', 'game', 'group', 'grup', 'holding'}


def slugs(name, web):
    n = (name or '').translate(TR).lower()
    n = re.sub(r'\(.*?\)', ' ', n)
    words = [w for w in re.split(r'[^a-z0-9]+', n) if w]
    out = []
    if web:
        host = re.sub(r'^https?://(www\.)?', '', web.lower()).split('/')[0]
        root = host.split('.')[0]
        if root and root not in ('com', 'co'):
            out.append(root)
    if words:
        out += [''.join(words), '-'.join(words)]
        core = [w for w in words if w not in STOP]
        if core:
            out += [''.join(core), core[0]]
    seen, res = set(), []
    for s in out:
        if len(s) >= 3 and s not in seen:
            seen.add(s); res.append(s)
    return res[:4]


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12, context=ctx) as r:
            return r.status, r.read(2_000_000).decode('utf-8', 'replace')
    except Exception as e:  # noqa
        return getattr(e, 'code', 0), ''


def check(args):
    firm, slug = args
    found = []
    # Lever
    st, b = fetch(f'https://api.lever.co/v0/postings/{slug}?mode=json')
    if st == 200:
        try:
            d = json.loads(b)
            if isinstance(d, list):
                found.append(('lever', slug, len(d)))
        except ValueError:
            pass
    # Greenhouse
    st, b = fetch(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs')
    if st == 200:
        try:
            found.append(('greenhouse', slug, len(json.loads(b)['jobs'])))
        except (ValueError, KeyError):
            pass
    # Ashby
    st, b = fetch(f'https://api.ashbyhq.com/posting-api/job-board/{slug}')
    if st == 200:
        try:
            found.append(('ashby', slug, len(json.loads(b)['jobs'])))
        except (ValueError, KeyError):
            pass
    # Recruitee
    st, b = fetch(f'https://{slug}.recruitee.com/api/offers/')
    if st == 200:
        try:
            found.append(('recruitee', slug, len(json.loads(b)['offers'])))
        except (ValueError, KeyError):
            pass
    # Workable (bilinmeyen hesapta 404 doner; hesap adi alani olmali)
    st, b = fetch(f'https://apply.workable.com/api/v1/widget/accounts/{slug}')
    if st == 200:
        try:
            d = json.loads(b)
            if d.get('name'):
                found.append(('workable', slug, len(d.get('jobs', []))))
        except ValueError:
            pass
    return firm, found


ws = openpyxl.load_workbook(XLSX)['Firmalar']
firms = []
for r in ws.iter_rows(min_row=2, values_only=True):
    name, size, web = r[1], r[5], r[10]
    # Teknokent kaynakli kucuk firmalar yerine once derlenmis/buyuk/orta firmalar (ATS kullanma olasiligi yuksek)
    if '--all' in sys.argv or r[15] == 'Derlenmiş liste (sektör bilgisi)' or size in ('Büyük / kurumsal', 'Orta / scale-up'):
        firms.append((name, web, r[2], r[4]))
print('taranacak firma:', len(firms))
jobs = [((n, w, c, s), sl) for n, w, c, s in firms for sl in slugs(n, w)]
print('istek grubu:', len(jobs), '(her biri 5 ATS)')
t0 = time.time()
with ThreadPoolExecutor(24) as ex:
    results = list(ex.map(check, jobs))
best = {}
for (n, w, c, s), found in results:
    for ats, slug, cnt in found:
        k = n
        # ayni firma icin birden fazla slug eslesirse en cok ilani olani al
        if k not in best or cnt > best[k]['count']:
            best[k] = {'firma': n, 'kategori': c, 'sehir': s, 'ats': ats, 'slug': slug, 'count': cnt}
out = sorted(best.values(), key=lambda x: -x['count'])
json.dump(out, open('ats_found.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'{len(out)} firma halka acik ATS uzerinde bulundu ({round(time.time() - t0)} sn)')
for x in out[:60]:
    print(f"  {x['count']:4d}  {x['ats']:10s} {x['slug']:22s} {x['firma']}")

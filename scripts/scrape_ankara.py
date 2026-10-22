"""Ankara teknokent firma rehberlerini (ODTU, Bilkent Cyberpark, Hacettepe) toplar -> ankara_raw.json"""
import html, json, re, sys, time, urllib.request

UA = {'User-Agent': 'Mozilla/5.0'}


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:  # noqa
            err = e
            time.sleep(1.5)
    print('FAIL', url, err, file=sys.stderr)
    return ''


def clean(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', s))).strip()


out = []

# ---- ODTU: site yeniden tasarlandi, firmalar JS ile /assets/data/companies.json'dan yukleniyor.
# Once JSON, olmazsa eski tablo, o da olmazsa <noscript> listesi (yalnizca ad) denenir.
odtu = []
try:
    for x in json.loads(get('https://www.odtuteknokent.com.tr/assets/data/companies.json') or '[]'):
        odtu.append({'name': clean(x.get('name', '')), 'web': (x.get('url') or '').strip(), 'source': 'ODTÜ Teknokent', 'hint': ''})
except (ValueError, AttributeError) as e:
    print('ODTU JSON okunamadi:', e, file=sys.stderr)
if not odtu:
    t = get('https://www.odtuteknokent.com.tr/tr/firmalar/tum-firmalar.php')
    for name, cell2 in re.findall(r'<tr><td>(.*?)</td><td>(.*?)</td></tr>', t, flags=re.S):
        m = re.search(r'href="([^"]+)"', cell2)
        odtu.append({'name': clean(name), 'web': m.group(1) if m else '', 'source': 'ODTÜ Teknokent', 'hint': ''})
if not odtu:
    ns = re.search(r'<noscript>(.*?)</noscript>', t, flags=re.S)
    odtu = [{'name': clean(n), 'web': '', 'source': 'ODTÜ Teknokent', 'hint': ''} for n in re.findall(r'<p>(.*?)</p>', ns.group(1) if ns else '')]
out.extend(x for x in odtu if x['name'])
print('ODTU', len(out))
if len(out) < 300:  # sessiz bozulmayi onle: sayfa yapisi degismis olabilir
    print('UYARI: ODTU beklenenden az kayit dondu, sayfa yapisi degismis olabilir', file=sys.stderr)

# ---- Cyberpark
n0 = len(out)
page1 = get('https://www.cyberpark.com.tr/firma-arsiv')
i = page1.find('e-bulletin-image-box')
print(page1[i - 200:i + 1800] if len(sys.argv) > 1 and sys.argv[1] == 'debugcp' else '', end='')
for p in range(1, 25):
    t = page1 if p == 1 else get(f'https://www.cyberpark.com.tr/firma-arsiv/{p}')
    items = re.findall(r'<img src="/content/upload/companies/[^"]*"\s+alt="([^"]*)"', t)
    if not items:
        break
    for a in items:
        out.append({'name': clean(a), 'web': '', 'source': 'Bilkent Cyberpark', 'hint': ''})
    time.sleep(0.4)
print('CYBERPARK', len(out) - n0)
if len(out) - n0 < 200:
    print('UYARI: Cyberpark beklenenden az kayit dondu, sayfa yapisi degismis olabilir', file=sys.stderr)

# ---- Hacettepe
n0 = len(out)
idx = get('https://hacettepeteknokent.com.tr/tr/firma_rehberi')
cats = re.findall(r'href="(/tr/firma_rehberi/[^"]+)"\s*>([^<]+)</a></div>', idx)
for path, cname in cats:
    t = get('https://hacettepeteknokent.com.tr' + path)
    body = t[t.find('<main'):]
    pg = set(re.findall(r'href="([^"]*(?:page|sayfa|p)=\d+[^"]*)"', body)) | set(re.findall(r'class="page-link"[^>]*href="([^"]+)"', body))
    if pg:
        print('PAGINATION?', path, sorted(pg)[:5])
    names = re.findall(r'<div class="firma_adi"><a href="([^"]+)">(.*?)</a>', body, flags=re.S)
    for href, nm in names:
        out.append({'name': clean(nm), 'web': '', 'source': 'Hacettepe Teknokent', 'hint': clean(cname), 'ht_page': href})
    print(' ', cname, len(names))
    time.sleep(0.4)
json.dump(out, open('ankara_raw.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('HT categories', len(cats), '| HT firma', sum(1 for x in out if x.get('source') == 'Hacettepe Teknokent'))
if sum(1 for x in out if x.get('source') == 'Hacettepe Teknokent') < 200:
    print('UYARI: Hacettepe beklenenden az kayit dondu, sayfa yapisi degismis olabilir', file=sys.stderr)

"""Site adresi bilinen Ankara firmalarinin ana sayfasindan <title> + meta description -> web_meta.json (anahtar: host)"""
import html, json, re, ssl, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

raw = json.load(open('ankara_raw.json', encoding='utf-8'))
det = {d['ht_page']: d for d in json.load(open('ht_details.json', encoding='utf-8'))}
urls = {}
for x in raw:
    w = x.get('web') or (det.get(x.get('ht_page')) or {}).get('web') or ''
    w = w.strip()
    if not w or any(b in w.lower() for b in ('wixsite', 'blogspot', 'facebook', 'linkedin', 'instagram')):
        continue
    if not re.match(r'https?://', w, re.I):
        w = 'http://' + w
    h = re.sub(r'^https?://(www\.)?', '', w, flags=re.I).split('/')[0].lower()
    urls.setdefault(h, w)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0 (compatible; firma-listesi-arastirma)', 'Accept-Language': 'tr,en;q=0.8'}


def clean(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', s or ''))).strip()


def fetch(item):
    h, u = item
    try:
        req = urllib.request.Request(u, headers=UA)
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            b = r.read(200000)
            cs = r.headers.get_content_charset() or 'utf-8'
        t = b.decode(cs, 'replace')
        title = re.search(r'<title[^>]*>(.*?)</title>', t, flags=re.S | re.I)
        desc = (re.search(r'<meta[^>]+name=["\']description["\'][^>]*content=["\']([^"\']*)', t, flags=re.I)
                or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description', t, flags=re.I)
                or re.search(r'<meta[^>]+property=["\']og:description["\'][^>]*content=["\']([^"\']*)', t, flags=re.I))
        return h, {'title': clean(title.group(1))[:120] if title else '', 'desc': clean(desc.group(1))[:240] if desc else ''}
    except Exception as e:  # noqa
        return h, {'err': type(e).__name__}


t0 = time.time()
with ThreadPoolExecutor(16) as ex:
    res = dict(ex.map(fetch, urls.items()))
json.dump(res, open('web_meta.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
ok = sum(1 for v in res.values() if v.get('title') or v.get('desc'))
print(len(urls), 'siteden', ok, 'basarili', round(time.time() - t0), 'sn')

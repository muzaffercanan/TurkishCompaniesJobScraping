"""Hacettepe Teknokent firma detay sayfalarindan web sitesi + tanitim -> ht_details.json"""
import html, json, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0'}
raw = json.load(open('ankara_raw.json', encoding='utf-8'))
ht = [x for x in raw if x['source'] == 'Hacettepe Teknokent']


def clean(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', s))).strip()


def fetch(x):
    url = 'https://hacettepeteknokent.com.tr' + x['ht_page']
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                t = r.read().decode('utf-8', 'replace')
            break
        except Exception:
            time.sleep(1.5)
            t = ''
    web = re.search(r'fa-arrow-pointer"></i>\s*([^<\s]+)', t)
    desc = re.search(r'<div class="col-12 my-4">(.*?)</div>', t, flags=re.S)
    time.sleep(0.2)
    return {'ht_page': x['ht_page'], 'web': web.group(1).strip() if web else '', 'desc': clean(desc.group(1))[:300] if desc else ''}


with ThreadPoolExecutor(6) as ex:
    res = list(ex.map(fetch, ht))
json.dump(res, open('ht_details.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(len(res), 'web:', sum(1 for r in res if r['web']), 'desc:', sum(1 for r in res if r['desc']))

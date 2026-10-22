"""test_run ciktisini onceki veriyle karsilastirir ve scrape dogrulugunu orneklerle kontrol eder."""
import collections, json, random, re
import openpyxl

# 1) ham kayitlar
a = json.load(open('ankara_raw.json', encoding='utf-8'))
b = json.load(open('test_run/ankara_raw.json', encoding='utf-8'))
key = lambda x: (x['source'], x['name'])
sa, sb = {key(x) for x in a}, {key(x) for x in b}
print('HAM KAYIT  eski:', len(a), 'yeni:', len(b), '| yalniz eskide:', len(sa - sb), '| yalniz yenide:', len(sb - sa))
print('  kaynak bazinda eski:', dict(collections.Counter(x['source'] for x in a)))
print('  kaynak bazinda yeni:', dict(collections.Counter(x['source'] for x in b)))
print('  yalniz eskide ornek:', sorted(sa - sb)[:5], '| yalniz yenide ornek:', sorted(sb - sa)[:5])
wa = {key(x): x.get('web', '') for x in a}
wb_ = {key(x): x.get('web', '') for x in b}
print('  ODTU web adresi farki:', sum(1 for k in wa if k in wb_ and k[0] == 'ODTÜ Teknokent' and wa[k] != wb_[k]),
      '| web dolu eski/yeni:', sum(1 for k, v in wa.items() if k[0] == 'ODTÜ Teknokent' and v), sum(1 for k, v in wb_.items() if k[0] == 'ODTÜ Teknokent' and v))

# 2) son Excel
def load(p):
    ws = openpyxl.load_workbook(p)['Firmalar']
    return {r[1]: (r[2], r[4], r[5], r[6], r[10], r[15]) for r in ws.iter_rows(min_row=2, values_only=True)}
x_old, x_new = load('Turkiye_Yazilim_Firmalari_v2.xlsx'), load('test_run/Turkiye_Yazilim_Firmalari_v2.xlsx')
print('\nEXCEL  eski:', len(x_old), 'yeni:', len(x_new), '| yalniz eskide:', len(set(x_old) - set(x_new)), '| yalniz yenide:', len(set(x_new) - set(x_old)))
diff = [n for n in x_old if n in x_new and x_old[n] != x_new[n]]
print('  ayni adli ama alani farkli satir:', len(diff))
for n in diff[:6]:
    print('   ', n, '\n      eski:', x_old[n], '\n      yeni:', x_new[n])

# 3) dogruluk ornekleri: scrape edilen ad gercekten kaynak sayfada var mi (canli sayfadan tersten kontrol)
import urllib.request
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40).read().decode('utf-8', 'replace')
random.seed(11)
live_cp = ''.join(get(f'https://www.cyberpark.com.tr/firma-arsiv/{p}') for p in range(1, 20))
live_odtu = get('https://www.odtuteknokent.com.tr/assets/data/companies.json')
import html
live_cp = html.unescape(live_cp)
live_odtu = live_odtu
for src, pool, live in (('Bilkent Cyberpark', None, live_cp), ('ODTÜ Teknokent', None, live_odtu)):
    names = [x['name'] for x in b if x['source'] == src]
    sample = random.sample(names, 12)
    missing = [n for n in sample if (n.replace('"', '\\"') not in live and n not in live)]
    print(f'\n{src}: {len(sample)} rastgele ad canli sayfada aranirken bulunamayan: {len(missing)}', missing[:4])

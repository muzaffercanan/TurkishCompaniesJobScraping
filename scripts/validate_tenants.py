"""ATS eslesmelerini dogrula: slug baska bir sirketin hesabina denk gelmis olabilir (ornek: 'insider' = Business Insider).
Kural: hesapta en az 1 Turkiye konumlu ilan varsa kalir; yoksa yalnizca elle dogrulanmis global firmalar (GLOBAL_OK) kalir.
Elenenler ats_rejected.json'a yazilir. Kullanim: python scripts/validate_tenants.py   (once jobs_watch.py calismis olmali)"""
import json, sqlite3

GLOBAL_OK = {'OKX TR', 'Binance TR', 'Udemy (Ankara)', 'Binalyze'}  # gercek firma, ilanlari agirlikla yurt disi
db = sqlite3.connect('ilanlar.db')
tr = {f: n for f, n in db.execute("SELECT firm, SUM(region='Türkiye') FROM jobs WHERE active=1 GROUP BY firm")}
found = json.load(open('ats_found.json', encoding='utf-8'))
keep, rej = [], []
for x in found:
    n = tr.get(x['firma'], 0) or 0
    if n > 0 or x['firma'] in GLOBAL_OK:
        keep.append(x)
    else:
        rej.append({**x, 'neden': 'Turkiye konumlu ilan yok; baska sirketin hesabi olabilir'})
json.dump(keep, open('ats_found.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
json.dump(rej, open('ats_rejected.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for x in rej:
    db.execute('DELETE FROM jobs WHERE firm=?', (x['firma'],))
db.commit()
print(f'kalan {len(keep)} | elenen {len(rej)}:', ', '.join(f"{x['firma']} ({x['ats']}/{x['slug']})" for x in rej))

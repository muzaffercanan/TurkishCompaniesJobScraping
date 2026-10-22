"""Halka acik ATS API'lerinden ilanlari ceker, yerel SQLite ile karsilastirir, Excel rapor uretir.
Token harcamaz. Kullanim:  python scripts/jobs_watch.py            (ats_found.json + ats_manual.json'daki firmalar)
Cikti: ilanlar.db (gecmis), ilan_raporu.xlsx (rapor)"""
import datetime as dt, json, os, re, sqlite3, ssl, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as L

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0 (compatible; ilan-izleyici)'}
NOW = dt.datetime.now()
TODAY = NOW.strftime('%Y-%m-%d')


def get_json(url, tries=2):
    last = None
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25, context=ctx) as r:
                return json.loads(r.read().decode('utf-8', 'replace'))
        except Exception as e:  # noqa
            last = e
            time.sleep(1)
    raise RuntimeError(f'{type(last).__name__}: {last}')


def ms_to_date(ms):
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000).strftime('%Y-%m-%d')
    except (TypeError, ValueError, OSError):
        return None


def date10(s):
    m = re.match(r'(\d{4}-\d{2}-\d{2})', s or '')
    return m.group(1) if m else None


# ---- her ATS icin: slug -> [{id,title,location,team,url,posted}]
def lever(slug):
    out = []
    for j in get_json(f'https://api.lever.co/v0/postings/{slug}?mode=json'):
        c = j.get('categories') or {}
        loc = c.get('location') or ', '.join(c.get('allLocations') or [])
        out.append(dict(id=j['id'], title=j.get('text', ''), location=loc or '', team=c.get('team') or c.get('department') or '',
                        url=j.get('hostedUrl', ''), posted=ms_to_date(j.get('createdAt')), remote=(j.get('workplaceType') == 'remote')))
    return out


def greenhouse(slug):
    d = get_json(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs')
    return [dict(id=str(j['id']), title=j.get('title', ''), location=(j.get('location') or {}).get('name', ''), team='',
                 url=j.get('absolute_url', ''), posted=date10(j.get('first_published') or j.get('updated_at')), remote=False) for j in d['jobs']]


def ashby(slug):
    d = get_json(f'https://api.ashbyhq.com/posting-api/job-board/{slug}')
    return [dict(id=j['id'], title=j.get('title', ''), location=j.get('location', '') or '', team=j.get('department') or j.get('team') or '',
                 url=j.get('jobUrl', ''), posted=date10(j.get('publishedAt')), remote=bool(j.get('isRemote'))) for j in d['jobs'] if j.get('isListed', True)]


def recruitee(slug):
    d = get_json(f'https://{slug}.recruitee.com/api/offers/')
    return [dict(id=str(j['id']), title=j.get('title', ''), location=j.get('location', '') or j.get('city', '') or '', team=j.get('department') or '',
                 url=j.get('careers_url', ''), posted=date10(j.get('published_at') or j.get('created_at')), remote=bool(j.get('remote'))) for j in d['offers']]


def workable(slug):
    d = get_json(f'https://apply.workable.com/api/v1/widget/accounts/{slug}')
    return [dict(id=j.get('shortcode') or j.get('url', ''), title=j.get('title', ''), location=', '.join(x for x in (j.get('city'), j.get('country')) if x),
                 team=j.get('department') or '', url=j.get('url', ''), posted=date10(j.get('published_on')), remote=bool(j.get('telecommuting'))) for j in d.get('jobs', [])]


import adapters  # firmaya ozel okuyucular (scripts/adapters.py)

FETCH = {'lever': lever, 'greenhouse': greenhouse, 'ashby': ashby, 'recruitee': recruitee, 'workable': workable,
         'custom': lambda slug: adapters.REGISTRY[slug]()}

# ---- siniflandirma (basliga gore, kucuk harf + ascii)
TR = str.maketrans({'İ': 'i', 'I': 'i', 'ı': 'i', 'ş': 's', 'Ş': 's', 'ğ': 'g', 'Ğ': 'g', 'ü': 'u', 'Ü': 'u', 'ö': 'o', 'Ö': 'o', 'ç': 'c', 'Ç': 'c'})
norm = lambda s: (s or '').translate(TR).lower()
JUNIOR = re.compile(r'\bjunior\b|\bjr\b|entry.?level|new.?grad|graduate|yeni mezun|trainee|early career|campus|\bmt\b|management trainee|associate (software|engineer|developer)|baslangic')
STAJ = re.compile(r'\bintern\b|internship|stajyer|\bstaj\b|working student|apprentice')  # ogrenci statusu genelde sart: mezunlara uymayabilir
SENIOR = re.compile(r'\bsenior\b|\bsr\b|\blead\b|principal|\bstaff\b|manager|\bhead\b|director|architect|\bvp\b|chief|expert|uzman|mudur|yonetici')
TECH = re.compile(r'software|yazilim|developer|gelistirici|backend|back-end|frontend|front-end|full.?stack|\bdata\b|\bveri\b|machine learning|\bml\b|\bai\b|yapay zeka|\bdevops|\bsre\b|\bqa\b|\btest\b|testing|mobile|mobil|android|\bios\b|embedded|gomulu|firmware|security|siber|cyber|guvenlik|cloud|bulut|platform engineer|python|\bjava\b|golang|\bgo\b|react|node\.?js|\.net|c\+\+|\bit\b|bilgisayar|computer|network|database|veritaban|game|oyun|unity|unreal|algorithm|algoritma|simulasyon|simulation|arayuz|programmer|programci|swe\b|quant')
TR_LOC = re.compile(r'turk|t[uü]rkiye|istanbul|ankara|izmir|kocaeli|gebze|bursa|antalya|eskisehir|konya|adana|mersin|kayseri|turkey')
REMOTE = re.compile(r'remote|uzaktan|anywhere|hybrid|hibrit')


def classify(j):
    t = norm(j['title'])
    level = ('Junior / Yeni mezun' if JUNIOR.search(t) else 'Staj' if STAJ.search(t) else 'Kıdemli+' if SENIOR.search(t) else 'Seviye yazmıyor')
    tech = bool(TECH.search(t) or TECH.search(norm(j.get('team'))))
    loc = norm(j['location'])
    where = 'Türkiye' if TR_LOC.search(loc) else 'Uzaktan' if (j.get('remote') or REMOTE.search(loc)) else 'Yurt dışı' if loc.strip() else 'Belirsiz'
    return level, tech, where


# ---- veritabani
db = sqlite3.connect('ilanlar.db')
db.executescript('''
CREATE TABLE IF NOT EXISTS jobs(firm TEXT, ats TEXT, job_id TEXT, title TEXT, location TEXT, team TEXT, url TEXT, posted TEXT,
  level TEXT, tech INTEGER, region TEXT, first_seen TEXT, last_seen TEXT, active INTEGER, PRIMARY KEY(firm, ats, job_id));
CREATE TABLE IF NOT EXISTS runs(run_at TEXT, firm TEXT, ats TEXT, slug TEXT, ok INTEGER, count INTEGER, error TEXT);
''')

targets = json.load(open('ats_found.json', encoding='utf-8')) if os.path.exists('ats_found.json') else []
if os.path.exists('ats_manual.json'):  # elle eklenenler: [{"firma":"..","ats":"lever","slug":".."}]
    targets += json.load(open('ats_manual.json', encoding='utf-8'))
seen_t, uniq = set(), []
for t in targets:
    k = (t['firma'], t['ats'], t['slug'])
    if k not in seen_t:
        seen_t.add(k); uniq.append(t)
print('izlenen firma/kaynak:', len(uniq))


def run(t):
    try:
        return t, FETCH[t['ats']](t['slug']), None
    except Exception as e:  # noqa
        return t, None, str(e)[:200]


with ThreadPoolExecutor(8) as ex:
    results = list(ex.map(run, uniq))

new_rows, closed_rows, warnings = [], [], []
for t, jobs, err in results:
    firm, ats, slug = t['firma'], t['ats'], t['slug']
    if err or jobs is None:
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)', (NOW.isoformat(timespec='seconds'), firm, ats, slug, 0, 0, err))
        warnings.append(f'{firm} ({ats}/{slug}): {err}')
        continue
    prev = db.execute('SELECT COUNT(*) FROM jobs WHERE firm=? AND ats=? AND active=1', (firm, ats)).fetchone()[0]
    if not jobs and prev > 3:  # sessiz bozulma: onceden ilan vardi, simdi 0
        warnings.append(f'{firm}: onceki calistirmada {prev} ilan vardi, simdi 0 geldi - kaynak degismis olabilir (kapananlar isaretlenmedi)')
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)', (NOW.isoformat(timespec='seconds'), firm, ats, slug, 0, 0, 'sifir ilan uyarisi'))
        continue
    db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)', (NOW.isoformat(timespec='seconds'), firm, ats, slug, 1, len(jobs), None))
    ids = set()
    for j in jobs:
        ids.add(j['id'])
        level, tech, region = classify(j)
        row = db.execute('SELECT first_seen FROM jobs WHERE firm=? AND ats=? AND job_id=?', (firm, ats, j['id'])).fetchone()
        if row:
            db.execute('UPDATE jobs SET title=?,location=?,team=?,url=?,posted=?,level=?,tech=?,region=?,last_seen=?,active=1 WHERE firm=? AND ats=? AND job_id=?',
                       (j['title'], j['location'], j['team'], j['url'], j['posted'], level, int(tech), region, TODAY, firm, ats, j['id']))
        else:
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)',
                       (firm, ats, j['id'], j['title'], j['location'], j['team'], j['url'], j['posted'], level, int(tech), region, TODAY, TODAY))
    for (jid, title, url) in db.execute('SELECT job_id,title,url FROM jobs WHERE firm=? AND ats=? AND active=1', (firm, ats)).fetchall():
        if jid not in ids:
            db.execute('UPDATE jobs SET active=0 WHERE firm=? AND ats=? AND job_id=?', (firm, ats, jid))
            closed_rows.append((firm, title, url))
db.commit()

first_run = db.execute('SELECT COUNT(DISTINCT run_at) FROM runs').fetchone()[0] <= 1

# ---- rapor
cols = ['Firma', 'İlan başlığı', 'Seviye', 'Konum', 'Bölge', 'Ekip', 'Yayın tarihi', 'Yaş (gün)', 'İlk görüldü', 'Kaynak', 'Bağlantı']


def fetch_rows(where):
    q = f'SELECT firm,title,level,location,region,team,posted,first_seen,ats,url FROM jobs WHERE {where} ORDER BY firm,title'
    rows = []
    for firm, title, level, loc, region, team, posted, fs, ats, url in db.execute(q):
        ref = posted or fs
        age = (NOW.date() - dt.date.fromisoformat(ref)).days if ref else None
        rows.append([firm, title, level, loc, region, team, posted or '', age, fs, ats, url])
    return rows


rep_wb = openpyxl.Workbook()


def sheet(name, rows, note=None):
    ws = rep_wb.create_sheet(name)
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF'); c.fill = PatternFill('solid', fgColor='1F3A5F'); c.alignment = Alignment(wrap_text=True, vertical='center')
    for r in rows:
        ws.append(r)
        cell = ws.cell(ws.max_row, 11)
        if r[10]:
            cell.hyperlink = r[10]; cell.font = Font(color='0563C1', underline='single')
        if isinstance(r[7], int) and r[7] > 90 and r[8] and r[6]:  # yayin tarihi bilinen ve 90 gunden eski
            ws.cell(ws.max_row, 8).fill = PatternFill('solid', fgColor='FCE4D6')
    for i, w in enumerate([22, 52, 14, 28, 11, 22, 12, 9, 12, 11, 60], 1):
        ws.column_dimensions[L(i)].width = w
    ws.freeze_panes = 'C2'
    ws.auto_filter.ref = f'A1:{L(len(cols))}{max(ws.max_row, 2)}'
    return ws


active_tech = "active=1 AND tech=1"
rep_wb.remove(rep_wb.active)
junior = fetch_rows(f"{active_tech} AND level='Junior / Yeni mezun' AND region IN ('Türkiye','Uzaktan','Belirsiz')")
sheet('Junior-Yeni mezun (TR+Uzaktan)', junior)
staj = fetch_rows(f"{active_tech} AND level='Staj' AND region IN ('Türkiye','Uzaktan','Belirsiz')")
sheet('Staj programları (TR)', staj)
sheet('Yeni ilanlar' if not first_run else 'İlk tarama (hepsi yeni)', fetch_rows(f"{active_tech} AND first_seen='{TODAY}' AND region IN ('Türkiye','Uzaktan','Belirsiz')"))
sheet('Seviye yazmıyor (TR)', fetch_rows(f"{active_tech} AND level='Seviye yazmıyor' AND region IN ('Türkiye','Belirsiz')"))
sheet('Tüm aktif teknik ilanlar', fetch_rows(active_tech))
ws = rep_wb.create_sheet('Kapananlar')
ws.append(['Firma', 'İlan başlığı', 'Bağlantı'])
for r in closed_rows:
    ws.append(list(r))
ws = rep_wb.create_sheet('Uyarılar-Taranamayan')
ws.append(['Uyarı'])
for w in warnings:
    ws.append([w])
ws = rep_wb.create_sheet('Firma özeti')
ws.append(['Firma', 'Kaynak', 'Aktif ilan', 'Teknik', 'Junior/Staj (TR+Uzaktan)'])
for firm, ats, n, tech, jn in db.execute("""SELECT firm, ats, SUM(active), SUM(CASE WHEN active=1 AND tech=1 THEN 1 ELSE 0 END),
    SUM(CASE WHEN active=1 AND tech=1 AND level='Junior / Yeni mezun' AND region IN ('Türkiye','Uzaktan','Belirsiz') THEN 1 ELSE 0 END) FROM jobs GROUP BY firm, ats ORDER BY 3 DESC"""):
    ws.append([firm, ats, n, tech, jn])
rep_wb.save('ilan_raporu.xlsx')

tot = db.execute('SELECT COUNT(*) FROM jobs WHERE active=1').fetchone()[0]
tech_n = db.execute('SELECT COUNT(*) FROM jobs WHERE active=1 AND tech=1').fetchone()[0]
print(f'\nTarandi: {len(uniq) - len(warnings)} basarili / {len(warnings)} uyari | aktif ilan: {tot} (teknik: {tech_n}) | junior/staj (TR+uzaktan): {len(junior)} | yeni bugun: {0 if first_run else "?"} | kapanan: {len(closed_rows)}')
print('\n--- JUNIOR / STAJ ILANLARI (TR + uzaktan) ---')
for r in junior[:60]:
    age = f"{r[7]}g" if isinstance(r[7], int) else '?'
    print(f"  {r[0][:22]:22s} | {r[1][:58]:58s} | {r[3][:26]:26s} | yas {age:>5s} | {r[10]}")
if warnings:
    print('\nUYARILAR:'); [print('  ', w) for w in warnings[:15]]

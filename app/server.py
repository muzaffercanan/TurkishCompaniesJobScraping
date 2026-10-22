"""Yerel web uygulamasi. Calistir: python -m app.server  (ya da Baslat.bat)
Yalnizca bu bilgisayardan erisilir (127.0.0.1)."""
import datetime as dt
import os
import sys
import threading
import webbrowser

from flask import Flask, g, jsonify, request, send_from_directory

from . import db, scanner, search, seniority

HOST = '127.0.0.1'
PORT = int(sys.argv[sys.argv.index('--port') + 1]) if '--port' in sys.argv else 8765
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _code_stamp():
    """Uygulama kodunun (app/*.py ve app/static/*) en son degisme zamani."""
    stamps = [os.path.getmtime(os.path.join(d, f)) for d in (APP_DIR, STATIC) for f in os.listdir(d)
              if f.endswith(('.py', '.js', '.css', '.html'))]
    return max(stamps) if stamps else 0


CODE_STAMP = _code_stamp()  # bu sunucunun yukledigi kodun damgasi
app = Flask(__name__, static_folder=None)
_c = db.connect()
db.import_excel(_c)
db.sync_excel(_c)


@app.before_request
def _open_db():
    g.con = db.connect()


@app.teardown_request
def _close_db(_exc):
    c = g.pop('con', None)
    if c is not None:
        c.close()


@app.get('/')
def index():
    return send_from_directory(STATIC, 'index.html')


@app.get('/static/<path:p>')
def static_files(p):
    return send_from_directory(STATIC, p)


def _distinct(col, table='companies'):
    return [r[0] for r in g.con.execute(f'SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL AND {col}!="" ORDER BY 1')]


@app.get('/api/meta')
def meta():
    last = g.con.execute('SELECT * FROM scans ORDER BY id DESC LIMIT 1').fetchone()
    st = {r[0] or 'taranmadi': r[1] for r in g.con.execute('SELECT status, COUNT(*) FROM companies GROUP BY status')}
    today = dt.date.today().isoformat()
    counts = dict(g.con.execute('''SELECT
        COALESCE(SUM(active=1 AND hidden=0 AND first_seen=?), 0) AS new_today,
        COALESCE(SUM(active=1 AND hidden=0 AND level IN ('Junior / Yeni mezun','Staj')), 0) AS entry,
        COALESCE(SUM(starred=1), 0) AS starred, COALESCE(SUM(applied=1), 0) AS applied,
        COALESCE(SUM(hidden=1), 0) AS hidden FROM jobs''', (today,)).fetchone())
    return jsonify(
        code_stale=_code_stamp() > CODE_STAMP + 1,  # diskteki kod, calisan sunucudan yeni: yeniden baslatilmali
        counts=counts,
        categories=_distinct('category'), cities=_distinct('city'), sizes=_distinct('size'),
        sources=_distinct('source', 'jobs'), levels=seniority.LEVELS,
        statuses=st,
        totals=dict(companies=g.con.execute('SELECT COUNT(*) FROM companies').fetchone()[0],
                    with_site=g.con.execute('SELECT COUNT(*) FROM companies WHERE website IS NOT NULL').fetchone()[0],
                    jobs=g.con.execute('SELECT COUNT(*) FROM jobs WHERE active=1').fetchone()[0],
                    companies_with_jobs=g.con.execute('SELECT COUNT(DISTINCT company_id) FROM jobs WHERE active=1').fetchone()[0]),
        last_scan=dict(last) if last else None)


@app.get('/api/jobs')
def jobs():
    a = request.args
    where, args = ['1=1'], []
    if a.get('active', '1') == '1':
        where.append('j.active=1')
    if a.get('hidden') == 'only':
        where.append('j.hidden=1')
    elif a.get('hidden', '0') != '1':
        where.append('j.hidden=0')
    if a.get('applied') == 'hide':
        where.append('j.applied=0')
    elif a.get('applied') == 'only':
        where.append('j.applied=1')
    if a.get('starred') == 'only':
        where.append('j.starred=1')
    if a.get('q'):
        if a.get('indesc') == '1':  # ilan aciklamasinda da ara (or. "python", "0-2 yil")
            where.append('(j.title LIKE ? OR c.name LIKE ? OR j.location LIKE ? OR j.team LIKE ? OR j.description LIKE ?)')
            args += [f'%{a["q"]}%'] * 5
        else:
            where.append('(j.title LIKE ? OR c.name LIKE ? OR j.location LIKE ? OR j.team LIKE ?)')
            args += [f'%{a["q"]}%'] * 4
    for key, col in (('category', 'c.category'), ('city', 'c.city'), ('size', 'c.size'), ('source', 'j.source'), ('level', 'j.level')):
        vals = [v for v in a.getlist(key) if v]
        if vals:
            where.append(f'{col} IN ({",".join("?" * len(vals))})')
            args += vals
    reg = a.get('region')
    if reg == 'tr+':
        where.append("j.region IN ('Türkiye','Uzaktan','Belirtilmemiş')")
    elif reg:
        where.append('j.region=?')
        args.append(reg)
    if a.get('tech') == '1':
        where.append('j.is_tech=1')
    if a.get('days'):
        where.append('j.first_seen >= ?')
        args.append((dt.date.today() - dt.timedelta(days=int(a['days']))).isoformat())
    if a.get('company_id'):
        where.append('j.company_id=?')
        args.append(int(a['company_id']))
    order = {'new': 'j.first_seen DESC, j.id DESC', 'company': 'c.name, j.title', 'title': 'j.title',
             'posted': 'COALESCE(j.posted, j.first_seen) DESC'}.get(a.get('sort'), 'j.first_seen DESC, j.id DESC')
    rows = g.con.execute(f'''SELECT j.id, j.company_id, j.source, j.title, j.location, j.team, j.url, j.posted, j.first_seen, j.last_seen,
                           j.active, j.level, j.is_tech, j.applied, j.hidden, j.starred, j.region, j.exp_min,
                           (j.note IS NOT NULL AND j.note!='') AS has_note,
                           c.name AS company, c.category, c.city AS company_city, c.size, c.website
                           FROM jobs j JOIN companies c ON c.id=j.company_id WHERE {" AND ".join(where)}
                           ORDER BY {order} LIMIT 5000''', args).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get('/api/jobs/<int:jid>')
def job_detail(jid):
    """Tek ilanin tum alanlari (aciklama ve not dahil); liste ucu bunlari tasimaz."""
    r = g.con.execute('''SELECT j.id, j.company_id, j.source, j.title, j.location, j.team, j.url, j.posted, j.first_seen, j.last_seen,
                         j.active, j.level, j.applied, j.hidden, j.starred, j.region, j.exp_min, j.description, j.note,
                         c.name AS company, c.category, c.city AS company_city, c.size, c.website, c.career_url
                         FROM jobs j JOIN companies c ON c.id=j.company_id WHERE j.id=?''', (jid,)).fetchone()
    return (jsonify(dict(r)) if r else (jsonify(error='bulunamadi'), 404))


@app.post('/api/jobs/<int:jid>')
def job_update(jid):
    d = request.get_json(force=True)
    for f in ('applied', 'hidden', 'starred'):
        if f in d:
            db.write(g.con, f'UPDATE jobs SET {f}=? WHERE id=?', (1 if d[f] else 0, jid))
    if 'note' in d:
        db.write(g.con, 'UPDATE jobs SET note=? WHERE id=?', ((d['note'] or '').strip()[:4000] or None, jid))
    return jsonify(ok=True)


@app.get('/api/companies')
def companies():
    a = request.args
    where, args = ['1=1'], []
    if a.get('q'):
        where.append('(name LIKE ? OR website LIKE ?)')
        args += [f'%{a["q"]}%'] * 2
    if a.get('status'):
        where.append("COALESCE(status,'taranmadi')=?")
        args.append(a['status'])
    rows = g.con.execute(f'''SELECT * FROM companies WHERE {" AND ".join(where)}
                           ORDER BY job_count DESC, name LIMIT 3000''', args).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post('/api/companies/<int:cid>')
def company_update(cid):
    d = request.get_json(force=True)
    if 'website' in d:
        db.write(g.con, "UPDATE companies SET website=?, website_source='manuel', checked_at=NULL WHERE id=?", (d['website'] or None, cid))
    if 'career_url' in d:  # elle verilen kariyer sayfasi: ATS'i yeniden tespit ettirmek icin kesfi sifirla
        db.write(g.con, "UPDATE companies SET career_url=?, ats=CASE WHEN ats='custom' THEN ats ELSE 'generic' END, checked_at=? WHERE id=?",
                 (d['career_url'] or None, None, cid))
    return jsonify(ok=True)


@app.get('/api/config')
def get_config():
    cfg = search.load_config()
    k = cfg.get('brave_api_key') or ''
    candidates = len(search.candidates_for([dict(r) for r in g.con.execute('SELECT * FROM companies')]))
    return jsonify(brave_key_set=bool(k), brave_key_hint=(k[:4] + '…' + k[-3:]) if len(k) > 8 else '', site_candidates=candidates)


@app.post('/api/config')
def set_config():
    d = request.get_json(force=True)
    cfg = search.load_config()
    if 'brave_api_key' in d:
        cfg['brave_api_key'] = (d['brave_api_key'] or '').strip()
    search.save_config(cfg)
    return jsonify(ok=True)


@app.get('/api/health')
def health():
    """Kaynak sagligi: her kaynagin son iki taramasi, ani dususler, kimlik kararsizligi ve hatalar."""
    rows = g.con.execute('''
        WITH r AS (SELECT sr.*, ROW_NUMBER() OVER (PARTITION BY company_id ORDER BY id DESC) AS n FROM source_runs sr)
        SELECT c.id, c.name, c.ats, c.status, c.status_note, a.run_at, a.source, a.ok, a.count, a.new, a.closed, a.prev_active,
               a.overlap, a.error, b.count AS prev_count, b.ok AS prev_ok,
               (SELECT COUNT(*) FROM source_runs x WHERE x.company_id=c.id AND x.ok=0) AS fail_total
        FROM r a JOIN companies c ON c.id=a.company_id LEFT JOIN r b ON b.company_id=a.company_id AND b.n=2
        WHERE a.n=1 ORDER BY a.ok, c.name''').fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d['source'] == 'kesif' and d['ok']:
            continue  # ilan kaynagi olmayan firma: saglik listesinde gosterilmez
        flags = scanner.health_flags(d['prev_active'] or 0, d['count'] or 0, d['overlap'])
        if not d['ok']:
            flags.insert(0, 'son tarama hata verdi: ' + (d['error'] or '')[:120])
        if d['count'] == 0 and (d['prev_count'] or 0) > 0:
            flags.append('ilan sayisi sifira dustu')
        d['flags'] = flags
        d['level'] = 'kotu' if not d['ok'] else 'uyari' if flags else 'iyi'
        out.append(d)
    order = {'kotu': 0, 'uyari': 1, 'iyi': 2}
    out.sort(key=lambda x: (order[x['level']], x['name']))
    return jsonify(out)


@app.post('/api/companies/<int:cid>/scan')
def company_scan(cid):
    return jsonify(started=scanner.start('firma', cid))


@app.post('/api/scan')
def scan():
    mode = (request.get_json(silent=True) or {}).get('mode', 'hizli')
    if mode == 'site' and not (search.load_config().get('brave_api_key') or '').strip():
        return jsonify(started=False, error='Önce Firmalar sekmesinden arama API anahtarını gir.')
    return jsonify(started=scanner.start(mode if mode in ('hizli', 'tam', 'yeni', 'site', 'program') else 'hizli'))


@app.get('/api/scan/status')
def scan_status():
    s = dict(scanner.STATE)
    s['log'] = list(scanner.STATE['log'])[-120:]
    return jsonify(s)


def _already_running(url):
    """Ayni portta calisan bir Ilan Radari var mi? (Windows'ta iki sunucu ayni portu dinleyebilir; istekler eskisine gidebilir.)"""
    import urllib.request
    try:
        with urllib.request.urlopen(url + 'api/meta', timeout=1.5) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main():
    url = f'http://{HOST}:{PORT}/'
    if _already_running(url):
        print(f'Ilan Radari zaten acik: {url}')
        print('Kod guncellendiyse once acik olan siyah pencereyi kapatin, sonra Baslat.bat ile yeniden acin.')
        if '--no-browser' not in sys.argv:
            webbrowser.open(url)
        return
    if os.environ.get('NO_BROWSER') != '1' and '--no-browser' not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f'Uygulama acik: {url}  (kapatmak icin bu pencereyi kapatin)')
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == '__main__':
    main()

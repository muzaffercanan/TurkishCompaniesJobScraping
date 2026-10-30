"""SQLite veritabani: firmalar, ilanlar, taramalar. Excel yalnizca OKUNUR (ilk aktarimda)."""
import datetime as dt
import functools
import json
import os
import re
import sqlite3
import threading
import unicodedata

ROOT =os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, 'data', 'app.db')
XLSX = os.path.join(ROOT, 'Turkiye_Yazilim_Firmalari_v2.xlsx')
_lock = threading.Lock()
_tls = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT, city TEXT, size TEXT, focus TEXT,
  website TEXT, website_source TEXT, career_url TEXT, ats TEXT, ats_slug TEXT,
  status TEXT, status_note TEXT, last_scan TEXT, job_count INTEGER DEFAULT 0, excel_row INTEGER);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY, company_id INTEGER, source TEXT, ext_id TEXT, title TEXT, location TEXT, team TEXT,
  url TEXT, posted TEXT, first_seen TEXT, last_seen TEXT, active INTEGER DEFAULT 1, level TEXT, is_tech INTEGER,
  applied INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, UNIQUE(company_id, source, ext_id));
CREATE TABLE IF NOT EXISTS scans(
  id INTEGER PRIMARY KEY, started TEXT, finished TEXT, mode TEXT, companies INTEGER, ok INTEGER, failed INTEGER,
  new_jobs INTEGER, closed_jobs INTEGER);
CREATE INDEX IF NOT EXISTS ix_jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS ix_jobs_active ON jobs(active);
"""


@functools.lru_cache(maxsize=16384)  # ayni ilan metinleri her aramada yeniden sadelestirilmesin (aciklamada arama ~10x hizlanir)
def fold(s):
    """Arama/siralama icin metni sadelestirir: buyuk-kucuk harf ve Turkce/aksan farki yok sayilir
    (Izmir = İZMİR = izmir, yazılım = yazilim, Şirket = sirket)."""
    if not s:
        return ''
    s = str(s)
    if not s.isascii():
        s = unicodedata.normalize('NFKD', s.replace('ı', 'i'))
        s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower()


NEW_DAYS = 3  # "yeni ilan" penceresi (gun); arayuzdeki "3 gun" secimiyle ayni
_ISO = "j.posted GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'"
# Bir ilan "yeni" sayilir: yayin tarihi pencerede YA DA kaynagin ilk taramasindan SONRA bulunmus ve ilk gorulme tarihi pencerede.
# Ilk taramadaki ilanlar siteye o gun eklenmedi, yalnizca o gun ilk kez goruldu; yayin tarihi de yoksa yeni sayilmaz.
# jobs tablosu 'j' takma adiyla kullanilmali; iki '?' alir: (yayin esigi, ilk gorulme esigi), ikisi de cutoff(gun).
RECENT = f"(({_ISO} AND j.posted >= ?) OR (j.is_baseline=0 AND j.first_seen >= ?))"


def cutoff(days):
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


# "Bana uygun" (arayuzdeki hazir filtre ile ayni): junior / staj, yazilim-teknik, Turkiye / uzaktan / konumu belirtilmemis.
# jobs tablosu 'j' takma adiyla kullanilmali.
FIT_LEVELS = ('Junior / Yeni mezun', 'Staj')
FIT = "(j.level IN ('Junior / Yeni mezun','Staj') AND j.is_tech=1 AND j.region IN ('Türkiye','Uzaktan','Belirtilmemiş'))"


def search_clauses(q, cols):
    """Arama kutusu metnini SQL kosullarina cevirir: her kelime sutunlardan en az birinde gecmeli (kelime sirasi onemsiz;
    basinda '-' olan kelimeler ise hicbir sutunda gecmemeli: or. 'backend -senior').
    Dondurur: ([kosul, ...], [arguman, ...]). Sutunlar trn() ile sadelestirilir."""
    clauses, args = [], []
    for w in fold(q).split():
        neg = w.startswith('-') and len(w) > 1
        if neg:
            w = w[1:]
        w = w.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        if neg:
            clauses.append('(' + ' AND '.join(f"COALESCE(trn({c}), '') NOT LIKE ? ESCAPE '\\'" for c in cols) + ')')
        else:
            clauses.append('(' + ' OR '.join(f"trn({c}) LIKE ? ESCAPE '\\'" for c in cols) + ')')
        args += [f'%{w}%'] * len(cols)
    return clauses, args


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute('PRAGMA table_info(companies)')}
    for col in ('ats_extra', 'checked_at', 'merged_into', 'program_urls', 'program_checked'):
        if col not in cols:
            con.execute(f'ALTER TABLE companies ADD COLUMN {col} TEXT')
    con.execute('''CREATE TABLE IF NOT EXISTS source_runs(
        id INTEGER PRIMARY KEY, run_at TEXT, company_id INTEGER, source TEXT, ok INTEGER, count INTEGER,
        new INTEGER, closed INTEGER, prev_active INTEGER, overlap REAL, error TEXT)''')
    con.execute('CREATE INDEX IF NOT EXISTS ix_runs_company ON source_runs(company_id, id)')
    jcols = {r[1] for r in con.execute('PRAGMA table_info(jobs)')}
    for col, typ in (('region', 'TEXT'), ('description', 'TEXT'), ('exp_min', 'INTEGER'), ('detail_checked', 'INTEGER'),
                     ('detail_kind', 'TEXT'), ('detail_url', 'TEXT'), ('starred', 'INTEGER DEFAULT 0'), ('note', 'TEXT'),
                     ('is_baseline', 'INTEGER DEFAULT 0'), ('seen', 'INTEGER DEFAULT 0'), ('stage', 'TEXT'), ('applied_at', 'TEXT')):
        if col not in jcols:
            con.execute(f'ALTER TABLE jobs ADD COLUMN {col} {typ}')
            if col == 'is_baseline':  # eski kayitlar: kaynagin daha onceki bir gunde basarili taramasi yoksa ilk taramadandir
                con.execute('''UPDATE jobs SET is_baseline = CASE WHEN EXISTS(
                                 SELECT 1 FROM source_runs r WHERE r.company_id=jobs.company_id AND r.source=jobs.source AND r.ok=1
                                 AND substr(r.run_at,1,10) < jobs.first_seen) THEN 0 ELSE 1 END''')
                con.commit()
            elif col == 'seen':  # kullanicinin zaten islem yaptigi ilanlar gorulmus sayilir
                con.execute("UPDATE jobs SET seen=1 WHERE applied=1 OR hidden=1 OR starred=1 OR (note IS NOT NULL AND note!='')")
                con.commit()
            elif col == 'stage':
                con.execute("UPDATE jobs SET stage='basvuruldu' WHERE applied=1 AND stage IS NULL")
                con.commit()
    con.create_function('trn', 1, fold, deterministic=True)  # arama / siralama: SQL'de trn(sutun)
    return con


def tl():
    """Is parcacigina ozel baglanti (sqlite3 baglantilari is parcaciklari arasinda paylasilmamali)."""
    c = getattr(_tls, 'con', None)
    if c is None:
        c = _tls.con = connect()
    return c


def write(con, sql, args=()):
    """Coklu is parcacigi icin kilitli yazma."""
    with _lock:
        cur = con.execute(sql, args)
        con.commit()
        return cur


def import_excel(con, path=XLSX):
    """Excel'deki firmalari aktar (yalnizca bos veritabaninda). Excel degistirilmez."""
    if con.execute('SELECT COUNT(*) FROM companies').fetchone()[0]:
        return 0
    import openpyxl
    ws = openpyxl.load_workbook(path)['Firmalar']
    rows = []
    for r in ws.iter_rows(min_row=2):
        name = r[1].value
        if not name:
            continue
        w = r[10]
        web = w.hyperlink.target if w.hyperlink else (('https://' + str(w.value)) if w.value else None)
        rows.append((name, r[2].value, r[4].value, r[5].value, r[6].value, web, 'excel' if web else None, r[0].row))
    with _lock:
        con.executemany('INSERT INTO companies(name,category,city,size,focus,website,website_source,excel_row) VALUES(?,?,?,?,?,?,?,?)', rows)
        con.commit()
    _seed_known_sources(con)
    return len(rows)


def sync_excel(con, path=XLSX):
    """Excel'e sonradan eklenen firmalari veritabanina al (ad bazinda; mevcutlara dokunmaz). Eklenen sayi doner."""
    import openpyxl
    if not os.path.exists(path):
        return 0
    have = {r[0] for r in con.execute('SELECT name FROM companies')}
    ws = openpyxl.load_workbook(path)['Firmalar']
    rows = []
    for r in ws.iter_rows(min_row=2):
        name = r[1].value
        if not name or name in have:
            continue
        w = r[10]
        web = w.hyperlink.target if w.hyperlink else (('https://' + str(w.value)) if w.value else None)
        if web:
            web = re.sub(r'^https?://(?=https?://)', '', web)  # "http://https://..." cift sema
        if web and '.' not in web.split('://')[-1].split('/')[0]:
            web = None  # "https://" gibi bos adresler
        rows.append((name, r[2].value, r[4].value, r[5].value, r[6].value, web, 'excel' if web else None, r[0].row))
        have.add(name)
    if rows:
        with _lock:
            con.executemany('INSERT INTO companies(name,category,city,size,focus,website,website_source,excel_row) VALUES(?,?,?,?,?,?,?,?)', rows)
            con.commit()
    return len(rows)


def _seed_known_sources(con):
    """Onceki calismada dogrulanan ATS eslesmelerini ve firma okuyucularini tasi."""
    seeds = []
    for f in ('ats_found.json', 'ats_manual.json'):
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            seeds += json.load(open(p, encoding='utf-8'))
    with _lock:
        for s in seeds:
            name = s['firma']
            row = con.execute('SELECT id FROM companies WHERE name=? OR name LIKE ? ORDER BY length(name) LIMIT 1',
                              (name, name + '%')).fetchone()
            if row:
                con.execute('UPDATE companies SET ats=?, ats_slug=? WHERE id=?', (s['ats'], s['slug'], row['id']))
            else:  # listede yoksa (or. Amazon) yeni firma olarak ekle
                con.execute('INSERT INTO companies(name, ats, ats_slug, website_source) VALUES(?,?,?,?)',
                            (s['firma'], s['ats'], s['slug'], 'manuel'))
        con.commit()

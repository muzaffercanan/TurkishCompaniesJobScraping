"""Tarama motoru. Modlar:
  hizli : bilinen ATS ve firmaya ozel okuyucular + kariyer sayfasindan ilan veren firmalar
  tam   : tum firmalar; gerekiyorsa kariyer sayfasi kesfi + gercek tarayiciyla genel ayristirma
  yeni  : yalnizca hic kesfedilmemis (yeni eklenen) firmalar
  site  : arama API'si ile sitesi bilinmeyen firmalarin sitesini bul, sonra 'yeni' gibi tara
  firma : tek bir firmayi yeniden kesfet ve tara
Ilerleme STATE sozlugunde tutulur; web arayuzu buradan okur."""
import collections
import datetime as dt
import json
import queue
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import ats as atsmod
from . import browser, careers, custom, db, enrich, generic, programs, seniority
from .util import host_of, norm

# Is ilani siteleri: kendi sitelerinde baska sirketlerin ilanlarini yayinliyorlar ve otomatik toplamaya izin vermiyorlar.
# Bu firmalar listede olsa bile kariyer sayfalari taranmaz (Arama kisayollari sekmesinden acilir).
JOB_BOARDS = ('kariyer.net', 'eleman.net', 'secretcv.com', 'youthall.com', 'techcareer.net', 'coderspace.io', 'linkedin.com',
              'indeed.com', 'glassdoor.com', 'yenibiris.com', 'careerjet.com.tr', 'isbul.net', 'anbeankampus.co', 'toptalent.co',
              'kariyerkapisi.cbiko.gov.tr')


def is_job_board(website):
    h = host_of(website or '')
    return any(h == b or h.endswith('.' + b) for b in JOB_BOARDS)

STATE = dict(running=False, mode=None, phase='', total=0, done=0, current='', started=None, finished=None,
             new=0, closed=0, ok=0, failed=0, log=collections.deque(maxlen=500))
_run_lock = threading.Lock()
REDISCOVER_DAYS = 14  # kariyer sayfasi bulunamayan firmalar bu kadar gunde bir yeniden kesfedilir

# ------------------------------------------------------------------ siniflandirma (eleme yok, yalnizca etiket)
JUNIOR = re.compile(r'\bjunior\b|\bjr\b|entry.?level|new.?grad|graduate|yeni mezun|trainee|early career|campus|\bmt\b|'
                    r'management trainee|associate (software|engineer|developer)|uzman yardimcisi|genc yetenek|young talent')
STAJ = re.compile(r'\bintern\b|internship|stajyer|\bstaj\b|working student|apprentice|summer internship')
SENIOR = re.compile(r'\bsenior\b|\bsr\b|\blead\b|principal|\bstaff\b|manager|\bhead\b|director|architect|\bvp\b|chief|expert|'
                    r'kidemli|mudur|yonetici|direktor|\bsef\b|lider')
TECH = re.compile(r'software|yazilim|developer|gelistirici|backend|back-end|frontend|front-end|full.?stack|\bdata\b|\bveri\b|'
                  r'machine learning|\bml\b|\bai\b|yapay zeka|devops|\bsre\b|\bqa\b|\btest\b|testing|mobile|mobil|android|\bios\b|'
                  r'embedded|gomulu|firmware|security|siber|cyber|guvenlik|cloud|bulut|platform|python|\bjava\b|golang|\bgo\b|react|'
                  r'node|\.net|c\+\+|\bit\b|bilgi teknoloj|bilgisayar|computer|network|database|veritaban|game|oyun|unity|unreal|'
                  r'algorithm|algoritma|simulasyon|simulation|arayuz|programmer|programci|quant|engineer|muhendis|analyst|analist|'
                  r'sistem|system|bilisim|dijital|digital')


TR_LOC = re.compile(r'turk|turkiye|istanbul|ankara|izmir|kocaeli|gebze|bursa|antalya|eskisehir|konya|adana|mersin|kayseri|'
                    r'sakarya|maslak|levent|kadikoy|atasehir|sariyer|besiktas|sisli|umraniye|kucukyali|pendik|tuzla|cankaya|odtu|bilkent')
REMOTE = re.compile(r'remote|uzaktan|anywhere|hybrid|hibrit|work from home')


def region_of(location, remote=False):
    l = norm(location)
    if TR_LOC.search(l):
        return 'Türkiye'
    if remote or REMOTE.search(l):
        return 'Uzaktan'
    return 'Yurt dışı' if l.strip(' ,-') else 'Belirtilmemiş'


def classify(title, team=''):
    """Basliktan seviye + teknik mi. Baslik seviye vermiyorsa 'Belirtilmemiş' doner (aciklamaya seniority.py bakar)."""
    t = norm(title)
    level = 'Junior / Yeni mezun' if JUNIOR.search(t) else 'Staj' if STAJ.search(t) else 'Kıdemli+' if SENIOR.search(t) else 'Belirtilmemiş'
    return level, int(bool(TECH.search(t) or TECH.search(norm(team))))


# ------------------------------------------------------------------ yardimcilar
def _log(msg):
    STATE['log'].append(f"{dt.datetime.now():%H:%M:%S} {msg}")


def _today():
    return dt.date.today().isoformat()


def upsert(con, company_id, source, jobs, definitive=True, guard=True):
    """Ilanlari ekle/guncelle. definitive=True ise listede olmayan aktif ilanlar kapatilir.
    Dondurur: (yeni, kapanan, onceki_aktif_sayisi, ortusme_orani, yeni_ilan_id_listesi)"""
    now, new = _today(), 0
    prev = db.tl().execute('SELECT id, ext_id FROM jobs WHERE company_id=? AND source=? AND active=1', (company_id, source)).fetchall()
    prev_ids = {r['ext_id'] for r in prev}
    ids, new_rows = set(), []
    for j in jobs:
        ext = str(j.get('id') or j.get('url'))[:500]
        if not ext or not j.get('title') or ext in ids:
            continue
        ids.add(ext)
        title_level, tech = classify(j['title'], j.get('team', ''))
        if j.get('tech') is not None:
            tech = int(bool(j['tech']))
        region = region_of(j.get('location', ''), j.get('remote'))
        row = db.tl().execute('SELECT id, description FROM jobs WHERE company_id=? AND source=? AND ext_id=?',
                              (company_id, source, ext)).fetchone()
        desc = (j.get('desc') or '').strip() or (row['description'] if row else '') or ''
        level, exp = seniority.level_from(title_level, desc)
        if j.get('level'):  # kaynak seviyeyi kesin biliyor (or. staj / yeni mezun programi)
            level, exp = j['level'], None
        dkind, durl = j.get('detail') or (('page', j.get('url')) if source in ('genel', 'ozel') and j.get('url') else (None, None))
        if row:
            db.write(db.tl(), 'UPDATE jobs SET title=?, location=?, team=?, url=?, posted=COALESCE(?,posted), last_seen=?, active=1, level=?, '
                              'is_tech=?, region=?, description=?, exp_min=?, detail_kind=?, detail_url=? WHERE id=?',
                     (j['title'], j.get('location', ''), j.get('team', ''), j.get('url', ''), j.get('posted'), now, level, tech, region,
                      desc[:6000] or None, exp, dkind, durl, row['id']))
        else:
            cur = db.write(db.tl(), 'INSERT INTO jobs(company_id,source,ext_id,title,location,team,url,posted,first_seen,last_seen,active,'
                                    'level,is_tech,region,description,exp_min,detail_kind,detail_url) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?)',
                           (company_id, source, ext, j['title'], j.get('location', ''), j.get('team', ''), j.get('url', ''),
                            j.get('posted'), now, now, level, tech, region, desc[:6000] or None, exp, dkind, durl))
            new += 1
            new_rows.append((cur.lastrowid, j, region, bool(desc)))
    closed = 0
    if definitive and (ids or len(prev) <= 3 or not guard):  # onceden cok ilan vardi ve simdi 0 geldiyse kaynak bozulmus olabilir
        for r in prev:
            if r['ext_id'] not in ids:
                db.write(db.tl(), 'UPDATE jobs SET active=0 WHERE id=?', (r['id'],))
                closed += 1
    overlap = (len(prev_ids & ids) / len(prev_ids)) if prev_ids else None
    return new, closed, len(prev_ids), overlap, new_rows


def enrich_pending(company_id):
    """Aciklamasi olmayan aktif ilanlar icin detay sayfasini cek: Turkiye/uzaktan/belirtilmemis konumlular,
    firma basina tarama basina en fazla enrich.MAX_PER_COMPANY ilan (siteleri yormamak ve engellenmemek icin).
    Kalanlar sonraki taramalarda tamamlanir."""
    rows = db.tl().execute(
        "SELECT id, title, team, detail_kind, detail_url FROM jobs WHERE company_id=? AND active=1 AND description IS NULL "
        "AND detail_checked IS NULL AND detail_url IS NOT NULL AND region IN ('Türkiye','Uzaktan','Belirtilmemiş') "
        "ORDER BY is_tech DESC, first_seen DESC LIMIT ?", (company_id, enrich.MAX_PER_COMPANY)).fetchall()
    done = 0
    for r in rows:
        desc, posted = enrich.fetch_detail(r['detail_kind'], r['detail_url'])
        if desc:
            title_level, _ = classify(r['title'], r['team'] or '')
            level, exp = seniority.level_from(title_level, desc)
            db.write(db.tl(), 'UPDATE jobs SET description=?, exp_min=?, level=?, posted=COALESCE(posted, ?), detail_checked=1 WHERE id=?',
                     (desc[:6000], exp, level, posted, r['id']))
            done += 1
        else:
            db.write(db.tl(), 'UPDATE jobs SET detail_checked=1 WHERE id=?', (r['id'],))
        enrich.pace()
    return done


def _record_run(c, source, ok, count=0, new=0, closed=0, prev=0, overlap=None, error=None):
    db.write(db.tl(), 'INSERT INTO source_runs(run_at,company_id,source,ok,count,new,closed,prev_active,overlap,error) VALUES(?,?,?,?,?,?,?,?,?,?)',
             (dt.datetime.now().isoformat(timespec='seconds'), c['id'], source, int(ok), count, new, closed, prev, overlap, error))


def health_flags(prev, count, overlap):
    """Kaynak sagligi uyarilari: okuyucu bozulmus ya da ilan kimlikleri kararsiz olabilir."""
    flags = []
    if prev >= 10 and overlap is not None and overlap < 0.4:
        flags.append(f'ilanlarin %{round(100 * (1 - overlap))}i bir anda degisti (okuyucu/kimlik sorunu olabilir)')
    if prev >= 10 and count < prev * 0.4:
        flags.append(f'ilan sayisi {prev} -> {count} dustu')
    return flags


def _finish_company(con, c, status, note, n_jobs):
    db.write(db.tl(), 'UPDATE companies SET status=?, status_note=?, last_scan=?, job_count=? WHERE id=?',
             (status, note[:300], dt.datetime.now().isoformat(timespec='minutes'), n_jobs, c['id']))


def _fetch_known(c):
    """ATS veya firmaya ozel okuyucu: (source, jobs)"""
    if c['ats'] == 'custom':
        return 'ozel', custom.REGISTRY[c['ats_slug']]()
    return c['ats'], atsmod.fetch_jobs(c['ats'], c['ats_slug'], c['ats_extra'])


def scan_known(con, c):
    source = 'ozel' if c['ats'] == 'custom' else c['ats']
    try:
        source, jobs = _fetch_known(c)
        new, closed, prev, overlap, new_rows = upsert(con, c['id'], source, jobs)
        enrich_pending(c['id'])
        active = db.tl().execute('SELECT COUNT(*) FROM jobs WHERE company_id=? AND active=1', (c['id'],)).fetchone()[0]
        note = f'{source}: {len(jobs)} ilan'
        if jobs and c['ats'] != 'custom' and not any(region_of(j.get('location', ''), j.get('remote')) in ('Türkiye', 'Uzaktan', 'Belirtilmemiş')
                                                     for j in jobs):
            note += ' — dikkat: hicbiri Turkiye/uzaktan degil, yanlis eslesme olabilir'
        flags = health_flags(prev, len(jobs), overlap)
        if flags:
            note += ' — SAGLIK: ' + '; '.join(flags)
            _log(f'{c["name"]}: kaynak sagligi uyarisi: {"; ".join(flags)}')
        _record_run(c, source, True, len(jobs), new, closed, prev, overlap)
        _finish_company(con, c, 'ozel' if c['ats'] == 'custom' else 'ats', note, active)
        STATE['new'] += new
        STATE['closed'] += closed
        STATE['ok'] += 1
        if new:
            _log(f'{c["name"]}: {new} yeni ilan ({source})')
    except Exception as e:  # noqa: BLE001
        STATE['failed'] += 1
        _record_run(c, source, False, error=str(e)[:200])
        if c['ats'] != 'custom' and getattr(e, 'status', None) in (403, 404, 410):
            # ATS hesabi kapanmis/tasinmis: genel ayristiriciya dus ve bir sonraki taramada kariyer sayfasini yeniden kesfet
            db.write(db.tl(), "UPDATE companies SET ats='generic', ats_extra=?, checked_at=NULL WHERE id=?", (c['ats'], c['id']))
            _finish_company(con, c, 'hata', f'{c["ats"]}/{c["ats_slug"]} hesabi calismiyor ({e.status}); yeniden kesfedilecek',
                            c['job_count'] or 0)
        else:
            _finish_company(con, c, 'hata', f'{c["ats"]} okunamadi: {str(e)[:150]}', c['job_count'] or 0)
        _log(f'{c["name"]}: HATA {str(e)[:100]}')


def scan_discover(con, c, force=False):
    """Kesif gerekiyorsa yap, sonra ilanlari cek (bu fonksiyon tarayici is parcaciginda calisir)."""
    if is_job_board(c['website']) and c['ats'] in (None, 'generic'):
        for r in db.tl().execute("SELECT id FROM jobs WHERE company_id=? AND source='genel' AND active=1", (c['id'],)).fetchall():
            db.write(db.tl(), 'UPDATE jobs SET active=0, hidden=1 WHERE id=?', (r['id'],))
        _finish_company(con, c, 'ilan-sitesi', 'is ilani sitesi: taranmiyor (Arama kisayollari sekmesini kullan)', 0)
        STATE['ok'] += 1
        return
    try:
        need = force or not c['checked_at'] or c['status'] in (None, 'erisilemedi', 'hata')
        if not need and c['status'] in ('kariyer-yok', 'site-yok', 'yonlendirme'):
            age = (dt.date.today() - dt.date.fromisoformat(c['checked_at'][:10])).days
            need = age >= REDISCOVER_DAYS
        jobs, status, note = None, c['status'], c['status_note'] or ''
        if need:
            r = careers.discover(c)
            db.write(db.tl(), 'UPDATE companies SET career_url=?, ats=?, ats_slug=?, ats_extra=?, status=?, status_note=?, checked_at=? WHERE id=?',
                     (r['career_url'], r['ats'], r['ats_slug'], r['ats_extra'], r['status'], r['status_note'][:300],
                      dt.datetime.now().isoformat(timespec='minutes'), c['id']))
            c = dict(c, career_url=r['career_url'], ats=r['ats'], ats_slug=r['ats_slug'], ats_extra=r['ats_extra'])
            jobs, status, note = r['jobs'], r['status'], r['status_note']
            if atsmod.has_reader(r['ats'], r['ats_extra']):
                try:
                    _fetch_known(c)
                    return scan_known(con, c)
                except Exception as e:  # noqa: BLE001 - sayfadaki ATS hesabi kapanmis/tasinmis olabilir
                    if not (getattr(e, 'status', None) in (403, 404, 410) or 'kayitta' in str(e)):
                        raise
                    old = f"{r['ats']}/{r['ats_slug']}"
                    db.write(db.tl(), "UPDATE companies SET ats='generic', ats_extra=? WHERE id=?", (r['ats'], c['id']))
                    c = dict(c, ats='generic', ats_extra=r['ats'])
                    final, html, links, frames = browser.render(c['career_url'] or c['website'])
                    jobs = generic.extract(final, [tuple(x) for x in links])
                    status = 'genel' if jobs else 'sayfa-var-ilan-yok'
                    note = (f'genel ayristirici: {len(jobs)} ilan' if jobs else 'kariyer sayfasi var, ilan listesi bulunamadi') + \
                        f' (sayfadaki {old} hesabi calismiyor: {getattr(e, "status", e)})'
        elif c['ats'] == 'generic' and c['career_url']:
            final, html, links, frames = browser.render(c['career_url'])
            jobs = generic.extract(final, [tuple(x) for x in links])
            status = 'genel' if jobs else 'sayfa-var-ilan-yok'
            note = f'genel ayristirici: {len(jobs)} ilan' if jobs else 'kariyer sayfasi var, ilan listesi bulunamadi'
        if jobs is not None and (jobs or c['ats'] == 'generic'):
            new, closed, prev, overlap, new_rows = upsert(con, c['id'], 'genel', jobs, definitive=True, guard=False)
            enrich_pending(c['id'])
            _record_run(c, 'genel', True, len(jobs), new, closed, prev, overlap)
            STATE['new'] += new
            STATE['closed'] += closed
            if new:
                _log(f'{c["name"]}: {new} yeni ilan (genel)')
        if jobs is None or (not jobs and c['ats'] != 'generic'):  # ilan kaynagi olmayan basarili kesif (eski hatalari gecersiz kilar)
            _record_run(c, 'kesif', True, 0)
        active = db.tl().execute('SELECT COUNT(*) FROM jobs WHERE company_id=? AND active=1', (c['id'],)).fetchone()[0]
        _finish_company(con, c, status or 'kariyer-yok', note or '', active)
        STATE['ok'] += 1
    except Exception as e:  # noqa: BLE001
        STATE['failed'] += 1
        _record_run(c, 'genel', False, error=str(e)[:200])
        _finish_company(con, c, 'hata', f'kesif/tarama hatasi: {str(e)[:150]}', c['job_count'] or 0)
        _log(f'{c["name"]}: HATA {str(e)[:100]}')


PROGRAM_RECHECK_DAYS = 30
STALL_SECONDS = 600  # kuyruk bittikten sonra bu kadar ilerleme olmazsa takilan is parcacigi beklenmez


def program_jobs(progs):
    """Program sayfalarini ilan satirina cevir. Durum ve son basvuru tarihi 'team' alaninda gorunur."""
    out = []
    for p in progs:
        team = 'Program · ' + p['status'] + (f" · son başvuru {p['deadline']}" if p.get('deadline') else '')
        out.append(dict(id=p['url'], url=p['url'], title=p['title'], team=team, location='Türkiye', desc=p['text'],
                        level='Staj' if p['kind'] == 'Staj' else 'Junior / Yeni mezun', tech=True))
    return out


def scan_programs(con, c, rediscover=False):
    """Genc yetenek / staj / yeni mezun program sayfalari. Bilinen sayfalar yeniden okunur; yoksa ya da istenirse yeniden aranir."""
    known = json.loads(c.get('program_urls') or '[]')
    try:
        if rediscover or not known:
            progs = programs.discover(c)
            urls = [p['url'] for p in progs]
            definitive = True
        else:
            progs = [p for p in (programs.read(u, c) for u in known) if p]
            for p in progs:
                p.pop('links', None)
            urls = known
            definitive = len(progs) == len(known)  # okunamayan sayfa (gecici hata) varsa ilanini kapatma
        db.write(db.tl(), 'UPDATE companies SET program_urls=?, program_checked=? WHERE id=?',
                 (json.dumps(urls, ensure_ascii=False) if urls else None, dt.datetime.now().isoformat(timespec='minutes'), c['id']))
        new, closed, prev, overlap, _ = upsert(con, c['id'], 'program', program_jobs(progs), definitive=definitive, guard=False)
        if progs or prev:
            _record_run(c, 'program', True, len(progs), new, closed, prev, overlap)
        STATE['new'] += new
        STATE['closed'] += closed
        STATE['ok'] += 1
        if new:
            _log(f'{c["name"]}: {new} yeni program sayfasi ({", ".join(p["title"][:40] for p in progs[:3])})')
    except Exception as e:  # noqa: BLE001
        STATE['failed'] += 1
        _record_run(c, 'program', False, error=str(e)[:200])
        _log(f'{c["name"]}: program HATA {str(e)[:100]}')


def _browser_pool(con, rows, workers, force=False, fn=None):
    q = queue.Queue()
    for r in rows:
        q.put(r)

    def worker():
        try:
            while True:
                try:
                    c = q.get_nowait()
                except queue.Empty:
                    return
                STATE['current'] = c['name']
                fn(con, c, force) if fn else scan_discover(con, c, force=force)
                STATE['done'] += 1
        finally:
            browser.close_local()
    ts = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in ts:
        t.start()
    last_done, last_change = STATE['done'], time.monotonic()
    while any(t.is_alive() for t in ts):
        for t in ts:
            t.join(timeout=5)
        if STATE['done'] != last_done:
            last_done, last_change = STATE['done'], time.monotonic()
        elif q.empty() and time.monotonic() - last_change > STALL_SECONDS:
            # kuyruk bitti ama bir is parcacigi bir sayfada asili kaldi: taramayi bitir (is parcaciklari daemon, arkada kalir)
            _log(f'takilan sayfa atlandi ({STATE["current"]}); {sum(t.is_alive() for t in ts)} is parcacigi yanit vermiyor')
            break


def run(mode='hizli', company_id=None):
    if not _run_lock.acquire(blocking=False):
        return False
    con = db.connect()
    started = dt.datetime.now().isoformat(timespec='seconds')
    STATE.update(running=True, mode=mode, phase='hazirlaniyor', total=0, done=0, current='', started=started, finished=None,
                 new=0, closed=0, ok=0, failed=0)
    STATE['log'].clear()
    try:
        db.import_excel(con)
        added = db.sync_excel(con)
        if added:
            _log(f"Excel'den {added} yeni firma eklendi")
        known_sql = "SELECT * FROM companies WHERE merged_into IS NULL AND (ats IN ({}) OR ats='custom')".format(','.join(f"'{a}'" for a in atsmod.READERS))
        if mode == 'site':
            from . import search
            STATE.update(phase='arama API ile web sitesi araniyor')

            def prog(i, n, name):
                STATE.update(done=i, total=n, current=name)
            search.run(progress=prog, log=_log)
            mode = 'yeni'  # bulunan siteleri hemen kesfet ve tara
            STATE.update(done=0, total=0)
        if mode == 'yeni':
            rest = [dict(r) for r in db.tl().execute("SELECT * FROM companies WHERE merged_into IS NULL AND checked_at IS NULL AND (ats IS NULL OR ats='generic')")]
            STATE.update(total=len(rest), phase='yeni eklenen firmalar (kesif + gercek tarayici)')
            _log(f'{len(rest)} yeni firma taraniyor')
            _browser_pool(con, rest, workers=6)
        elif mode == 'program':
            cutoff = (dt.date.today() - dt.timedelta(days=PROGRAM_RECHECK_DAYS)).isoformat()
            rows = [dict(r) for r in db.tl().execute(
                "SELECT * FROM companies WHERE merged_into IS NULL AND (website IS NOT NULL AND website<>'' OR career_url IS NOT NULL) "
                "AND (program_checked IS NULL OR program_checked < ?) ORDER BY "
                "CASE WHEN size LIKE 'Büyük%' THEN 0 WHEN size LIKE 'Orta%' THEN 1 ELSE 2 END, id", (cutoff,))
                if not is_job_board(r['website'])]
            STATE.update(total=len(rows), phase='genç yetenek / staj / yeni mezun program sayfaları aranıyor')
            _log(f'{len(rows)} firmada program sayfasi araniyor (son {PROGRAM_RECHECK_DAYS} gunde bakilanlar atlanir)')
            _browser_pool(con, rows, workers=8, force=True, fn=scan_programs)
        elif mode == 'firma':
            c = dict(db.tl().execute('SELECT * FROM companies WHERE id=?', (company_id,)).fetchone())
            STATE.update(total=1, phase=f'{c["name"]} yeniden kesfediliyor')
            _browser_pool(con, [c], 1, force=True)
        else:
            known = [dict(r) for r in db.tl().execute(known_sql)]
            STATE.update(total=len(known), phase='bilinen kaynaklar (ATS + ozel okuyucular)')
            _log(f'{len(known)} bilinen kaynak taraniyor')

            def one(c):
                STATE['current'] = c['name']
                scan_known(con, c)
                STATE['done'] += 1
            with ThreadPoolExecutor(10) as ex:
                list(ex.map(one, known))
            if mode == 'hizli':
                gen = [dict(r) for r in db.tl().execute("SELECT * FROM companies WHERE merged_into IS NULL AND ats='generic' AND status='genel' AND career_url IS NOT NULL")]
                STATE.update(total=STATE['total'] + len(gen), phase='kariyer sayfasindan ilan veren firmalar')
                _log(f'{len(gen)} kariyer sayfasi yeniden okunuyor')
                _browser_pool(con, gen, workers=4)
                progs = [dict(r) for r in db.tl().execute("SELECT * FROM companies WHERE merged_into IS NULL AND program_urls IS NOT NULL")]
                if progs:
                    STATE.update(total=STATE['total'] + len(progs), phase='bilinen program sayfaları (genç yetenek / staj)')
                    _log(f'{len(progs)} firmanin program sayfasi yeniden okunuyor')
                    _browser_pool(con, progs, workers=4, fn=scan_programs)
            if mode == 'tam':
                rest = [dict(r) for r in db.tl().execute(
                    "SELECT * FROM companies WHERE merged_into IS NULL AND (NOT (ats IN ({}) OR ats='custom') OR ats IS NULL) ORDER BY "
                    "CASE WHEN size LIKE 'Büyük%' THEN 0 WHEN size LIKE 'Orta%' THEN 1 ELSE 2 END, id"
                    .format(','.join(f"'{a}'" for a in atsmod.READERS)))]
                STATE.update(total=STATE['total'] + len(rest), phase='kariyer sayfalari (kesif + gercek tarayici)')
                _log(f'{len(rest)} firmanin kariyer sayfasi taraniyor')
                _browser_pool(con, rest, workers=6)
        _log(f'bitti: {STATE["new"]} yeni, {STATE["closed"]} kapanan ilan, {STATE["failed"]} hata')
    except Exception:  # noqa: BLE001
        _log('BEKLENMEYEN HATA: ' + traceback.format_exc()[-300:])
    finally:
        fin = dt.datetime.now().isoformat(timespec='seconds')
        db.write(db.tl(), 'INSERT INTO scans(started,finished,mode,companies,ok,failed,new_jobs,closed_jobs) VALUES(?,?,?,?,?,?,?,?)',
                 (started, fin, mode, STATE['total'], STATE['ok'], STATE['failed'], STATE['new'], STATE['closed']))
        STATE.update(running=False, finished=fin, phase='bitti', current='')
        _run_lock.release()
    return True


def start(mode='hizli', company_id=None):
    if STATE['running']:
        return False
    threading.Thread(target=run, args=(mode, company_id), daemon=True).start()
    return True

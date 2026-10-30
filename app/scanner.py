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
from . import agg, browser, careers, custom, db, enrich, generic, programs, seniority
from .util import TR_PLACE, HttpError, host_of, log, norm

# Is ilani siteleri: kendi sitelerinde baska sirketlerin ilanlarini yayinliyorlar ve otomatik toplamaya izin vermiyorlar.
# Bu firmalar listede olsa bile kariyer sayfalari taranmaz (Arama kisayollari sekmesinden acilir).
JOB_BOARDS = ('kariyer.net', 'eleman.net', 'secretcv.com', 'youthall.com', 'techcareer.net', 'coderspace.io', 'linkedin.com',
              'indeed.com', 'glassdoor.com', 'yenibiris.com', 'careerjet.com.tr', 'isbul.net', 'anbeankampus.co', 'toptalent.co',
              'kariyerkapisi.cbiko.gov.tr', 'turbin.ai')


def is_job_board(website):
    h = host_of(website or '')
    return any(h == b or h.endswith('.' + b) for b in JOB_BOARDS)

STATE = dict(running=False, stopping=False, mode=None, auto=False, phase='', total=0, done=0, current='', started=None, finished=None,
             new=0, fresh=0, fit=0, closed=0, ok=0, failed=0, log=collections.deque(maxlen=500))
_NEW_IDS = []  # bu taramada eklenen ilanlarin kimlikleri (tarama sonunda "yeni" / "bana uygun" sayimi icin)
_run_lock = threading.Lock()
_stop = threading.Event()


def stop():
    """Calisan taramayi durdurma istegi: mevcut firma bitince is parcaciklari temiz sekilde cikar."""
    if STATE['running']:
        _stop.set()
        STATE['stopping'] = True
        _log('durdurma istegi alindi, mevcut adimlar tamamlaninca tarama duracak...')
        return True
    return False
REDISCOVER_DAYS = 14  # kariyer sayfasi bulunamayan firmalar bu kadar gunde bir yeniden kesfedilir
BURST_MIN, BURST_RATIO = 50, 2  # tek taramada bundan fazla VE onceki aktif sayinin 2 katindan fazla yeni ilan = gercek yeni degil, ilk tam okuma

# ------------------------------------------------------------------ siniflandirma (eleme yok, yalnizca etiket)
JUNIOR = re.compile(r'\bjunior\b|\bjr\b|entry.?level|new.?grad|graduate|yeni mezun|trainee|early career|campus|\bmt\b|'
                    r'management trainee|associate (software|engineer|developer)|uzman yardimcisi|genc yetenek|young talent')
STAJ = re.compile(r'\bintern\b|internship|stajyer|\bstaj(?:i|in|ini|lar|lari)?\b|working student|apprentice|summer internship')  # norm() "ı"yi "i" yapar: Stajı = staji
SENIOR = re.compile(r'\bsenior\b|\bsr\b|\blead\b|principal|\bstaff\b|manager|\bhead\b|director|architect|\bvp\b|chief|expert|'
                    r'kidemli|mudur|yonetici|direktor|\bsef\b|lider')
TECH = re.compile(r'software|yazilim|developer|gelistirici|backend|back-end|frontend|front-end|full.?stack|\bdata\b|\bveri\b|'
                  r'machine learning|\bml\b|\bai\b|yapay zeka|devops|\bsre\b|\bqa\b|\btest\b|testing|mobile|mobil|android|\bios\b|'
                  r'embedded|gomulu|firmware|security|siber|cyber|guvenlik|cloud|bulut|platform|python|\bjava\b|golang|\bgo\b|react|'
                  r'node|\.net|c\+\+|\bit\b|bilgi teknoloj|bilgisayar|computer|network|database|veritaban|game|oyun|unity|unreal|'
                  r'algorithm|algoritma|simulasyon|simulation|arayuz|programmer|programci|quant|engineer|muhendis|analyst|analist|'
                  r'sistem|system|bilisim|dijital|digital')


TR_LOC = TR_PLACE  # util.TR_PLACE: ATS okuyuculari da (Workday konum filtresi) ayni kalibi kullanir
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
    """Arayuzdeki 'Gunluk' sekmesi (bellekte, son 500 satir) ve kalici gunluk dosyasi (data/logs/tarama.log)."""
    STATE['log'].append(f"{dt.datetime.now():%H:%M:%S} {msg}")
    log.info(msg)


def _today():
    return dt.date.today().isoformat()


def upsert(con, company_id, source, jobs, definitive=True, guard=True):
    """Ilanlari ekle/guncelle. definitive=True ise listede olmayan aktif ilanlar kapatilir.
    Dondurur: (yeni, kapanan, onceki_aktif_sayisi, ortusme_orani, yeni_ilan_id_listesi)"""
    now, new = _today(), 0
    prev = db.tl().execute('SELECT id, ext_id FROM jobs WHERE company_id=? AND source=? AND active=1', (company_id, source)).fetchall()
    prev_ids = {r['ext_id'] for r in prev}
    # Kaynagin ilk taramasi: bu ilanlar siteye bugun eklenmedi, ilk kez goruluyor; arayuzde "yeni" sayilmaz (is_baseline=1).
    baseline = int(not db.tl().execute('SELECT 1 FROM jobs WHERE company_id=? AND source=? LIMIT 1', (company_id, source)).fetchone()
                   and not db.tl().execute('SELECT 1 FROM source_runs WHERE company_id=? AND source=? AND ok=1 LIMIT 1',
                                           (company_id, source)).fetchone())
    if not baseline:  # kaynak onceden kismen okunmussa (hata, sayfalama) ilk tam okuma yuzlerce "yeni" ilan getirir: o da ilk taramadir
        known = {r['ext_id'] for r in db.tl().execute('SELECT ext_id FROM jobs WHERE company_id=? AND source=?', (company_id, source))}
        n_new = len({str(j.get('id') or j.get('url'))[:500] for j in jobs if j.get('title')} - known)
        if n_new > max(BURST_MIN, BURST_RATIO * len(prev_ids)):
            baseline = 1
            name = (db.tl().execute('SELECT name FROM companies WHERE id=?', (company_id,)).fetchone() or ['?'])[0]
            _log(f"{name}: {source} kaynagindan {n_new} yeni ilan birden geldi (onceki aktif {len(prev_ids)}): ilk tam okuma sayildi, 'yeni' isaretlenmeyecek")
    hide = int(bool((db.tl().execute('SELECT hide_jobs FROM companies WHERE id=?', (company_id,)).fetchone() or [0])[0]))
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
                                    'level,is_tech,region,description,exp_min,detail_kind,detail_url,is_baseline,hidden) '
                                    'VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)',
                           (company_id, source, ext, j['title'], j.get('location', ''), j.get('team', ''), j.get('url', ''),
                            j.get('posted'), now, now, level, tech, region, desc[:6000] or None, exp, dkind, durl, baseline, hide))
            new += 1
            _NEW_IDS.append(cur.lastrowid)
            if not baseline:
                STATE['fresh'] = STATE.get('fresh', 0) + 1  # tarama surerken kaba sayac; kesin sayi _summarize_new'de
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
    Kalanlar sonraki taramalarda tamamlanir. Liste konum vermediyse ve detay sayfasi veriyorsa (JobPosting) konum/bolge da dolar."""
    rows = db.tl().execute(
        "SELECT id, title, team, location, region, detail_kind, detail_url FROM jobs WHERE company_id=? AND active=1 AND description IS NULL "
        "AND detail_checked IS NULL AND detail_url IS NOT NULL AND region IN ('Türkiye','Uzaktan','Belirtilmemiş') "
        "ORDER BY is_tech DESC, first_seen DESC LIMIT ?", (company_id, enrich.MAX_PER_COMPANY)).fetchall()
    done = 0
    for r in rows:
        desc, posted, loc = enrich.fetch_detail(r['detail_kind'], r['detail_url'])
        if desc:
            title_level, _ = classify(r['title'], r['team'] or '')
            level, exp = seniority.level_from(title_level, desc)
            db.write(db.tl(), 'UPDATE jobs SET description=?, exp_min=?, level=?, posted=COALESCE(posted, ?), detail_checked=1 WHERE id=?',
                     (desc[:6000], exp, level, posted, r['id']))
            if loc and not (r['location'] or '').strip():  # listede konum yoktu, detay sayfasi verdi (uzaktan isaretli ilan uzaktan kalir)
                region = r['region'] if r['region'] == 'Uzaktan' and region_of(loc) != 'Türkiye' else region_of(loc)
                db.write(db.tl(), 'UPDATE jobs SET location=?, region=? WHERE id=?', (loc, region, r['id']))
            done += 1
        else:
            db.write(db.tl(), 'UPDATE jobs SET detail_checked=1 WHERE id=?', (r['id'],))
        enrich.pace()
    return done


def _record_run(c, source, ok, count=0, new=0, closed=0, prev=0, overlap=None, error=None):
    db.write(db.tl(), 'INSERT INTO source_runs(run_at,company_id,source,ok,count,new,closed,prev_active,overlap,error) VALUES(?,?,?,?,?,?,?,?,?,?)',
             (dt.datetime.now().isoformat(timespec='seconds'), c['id'], source, int(ok), count, new, closed, prev, overlap, error))


GENERIC_MIN_PREV = 5  # genel ayristirici listeleri kucuk: saglik kontrolu 5 ilandan baslar (ATS ve ozel okuyucularda 10)


def _min_prev(source):
    return GENERIC_MIN_PREV if source == 'genel' else 10


def _churn(prev, overlap, source=''):
    """Onceki ilanlarin cogu bir anda kayboldu, yerine baskalari geldi: ilan kimlikleri kararsiz (adres degisiyor) ya da sayfa
    her seferinde baska ilanlar gosteriyor (or. 'one cikan ilanlar' listesi)."""
    return prev >= _min_prev(source) and overlap is not None and overlap < 0.4


def health_flags(prev, count, overlap, source=''):
    """Kaynak sagligi uyarilari: okuyucu bozulmus ya da ilan kimlikleri kararsiz olabilir."""
    flags = []
    if _churn(prev, overlap, source):
        flags.append(f'ilanlarin %{round(100 * (1 - overlap))}i bir anda degisti (okuyucu/kimlik sorunu olabilir)')
    if prev >= _min_prev(source) and count < prev * 0.4:
        flags.append(f'ilan sayisi {prev} -> {count} dustu')
    return flags


def _check_health(c, source, prev, count, overlap, new_rows):
    """Saglik uyarilarini loga yazar ve dondurur. Kimlik kaymasinda bu taramada eklenen ilanlar 'yeni' sayilmaz (is_baseline=1):
    gercekten yeni degiller, ayni ya da rastgele ilanlar yeni kimlikle geldi; 'bana uygun' bildirimi de gitmez."""
    flags = health_flags(prev, count, overlap, source)
    if flags:
        _log(f'{c["name"]}: kaynak sagligi uyarisi: {"; ".join(flags)}')
    if new_rows and _churn(prev, overlap, source):
        ids = [r[0] for r in new_rows]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            db.write(db.tl(), f'UPDATE jobs SET is_baseline=1 WHERE id IN ({",".join("?" * len(chunk))})', chunk)
        _log(f'{c["name"]}: kimlik kaymasi: {source} kaynagindan gelen {len(ids)} ilan yeni sayilmadi')
    return flags


def _finish_company(con, c, status, note, n_jobs):
    db.write(db.tl(), 'UPDATE companies SET status=?, status_note=?, last_scan=?, job_count=? WHERE id=?',
             (status, note[:300], dt.datetime.now().isoformat(timespec='minutes'), n_jobs, c['id']))


def _robots_block(con, c, source):
    """robots.txt bu kaynagi okumamiza izin vermiyor: kaynagin acik ilanlari kapanir, firma 'robots' durumuna alinir.
    Hata sayilmaz; her taramada kural yeniden kontrol edilir, site izin verirse okuma kendiliginden baslar."""
    rows = db.tl().execute('SELECT id FROM jobs WHERE company_id=? AND source=? AND active=1', (c['id'], source)).fetchall()
    for r in rows:
        db.write(db.tl(), 'UPDATE jobs SET active=0 WHERE id=?', (r['id'],))
    _record_run(c, source, True, 0, 0, len(rows), len(rows), None, 'robots.txt izin vermiyor')
    active = db.tl().execute('SELECT COUNT(*) FROM jobs WHERE company_id=? AND active=1', (c['id'],)).fetchone()[0]
    _finish_company(con, c, 'robots', f'robots.txt izin vermiyor: {source} kaynagi taranmiyor', active)
    STATE['closed'] += len(rows)
    STATE['ok'] += 1
    if rows:
        _log(f'{c["name"]}: robots.txt izin vermiyor, {source} kaynagindaki {len(rows)} ilan kapatildi')


def tr_only(jobs):
    """Cok uluslu firma kaynagi: yalnizca Turkiye'deki ilanlar. Kaynak ilan dondurduyse liste dogrulanmistir (Turkiye'de ilan
    kalmadiysa eskiler kapanir); kaynak bos donduyse okuyucunun kendi karari gecerli."""
    kept = [j for j in jobs if region_of(j.get('location', ''), j.get('remote')) == 'Türkiye']
    note = getattr(jobs, 'note', '') or (f'Turkiye filtresi: {len(kept)} / {len(jobs)} ilan' if len(kept) != len(jobs) else '')
    return atsmod.Jobs(kept, note=note, confirmed=bool(jobs) or getattr(jobs, 'confirmed', False))


def _fetch_known(c):
    """ATS veya firmaya ozel okuyucu: (source, jobs)"""
    if c['ats'] == 'custom':
        return 'ozel', custom.REGISTRY[c['ats_slug']]()
    jobs = atsmod.fetch_jobs(c['ats'], c['ats_slug'], c['ats_extra'])
    return c['ats'], (tr_only(jobs) if c.get('tr_only') else jobs)


def scan_known(con, c):
    source = 'ozel' if c['ats'] == 'custom' else c['ats']
    try:
        source, jobs = _fetch_known(c)
        # okuyucu bos listeyi dogruladiysa (or. Workday'de Turkiye ilani yok) koruma devre disi: eski ilanlar kapanir
        new, closed, prev, overlap, new_rows = upsert(con, c['id'], source, jobs, guard=not getattr(jobs, 'confirmed', False))
        enrich_pending(c['id'])
        active = db.tl().execute('SELECT COUNT(*) FROM jobs WHERE company_id=? AND active=1', (c['id'],)).fetchone()[0]
        note = f'{source}: {len(jobs)} ilan' + (f' ({jobs.note})' if getattr(jobs, 'note', '') else '')
        if jobs and c['ats'] != 'custom' and not any(region_of(j.get('location', ''), j.get('remote')) in ('Türkiye', 'Uzaktan', 'Belirtilmemiş')
                                                     for j in jobs):
            note += ' — dikkat: hicbiri Turkiye/uzaktan degil, yanlis eslesme olabilir'
        flags = _check_health(c, source, prev, len(jobs), overlap, new_rows)
        if flags:
            note += ' — SAGLIK: ' + '; '.join(flags)
        _record_run(c, source, True, len(jobs), new, closed, prev, overlap)
        _finish_company(con, c, 'ozel' if c['ats'] == 'custom' else 'ats', note, active)
        STATE['new'] += new
        STATE['closed'] += closed
        STATE['ok'] += 1
        if new:
            _log(f'{c["name"]}: {new} yeni ilan ({source})')
    except Exception as e:  # noqa: BLE001
        if getattr(e, 'status', None) == 'robots':
            return _robots_block(con, c, source)
        log.warning('%s: %s okunamadi', c['name'], source, exc_info=True)  # tam iz dosyaya; tarama diger firmalarla surer
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
        if not need and c['status'] in ('kariyer-yok', 'site-yok', 'yonlendirme', 'robots'):
            age = (dt.date.today() - dt.date.fromisoformat(c['checked_at'][:10])).days
            need = age >= REDISCOVER_DAYS
        jobs, status, note = None, c['status'], c['status_note'] or ''
        if need:
            r = careers.discover(c)
            db.write(db.tl(), 'UPDATE companies SET career_url=?, ats=?, ats_slug=?, ats_extra=?, status=?, status_note=?, checked_at=? WHERE id=?',
                     (r['career_url'], r['ats'], r['ats_slug'], r['ats_extra'], r['status'], r['status_note'][:300],
                      dt.datetime.now().isoformat(timespec='minutes'), c['id']))
            c = dict(c, career_url=r['career_url'], ats=r['ats'], ats_slug=r['ats_slug'], ats_extra=r['ats_extra'])
            if r['status'] == 'robots':
                return _robots_block(con, c, 'genel')
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
                    jobs = generic.extract(final, [tuple(x) for x in links], html)
                    status = 'genel' if jobs else 'sayfa-var-ilan-yok'
                    note = (f'genel ayristirici: {len(jobs)} ilan' if jobs else 'kariyer sayfasi var, ilan listesi bulunamadi') + \
                        f' (sayfadaki {old} hesabi calismiyor: {getattr(e, "status", e)})'
        elif c['ats'] == 'generic' and c['career_url']:
            final, html, links, frames = browser.render(c['career_url'])
            jobs = generic.extract(final, [tuple(x) for x in links], html)
            status = 'genel' if jobs else 'sayfa-var-ilan-yok'
            note = f'genel ayristirici: {len(jobs)} ilan' if jobs else 'kariyer sayfasi var, ilan listesi bulunamadi'
        if jobs is not None and (jobs or c['ats'] == 'generic'):
            new, closed, prev, overlap, new_rows = upsert(con, c['id'], 'genel', jobs, definitive=True, guard=False)
            enrich_pending(c['id'])
            flags = _check_health(c, 'genel', prev, len(jobs), overlap, new_rows)
            if flags:
                note = (note or '') + ' — SAGLIK: ' + '; '.join(flags)
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
        if getattr(e, 'status', None) == 'robots':  # kayitli kariyer sayfasi tarayicida acilirken robots.txt engeli
            return _robots_block(con, c, 'genel')
        log.warning('%s: kesif/tarama hatasi', c['name'], exc_info=True)
        STATE['failed'] += 1
        _record_run(c, 'genel', False, error=str(e)[:200])
        _finish_company(con, c, 'hata', f'kesif/tarama hatasi: {str(e)[:150]}', c['job_count'] or 0)
        _log(f'{c["name"]}: HATA {str(e)[:100]}')


AGG_SOURCE = 'workable-tr'
AGG_CATEGORY = 'İş platformundan eklenen'


def _new_company(name, website, city, ats, slug, extra=None, source='platform'):
    cur = db.write(db.tl(), 'INSERT INTO companies(name, category, city, website, website_source, ats, ats_slug, ats_extra, tr_only, checked_at) '
                            'VALUES(?,?,?,?,?,?,?,?,1,?)',
                   (name, AGG_CATEGORY, city or 'Belirtilmemiş', website or None, source if website else None, ats, slug, extra,
                    dt.datetime.now().isoformat(timespec='minutes')))
    return cur.lastrowid


def _city(location):
    first = (location or '').split(',')[0].strip()
    country_only = re.match(r'(turkiye|turkey|tuerkiye)$', norm(first))
    return first if first and TR_PLACE.search(norm(first)) and not country_only else 'Belirtilmemiş'


def _own_source(row):
    """Firmanin ilanlari zaten kendi kaynagindan geliyor mu (ATS / ozel okuyucu / ilan bulan genel ayristirici)?"""
    return row['ats'] not in (None, 'generic', 'agg') or (row['ats'] == 'generic' and row['status'] == 'genel')


def scan_aggregators(con):
    """Workable genel aramasindaki Turkiye ilanlari firmalara dagitilir (kaynak 'workable-tr'). Listede olmayan firma yalnizca
    en az bir teknik ilani varsa eklenir. Kendi kaynagi olan firmanin ilanlari zaten oradan geldigi icin alinmaz (cift kayit)."""
    STATE.update(phase='iş platformu araması (Workable, Türkiye)')
    try:
        jobs = agg.workable_turkey()
    except Exception as e:  # noqa: BLE001
        log.warning('workable aramasi okunamadi', exc_info=True)
        _log(f'Workable aramasi okunamadi: {str(e)[:100]}')
        return
    if not jobs:  # arama bozulmus olabilir: hicbir firmanin ilani kapatilmaz
        _log('Workable aramasi bos dondu; firmalara dokunulmadi')
        return
    groups = collections.OrderedDict()
    for j in jobs:
        groups.setdefault(j['company']['key'], []).append(j)
    index = agg.company_index(db.tl())
    used, added = set(), 0
    for js in groups.values():
        if _stop.is_set():
            return
        co = js[0]['company']
        row = agg.match(co, index)
        if row is not None:
            if _own_source(row):
                continue
            cid = row['id']
            if row['ats'] != 'agg':
                db.write(db.tl(), "UPDATE companies SET ats='agg', ats_slug=?, tr_only=1 WHERE id=?", (AGG_SOURCE, cid))
        else:
            if not co['name'] or not any(agg.is_software(j['title']) for j in js):
                continue
            cid = _new_company(co['name'], co['website'], _city(js[0]['location']), 'agg', AGG_SOURCE, source='workable')
            added += 1
            index[1][agg._key(co['name'])] = dict(id=cid, ats='agg', status=None)
        used.add(cid)
        c = dict(db.tl().execute('SELECT * FROM companies WHERE id=?', (cid,)).fetchone())
        items = [{k: v for k, v in j.items() if k != 'company'} for j in js]
        new, closed, prev, overlap, new_rows = upsert(con, cid, AGG_SOURCE, items, guard=False)
        _check_health(c, AGG_SOURCE, prev, len(items), overlap, new_rows)
        _record_run(c, AGG_SOURCE, True, len(items), new, closed, prev, overlap)
        active = db.tl().execute('SELECT COUNT(*) FROM jobs WHERE company_id=? AND active=1', (cid,)).fetchone()[0]
        _finish_company(con, c, 'ats', f'Workable aramasi (Turkiye): {len(items)} ilan', active)
        STATE['new'] += new
        STATE['closed'] += closed
        if new:
            _log(f'{c["name"]}: {new} yeni ilan (Workable aramasi)')
    for r in db.tl().execute("SELECT * FROM companies WHERE ats='agg' AND ats_slug=?", (AGG_SOURCE,)).fetchall():
        if r['id'] not in used:  # firmanin Turkiye ilani kalmadi
            _, closed, prev, overlap, _ = upsert(con, r['id'], AGG_SOURCE, [], guard=False)
            _record_run(dict(r), AGG_SOURCE, True, 0, 0, closed, prev, overlap)
            _finish_company(con, dict(r), 'ats', "Workable aramasi: Turkiye'de ilani yok", 0)
            STATE['closed'] += closed
    _log(f'Workable aramasi: {len(jobs)} Turkiye ilani, {len(used)} firma' + (f', {added} yeni firma eklendi' if added else ''))


SR_DISCOVER_DAYS = 7


def discover_smartrecruiters(con, force=False):
    """SmartRecruiters genel aramasinda Turkiye'de ilani gorunen, listede olmayan firmalari SmartRecruiters hesabiyla ekle
    (yalnizca Turkiye ilanlari; en az bir teknik ilan). Haftada bir calisir ('tam' taramada her zaman); ilanlari normal okuyucu okur."""
    from . import search
    last = search.load_config().get('sr_discovered_at')
    if not force and last and (dt.date.today() - dt.date.fromisoformat(last[:10])).days < SR_DISCOVER_DAYS:
        return
    STATE.update(phase='iş platformu keşfi (SmartRecruiters, Türkiye)')
    try:
        found = agg.smartrecruiters_companies()
    except Exception as e:  # noqa: BLE001
        log.warning('smartrecruiters aramasi okunamadi', exc_info=True)
        _log(f'SmartRecruiters aramasi okunamadi: {str(e)[:100]}')
        return
    have = {(r[0] or '').lower() for r in db.tl().execute("SELECT ats_slug FROM companies WHERE ats='smartrecruiters'")}
    index = agg.company_index(db.tl())
    added = 0
    for ident, name in found.items():
        if _stop.is_set():
            return
        if ident.lower() in have:
            continue
        try:
            jobs = atsmod.smartrecruiters(ident, 'tr')
        except Exception:  # noqa: BLE001 - hesap kapali / gecici hata: sonraki kesifte yeniden denenir
            continue
        if not any(agg.is_software(j['title']) for j in jobs):
            continue
        row = agg.match({'name': name}, index)
        if row is not None:
            if not _own_source(row):
                db.write(db.tl(), "UPDATE companies SET ats='smartrecruiters', ats_slug=?, ats_extra='tr', tr_only=1 WHERE id=?",
                         (ident, row['id']))
                added += 1
            continue
        _new_company(name, None, _city(jobs[0]['location'] if jobs else ''), 'smartrecruiters', ident, 'tr')
        added += 1
        _log(f'SmartRecruiters: {name} eklendi ({len(jobs)} Turkiye ilani)')
    cfg = search.load_config()
    cfg['sr_discovered_at'] = dt.datetime.now().isoformat(timespec='minutes')
    search.save_config(cfg)
    _log(f'SmartRecruiters kesfi: {len(found)} firma goruldu, {added} firma eklendi/baglandi')


PROGRAM_RECHECK_DAYS = 30
STALL_SECONDS = 600  # kuyruk bittikten sonra bu kadar ilerleme olmazsa takilan is parcacigi beklenmez


def program_jobs(progs):
    """Program sayfalarini ilan satirina cevir. Durum ve son basvuru tarihi 'team' alaninda gorunur.
    Konum sayfadan cikarilir (programs._location); cok uluslu sirketlerin genel sayfalari 'Turkiye' sayilmaz."""
    out = []
    for p in progs:
        team = 'Program · ' + p['status'] + (f" · son başvuru {p['deadline']}" if p.get('deadline') else '')
        out.append(dict(id=p['url'], url=p['url'], title=p['title'], team=team, location=p.get('location', ''), desc=p['text'],
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
            progs, blocked, failed = [], [], 0
            for u in known:
                try:
                    p = programs.read(u, c)
                except HttpError as e:  # robots.txt izin vermiyor: sayfa listeden cikar, ilani asagida kapanir
                    if e.status != 'robots':
                        raise
                    blocked.append(u)
                    continue
                if p:
                    p.pop('links', None)
                    progs.append(p)
                else:
                    failed += 1
            urls = [u for u in known if u not in blocked]
            definitive = not failed  # okunamayan sayfa (gecici hata) varsa ilanini kapatma
            for u in blocked:
                db.write(db.tl(), "UPDATE jobs SET active=0 WHERE company_id=? AND source='program' AND ext_id=? AND active=1", (c['id'], u))
                _log(f'{c["name"]}: robots.txt izin vermiyor, program sayfasi kapatildi: {u}')
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
        log.warning('%s: program sayfasi hatasi', c['name'], exc_info=True)
        STATE['failed'] += 1
        _record_run(c, 'program', False, error=str(e)[:200])
        _log(f'{c["name"]}: program HATA {str(e)[:100]}')


def _browser_pool(con, rows, workers, force=False, fn=None):
    q = queue.Queue()
    for r in rows:
        q.put(r)

    def worker():
        try:
            while not _stop.is_set():
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


def _summarize_new():
    """Bu taramada eklenen ilanlardan 'yeni' sayilanlar (db.RECENT) ve bunlardan 'bana uygun' olanlar (db.FIT).
    Dondurur: (yeni_sayisi, [bana uygun satirlari: id, title, company]). Seviye/bolge aciklama cekildikten sonra kesinlesir."""
    ids, cut = list(_NEW_IDS), db.cutoff(db.NEW_DAYS)
    fresh, fit = 0, []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        rows = db.tl().execute(
            f'SELECT j.id, j.title, c.name AS company, {db.FIT} AS fit FROM jobs j JOIN companies c ON c.id=j.company_id '
            f'WHERE j.id IN ({",".join("?" * len(chunk))}) AND j.active=1 AND j.hidden=0 AND {db.RECENT}', [*chunk, cut, cut]).fetchall()
        fresh += len(rows)
        fit += [dict(r) for r in rows if r['fit']]
    return fresh, fit


def _notify_fit(fit):
    """Otomatik tarama 'bana uygun' yeni ilan buldu: masaustu bildirimi (arka planda; ayar kapaliysa gonderilmez)."""
    from . import auto, notify
    if not fit or not auto.settings()['notify']:
        return
    lines = [f"{r['company']} — {r['title']}"[:90] for r in fit[:3]] + ([f'+{len(fit) - 3} ilan daha'] if len(fit) > 3 else [])
    threading.Thread(target=notify.toast, args=(f'{len(fit)} yeni ilan sana uygun', lines, notify.BASE_URL + '#fit'), daemon=True).start()


def run(mode='hizli', company_id=None, auto=False):
    if not _run_lock.acquire(blocking=False):
        return False
    con = db.connect()
    started = dt.datetime.now().isoformat(timespec='seconds')
    _stop.clear()
    STATE.update(running=True, stopping=False, mode=mode, auto=auto, phase='hazirlaniyor', total=0, done=0, current='', started=started, finished=None,
                 new=0, fresh=0, fit=0, closed=0, ok=0, failed=0)
    STATE['log'].clear()
    _NEW_IDS.clear()
    _log(f'tarama basladi: {mode}' + (' (otomatik)' if auto else ''))
    try:
        db.import_excel(con)
        added = db.sync_excel(con)
        if added:
            _log(f"Excel'den {added} yeni firma eklendi")
        s_add, s_link = db.sync_seeds(con)
        if s_add or s_link:
            _log(f'firmalar_global.json: {s_add} yeni firma eklendi, {s_link} firmaya ATS hesabi baglandi')
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
        elif mode == 'hatali':
            err_rows = [dict(r) for r in db.tl().execute(
                "SELECT * FROM companies WHERE merged_into IS NULL AND COALESCE(ats, '')!='agg' AND (status='hata' OR id IN ("
                "SELECT company_id FROM (SELECT company_id, ok, ROW_NUMBER() OVER (PARTITION BY company_id ORDER BY id DESC) AS n FROM source_runs) WHERE n=1 AND ok=0))")]
            STATE.update(total=len(err_rows), phase='sorunlu / hata veren kaynaklar yeniden taranıyor')
            _log(f'{len(err_rows)} sorunlu kaynak yeniden taraniyor')
            _browser_pool(con, err_rows, workers=4, force=True)
        else:
            if mode in ('hizli', 'tam') and not _stop.is_set():
                discover_smartrecruiters(con, force=mode == 'tam')  # yeni firmalar bilinen kaynaklarla birlikte okunsun
            known = [dict(r) for r in db.tl().execute(known_sql)]
            STATE.update(total=len(known), phase='bilinen kaynaklar (ATS + ozel okuyucular)')
            _log(f'{len(known)} bilinen kaynak taraniyor')

            def one(c):
                if _stop.is_set():
                    return
                STATE['current'] = c['name']
                scan_known(con, c)
                STATE['done'] += 1
            with ThreadPoolExecutor(10) as ex:
                list(ex.map(one, known))
            if not _stop.is_set():
                scan_aggregators(con)
            if mode == 'hizli' and not _stop.is_set():
                gen = [dict(r) for r in db.tl().execute("SELECT * FROM companies WHERE merged_into IS NULL AND ats='generic' AND status='genel' AND career_url IS NOT NULL")]
                STATE.update(total=STATE['total'] + len(gen), phase='kariyer sayfasindan ilan veren firmalar')
                _log(f'{len(gen)} kariyer sayfasi yeniden okunuyor')
                _browser_pool(con, gen, workers=4)
                progs = [dict(r) for r in db.tl().execute("SELECT * FROM companies WHERE merged_into IS NULL AND program_urls IS NOT NULL")]
                if progs and not _stop.is_set():
                    STATE.update(total=STATE['total'] + len(progs), phase='bilinen program sayfaları (genç yetenek / staj)')
                    _log(f'{len(progs)} firmanin program sayfasi yeniden okunuyor')
                    _browser_pool(con, progs, workers=4, fn=scan_programs)
            if mode == 'tam' and not _stop.is_set():
                rest = [dict(r) for r in db.tl().execute(
                    "SELECT * FROM companies WHERE merged_into IS NULL AND (NOT (ats IN ({}) OR ats IN ('custom', 'agg')) OR ats IS NULL) ORDER BY "
                    "CASE WHEN size LIKE 'Büyük%' THEN 0 WHEN size LIKE 'Orta%' THEN 1 ELSE 2 END, id"
                    .format(','.join(f"'{a}'" for a in atsmod.READERS)))]
                STATE.update(total=STATE['total'] + len(rest), phase='kariyer sayfalari (kesif + gercek tarayici)')
                _log(f'{len(rest)} firmanin kariyer sayfasi taraniyor')
                _browser_pool(con, rest, workers=6)
        _log(('durduruldu' if _stop.is_set() else 'bitti') + f': {STATE["new"]} yeni, {STATE["closed"]} kapanan ilan, {STATE["failed"]} hata')
    except Exception:  # noqa: BLE001
        _log('BEKLENMEYEN HATA: ' + traceback.format_exc()[-300:])
        log.error('beklenmeyen tarama hatasi', exc_info=True)
    finally:
        try:
            fresh, fit = _summarize_new()
            STATE.update(fresh=fresh, fit=len(fit))
            if auto:
                _notify_fit(fit)
        except Exception:  # noqa: BLE001 - ozet/bildirim hatasi taramayi bozmasin
            _log('OZET HATASI: ' + traceback.format_exc()[-200:])
            log.error('ozet/bildirim hatasi', exc_info=True)
        fin = dt.datetime.now().isoformat(timespec='seconds')
        db.write(db.tl(), 'INSERT INTO scans(started,finished,mode,companies,ok,failed,new_jobs,closed_jobs) VALUES(?,?,?,?,?,?,?,?)',
                 (started, fin, mode, STATE['total'], STATE['ok'], STATE['failed'], STATE['new'], STATE['closed']))
        STATE.update(running=False, stopping=False, finished=fin, phase='durduruldu' if _stop.is_set() else 'bitti', current='')
        _run_lock.release()
    return True


def start(mode='hizli', company_id=None, auto=False):
    if STATE['running']:
        return False
    threading.Thread(target=run, args=(mode, company_id, auto), daemon=True).start()
    return True

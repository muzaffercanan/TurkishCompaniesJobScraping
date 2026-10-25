"""Turkce harfe duyarsiz arama, 'yeni ilan' (ilk tarama haric) ve 'goruldu' kurallari: internet gerekmez, gercek veritabanina dokunmaz."""
import datetime as dt
import os
import sqlite3
import threading
import unittest

from app import db, scanner
from tests.tempdb import TempDb


class Fold(unittest.TestCase):
    def test_turkish_and_case(self):
        for raw, want in (('İzmir', 'izmir'), ('IZMIR', 'izmir'), ('yazılım', 'yazilim'), ('Şirket', 'sirket'), ('ÇELİK', 'celik'),
                          ('Işık', 'isik'), ('Zürich', 'zurich'), ('Ankara', 'ankara'), ('', ''), (None, '')):
            self.assertEqual(db.fold(raw), want, raw)


class Search(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.create_function('trn', 1, db.fold, deterministic=True)
        self.con.execute('CREATE TABLE j(id INTEGER, title TEXT, location TEXT, team TEXT)')
        self.con.executemany('INSERT INTO j VALUES(?,?,?,?)', [
            (1, 'Backend Geliştirici', 'İstanbul, Türkiye', 'Yazılım'), (2, 'Frontend Developer', 'Ankara', None),
            (3, 'Yazılım Mühendisi', 'İzmir', 'Ürün'), (4, 'Q% Analyst', 'Remote', ''), (5, 'Şef Aşçı', 'Bursa', None)])

    def ids(self, q):
        cl, ar = db.search_clauses(q, ['title', 'location', 'team'])
        sql = 'SELECT id FROM j' + (' WHERE ' + ' AND '.join(cl) if cl else '') + ' ORDER BY id'
        return [r[0] for r in self.con.execute(sql, ar)]

    def test_turkish_letters_either_way(self):
        self.assertEqual(self.ids('istanbul'), [1])
        self.assertEqual(self.ids('İSTANBUL'), [1])
        self.assertEqual(self.ids('yazilim'), [1, 3])
        self.assertEqual(self.ids('yazılım'), [1, 3])
        self.assertEqual(self.ids('izmir'), [3])
        self.assertEqual(self.ids('sef asci'), [5])

    def test_words_are_anded_across_columns(self):
        self.assertEqual(self.ids('backend istanbul'), [1])      # baslik + konum
        self.assertEqual(self.ids('istanbul backend'), [1])      # sira onemsiz
        self.assertEqual(self.ids('backend ankara'), [])

    def test_wildcards_are_literal(self):
        self.assertEqual(self.ids('q%'), [4])
        self.assertEqual(self.ids('%'), [4])
        self.assertEqual(self.ids('_'), [])

    def test_empty_query_matches_all(self):
        self.assertEqual(self.ids('   '), [1, 2, 3, 4, 5])


def day(offset):
    return (dt.date.today() - dt.timedelta(days=offset)).isoformat()


class Recent(TempDb):
    def add(self, jid, first_seen, baseline, posted=None):
        self.con.execute("INSERT INTO jobs(id, company_id, source, ext_id, title, first_seen, is_baseline, posted, active) "
                         "VALUES(?,1,'lever',?,?,?,?,?,1)", (jid, str(jid), f'job{jid}', first_seen, baseline, posted))
        self.con.commit()

    def fresh(self, days=db.NEW_DAYS):
        cut = db.cutoff(days)
        return sorted(r[0] for r in self.con.execute(f'SELECT j.id FROM jobs j WHERE {db.RECENT}', (cut, cut)))

    def test_rules(self):
        self.add(1, day(0), 1)                        # ilk taramada bulundu, bugun: yeni DEGIL
        self.add(2, day(0), 0)                        # sonraki taramada bulundu, bugun: yeni
        self.add(3, day(2), 0)                        # 2 gun once: pencerede
        self.add(4, day(10), 0)                       # pencere disinda
        self.add(5, day(10), 1, posted=day(1))        # ilk taramada ama dun yayinlanmis: yeni
        self.add(6, day(0), 1, posted=day(40))        # eski ilan, bugun ilk kez goruldu: yeni degil
        self.add(7, day(0), 1, posted='3 days ago')   # bicimi bozuk yayin tarihi yok sayilir: yeni degil
        self.assertEqual(self.fresh(), [2, 3, 5])
        self.assertEqual(self.fresh(0), [2])          # "bugun": yalniz 2 (5'in yayini dun)
        self.assertEqual(self.fresh(30), [2, 3, 4, 5])


class Baseline(TempDb):
    def run_ok(self, source):
        scanner._record_run({'id': 1}, source, True, 1)

    def jobs(self, source):
        return {r['ext_id']: r['is_baseline'] for r in self.con.execute('SELECT ext_id, is_baseline FROM jobs WHERE source=?', (source,))}

    def j(self, ext):
        return dict(id=ext, title=f'Engineer {ext}', url=f'https://x/{ext}', location='Istanbul, Turkey')

    def test_first_scan_is_baseline_then_new(self):
        before = scanner.STATE.get('fresh', 0)
        scanner.upsert(self.con, 1, 'lever', [self.j('a'), self.j('b')])
        self.run_ok('lever')
        self.assertEqual(self.jobs('lever'), {'a': 1, 'b': 1})
        self.assertEqual(scanner.STATE.get('fresh', 0), before)           # ilk tarama "yeni" sayilmaz
        scanner.upsert(self.con, 1, 'lever', [self.j('a'), self.j('b'), self.j('c')])
        self.assertEqual(self.jobs('lever'), {'a': 1, 'b': 1, 'c': 0})
        self.assertEqual(scanner.STATE.get('fresh', 0), before + 1)

    def test_empty_first_run_then_job_is_new(self):
        self.run_ok('lever')                                              # basarili ama ilansiz tarama
        scanner.upsert(self.con, 1, 'lever', [self.j('a')])
        self.assertEqual(self.jobs('lever'), {'a': 0})

    def test_partial_history_then_full_read_is_baseline(self):
        # Accenture ornegi: kaynak daha once hatayla kismen okunmus (3 ilan), sonra ilk kez tam okunuyor (80 yeni)
        scanner.upsert(self.con, 1, 'workday', [self.j(f'old{i}') for i in range(3)])      # kismi ilk okuma (baseline)
        before = scanner.STATE.get('fresh', 0)
        scanner.upsert(self.con, 1, 'workday', [self.j(f'old{i}') for i in range(3)] + [self.j(f'n{i}') for i in range(80)])
        self.assertEqual({v for k, v in self.jobs('workday').items() if k.startswith('n')}, {1})
        self.assertEqual(scanner.STATE.get('fresh', 0), before)

    def test_normal_growth_stays_new(self):
        scanner.upsert(self.con, 1, 'workday', [self.j(f'old{i}') for i in range(40)])
        before = scanner.STATE.get('fresh', 0)
        scanner.upsert(self.con, 1, 'workday', [self.j(f'old{i}') for i in range(40)] + [self.j(f'n{i}') for i in range(12)])   # 12 < 50: gercek yeni
        self.assertEqual({v for k, v in self.jobs('workday').items() if k.startswith('n')}, {0})
        self.assertEqual(scanner.STATE.get('fresh', 0), before + 12)
        # 52 aktif ilanlik firmada 60 yeni ilan: esik max(50, 2*52=104) > 60 oldugu icin gercek yeni sayilir
        scanner.upsert(self.con, 1, 'workday', [self.j(f'old{i}') for i in range(40)] + [self.j(f'n{i}') for i in range(12)] + [self.j(f'm{i}') for i in range(60)])
        self.assertEqual({v for k, v in self.jobs('workday').items() if k.startswith('m')}, {0})
        # ayni firmada bir seferde 300 yeni ilan: esik max(50, 2*112=224) asildi -> yigin (ilk tam okuma), "yeni" degil
        scanner.upsert(self.con, 1, 'workday', [self.j(k) for k in self.jobs('workday')] + [self.j(f'z{i}') for i in range(300)])
        self.assertEqual({v for k, v in self.jobs('workday').items() if k.startswith('z')}, {1})

    def test_new_source_has_its_own_baseline(self):
        scanner.upsert(self.con, 1, 'lever', [self.j('a')])
        self.run_ok('lever')
        scanner.upsert(self.con, 1, 'genel', [self.j('g1'), self.j('g2')])  # kaynak degisti: yeni sayfa, hepsi ilk gorulme
        self.assertEqual(self.jobs('genel'), {'g1': 1, 'g2': 1})


class Migration(TempDb):
    def test_new_columns_and_backfill(self):
        # eski bir veritabani: yeni sutunlar yok, bir basarili tarama gecmisi var
        self.con.close()
        db._tls = threading.local()
        os.remove(db.DB_PATH)
        old = sqlite3.connect(db.DB_PATH)
        old.executescript("""
            CREATE TABLE companies(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE jobs(id INTEGER PRIMARY KEY, company_id INTEGER, source TEXT, ext_id TEXT, title TEXT, first_seen TEXT,
                              active INTEGER DEFAULT 1, applied INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0);
            CREATE TABLE source_runs(id INTEGER PRIMARY KEY, run_at TEXT, company_id INTEGER, source TEXT, ok INTEGER);
            INSERT INTO companies VALUES(1, 'Firma');
            INSERT INTO source_runs(run_at, company_id, source, ok) VALUES('2026-10-10T09:00:00', 1, 'lever', 1);
            INSERT INTO jobs(id, company_id, source, ext_id, title, first_seen, applied) VALUES(1, 1, 'lever', 'a', 'old', '2026-10-10', 0);
            INSERT INTO jobs(id, company_id, source, ext_id, title, first_seen, applied) VALUES(2, 1, 'lever', 'b', 'later', '2026-10-12', 1);
            INSERT INTO jobs(id, company_id, source, ext_id, title, first_seen, applied) VALUES(3, 1, 'genel', 'c', 'nosrc', '2026-10-12', 0);
        """)
        old.commit()
        old.close()
        con = db.tl()
        got = {r['id']: (r['is_baseline'], r['seen']) for r in con.execute('SELECT id, is_baseline, seen FROM jobs')}
        # 1: ilk taramanin ayni gunu -> baseline; 2: sonraki gun bulundu -> yeni (+ basvurulmus -> gorulmus);
        # 3: bu kaynak icin hic basarili tarama kaydi yok -> kanit yok, baseline sayilir
        self.assertEqual(got, {1: (1, 0), 2: (0, 1), 3: (1, 0)})


if __name__ == '__main__':
    unittest.main()

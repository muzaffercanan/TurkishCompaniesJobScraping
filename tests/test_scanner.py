"""Tarama cekirdegi: baslik/konum siniflandirma, aciklamadan seviye, upsert (ekle / guncelle / kapat / koruma), kaynak sagligi,
detay zenginlestirme ve scan_known hata dallari. Internet yok, gercek veritabanina dokunulmaz."""
import unittest
from unittest import mock

from app import ats as atsmod
from app import db, enrich, scanner, seniority
from app.util import HttpError
from tests.tempdb import TempDb


class Classify(unittest.TestCase):
    def level(self, title, team=''):
        return scanner.classify(title, team)[0]

    def tech(self, title, team=''):
        return scanner.classify(title, team)[1]

    def test_junior_titles(self):
        for t in ('Junior Backend Developer', 'Jr. Frontend Engineer', 'New Grad Software Engineer', 'Yeni Mezun Yazılım Geliştirici',
                  'Management Trainee', 'Associate Software Engineer', 'Entry-Level QA', 'Genç Yetenek Programı'):
            self.assertEqual(self.level(t), 'Junior / Yeni mezun', t)

    def test_intern_titles(self):
        for t in ('Software Engineering Intern', 'Yazılım Stajyeri', 'Staj Programı 2026', 'Working Student Data', 'Summer Internship'):
            self.assertEqual(self.level(t), 'Staj', t)

    def test_staj_suffixes(self):
        # norm() "ı"yi "i"ye cevirir: "Yaz Stajı" -> "yaz staji"
        for t in ('Yaz Stajı 2026', 'Uzun Dönem Stajın Başvurusu', 'Stajını Bizimle Yap', 'Yaz Stajları', 'Mühendislik Stajlar', 'YAZ STAJI'):
            self.assertEqual(self.level(t), 'Staj', t)

    def test_staj_suffix_does_not_overmatch(self):
        for t in ('Stajerlik Danışmanı', 'Stajkur Uzmanı', 'Backend Developer'):
            self.assertEqual(self.level(t), 'Belirtilmemiş', t)

    def test_senior_titles(self):
        for t in ('Senior Data Engineer', 'Sr. Java Developer', 'Tech Lead', 'Principal Engineer', 'Staff Engineer',
                  'Engineering Manager', 'Head of Platform', 'Yazılım Mimarı Architect', 'Kıdemli Yazılım Geliştirici', 'Takım Lideri',
                  'VP of Engineering', 'Müdür Yardımcısı'):
            self.assertEqual(self.level(t), 'Kıdemli+', t)

    def test_unspecified_title(self):
        self.assertEqual(self.level('Backend Developer'), 'Belirtilmemiş')
        self.assertEqual(self.level(''), 'Belirtilmemiş')

    def test_precedence_junior_beats_staj_beats_senior(self):
        # sirasi: junior > staj > senior (ilk eslesen kazanir)
        self.assertEqual(self.level('Junior Software Engineer Intern'), 'Junior / Yeni mezun')
        self.assertEqual(self.level('Senior Intern Mentor'), 'Staj')

    def test_word_boundaries(self):
        # "internal" intern degildir, "leader" lead degil ama "lider" kendi basina senior sayilir; "lead" kelime siniriyla eslesir
        self.assertEqual(self.level('Internal Tools Developer'), 'Belirtilmemiş')
        self.assertEqual(self.level('Misleading Title'), 'Belirtilmemiş')
        self.assertEqual(self.level('Team Lead'), 'Kıdemli+')

    def test_turkish_characters_are_folded(self):
        self.assertEqual(self.level('KIDEMLİ YAZILIM MÜHENDİSİ'), 'Kıdemli+')
        self.assertEqual(self.level('Stajyer Mühendis'), 'Staj')

    def test_tech_detection(self):
        for t in ('Backend Developer', 'Yazılım Mühendisi', 'Data Scientist', 'DevOps Engineer', 'Mobil Uygulama Geliştirici',
                  'Siber Güvenlik Uzmanı', 'Unity Game Programmer', 'Firmware Engineer', 'C++ Developer', 'Yapay Zeka Araştırmacısı'):
            self.assertEqual(self.tech(t), 1, t)

    def test_non_tech_titles(self):
        for t in ('Muhasebe Uzmanı', 'Satış Temsilcisi', 'Insan Kaynakları Asistanı', 'Hukuk Müşaviri'):
            self.assertEqual(self.tech(t), 0, t)

    def test_team_makes_title_technical(self):
        self.assertEqual(self.tech('Specialist'), 0)
        self.assertEqual(self.tech('Specialist', 'Platform Engineering'), 1)
        self.assertEqual(self.tech('Specialist', None), 0)   # takim alani bos olabilir


class Region(unittest.TestCase):
    def test_turkey(self):
        for loc in ('İstanbul, Türkiye', 'Ankara', 'Maslak, Sarıyer', 'Izmir, Turkey', 'Gebze/Kocaeli', 'ODTÜ Teknokent', 'TURKEY'):
            self.assertEqual(scanner.region_of(loc), 'Türkiye', loc)

    def test_remote(self):
        self.assertEqual(scanner.region_of('Remote'), 'Uzaktan')
        self.assertEqual(scanner.region_of('Uzaktan / Hibrit'), 'Uzaktan')
        self.assertEqual(scanner.region_of('Anywhere'), 'Uzaktan')
        self.assertEqual(scanner.region_of('Remote Roles - EMEA'), 'Uzaktan')
        self.assertEqual(scanner.region_of('', remote=True), 'Uzaktan')
        self.assertEqual(scanner.region_of('Berlin', remote=True), 'Yurt dışı')
        self.assertEqual(scanner.region_of('Taiwan (Remote)'), 'Yurt dışı')
        self.assertEqual(scanner.region_of('Remote - USA'), 'Yurt dışı')
        self.assertEqual(scanner.region_of('Remote Roles - APAC'), 'Yurt dışı')

    def test_turkey_wins_over_remote(self):
        self.assertEqual(scanner.region_of('Remote - Istanbul'), 'Türkiye')
        self.assertEqual(scanner.region_of('Istanbul', remote=True), 'Türkiye')

    def test_abroad(self):
        for loc in ('London, UK', 'Berlin, Germany', 'San Francisco, CA'):
            self.assertEqual(scanner.region_of(loc), 'Yurt dışı', loc)

    def test_unspecified(self):
        for loc in ('', None, '   ', ' , - '):
            self.assertEqual(scanner.region_of(loc), 'Belirtilmemiş', repr(loc))


class Experience(unittest.TestCase):
    def exp(self, text):
        return seniority.experience(text)[0]

    def test_year_patterns(self):
        cases = {'En az 3 yıl deneyim': 3, 'minimum 5 years of experience': 5, '2-4 yıl tecrübe': 2, '3 to 5 years': 3,
                 '5+ years experience': 5, 'Deneyim: en az 2 yıl': 2, '4 yıllık deneyim': 4}
        for text, want in cases.items():
            self.assertEqual(self.exp(text), want, text)

    def test_lowest_value_wins(self):
        self.assertEqual(self.exp('en az 5 yıl Java, en az 2 yıl SQL deneyimi'), 2)

    def test_out_of_range_ignored(self):
        self.assertIsNone(self.exp('Firma 25 yıldır sektörde, 2000+ çalışan'))

    def test_no_text(self):
        self.assertEqual(seniority.experience(''), (None, False))
        self.assertEqual(seniority.experience(None), (None, False))

    def test_newgrad_phrases(self):
        for text in ('Yeni mezun adaylar başvurabilir', 'Fresh graduates welcome', 'Deneyim şartı aranmamaktadır',
                     'Tecrübe şartı aranmamaktadır', 'Open to recent graduates', '2025 yılında mezun olmuş'):
            self.assertTrue(seniority.experience(text)[1], text)

    def test_junior_word_in_senior_posting_is_not_newgrad(self):
        self.assertFalse(seniority.experience('You will mentor junior engineers')[1])


class LevelFrom(unittest.TestCase):
    def test_title_level_is_never_overridden(self):
        self.assertEqual(seniority.level_from('Kıdemli+', 'yeni mezun adaylar'), ('Kıdemli+', None))
        self.assertEqual(seniority.level_from('Staj', 'en az 5 yıl deneyim'), ('Staj', 5))

    def test_thresholds(self):
        for text, level, years in (('en az 1 yıl deneyim', 'Junior / Yeni mezun', 1), ('en az 2 yıl deneyim', 'Orta (2-4 yıl)', 2),
                                   ('en az 4 yıl deneyim', 'Orta (2-4 yıl)', 4), ('en az 5 yıl deneyim', 'Kıdemli+', 5)):
            self.assertEqual(seniority.level_from('Belirtilmemiş', text), (level, years), text)

    def test_zero_years_is_junior(self):
        self.assertEqual(seniority.level_from('Belirtilmemiş', '0-1 yıl deneyim')[0], 'Junior / Yeni mezun')

    def test_newgrad_phrase_without_years(self):
        self.assertEqual(seniority.level_from('Belirtilmemiş', 'Yeni mezunlar için fırsat'), ('Junior / Yeni mezun', None))

    def test_years_beat_newgrad_phrase(self):
        # "yeni mezun" gecse de net bir yil sarti varsa o kullanilir
        self.assertEqual(seniority.level_from('Belirtilmemiş', 'yeni mezun degil, en az 6 yıl deneyim')[0], 'Kıdemli+')

    def test_nothing_known(self):
        self.assertEqual(seniority.level_from('Belirtilmemiş', 'Güzel bir ekibe katılın'), ('Belirtilmemiş', None))


class HealthFlags(unittest.TestCase):
    def test_healthy(self):
        self.assertEqual(scanner.health_flags(50, 52, 0.95), [])

    def test_small_sources_are_ignored(self):
        self.assertEqual(scanner.health_flags(9, 0, 0.0), [])

    def test_count_drop(self):
        flags = scanner.health_flags(100, 30, 0.9)
        self.assertEqual(len(flags), 1)
        self.assertIn('100 -> 30', flags[0])

    def test_count_drop_boundary(self):
        self.assertEqual(scanner.health_flags(100, 40, 0.9), [])      # tam %40: uyari yok
        self.assertEqual(len(scanner.health_flags(100, 39, 0.9)), 1)

    def test_identity_churn(self):
        flags = scanner.health_flags(20, 20, 0.1)
        self.assertEqual(len(flags), 1)
        self.assertIn('%90', flags[0])

    def test_both_flags(self):
        self.assertEqual(len(scanner.health_flags(100, 10, 0.05)), 2)

    def test_first_run_has_no_overlap(self):
        self.assertEqual(scanner.health_flags(0, 50, None), [])

    def test_generic_sources_are_checked_from_five_jobs(self):
        self.assertEqual(len(scanner.health_flags(8, 8, 0.0, 'genel')), 1)
        self.assertEqual(len(scanner.health_flags(5, 1, 0.9, 'genel')), 1)
        self.assertEqual(scanner.health_flags(8, 8, 0.0, 'lever'), [])
        self.assertEqual(scanner.health_flags(4, 0, 0.0, 'genel'), [])


class ProgramJobs(unittest.TestCase):
    def test_location_comes_from_page(self):
        p = dict(url='https://x.com/staj', title='Staj', status='Başvuru açık', kind='Staj', text='metin', location='Küresel program sayfası')
        (j,) = scanner.program_jobs([p])
        self.assertEqual(j['location'], 'Küresel program sayfası')
        self.assertEqual(scanner.region_of(j['location']), 'Yurt dışı')
        self.assertEqual(scanner.region_of(scanner.program_jobs([dict(p, location='')])[0]['location']), 'Belirtilmemiş')
        self.assertEqual(scanner.region_of(scanner.program_jobs([dict(p, location='Türkiye')])[0]['location']), 'Türkiye')


class ScanProgramsRobots(TempDb):
    def test_robots_blocked_program_page_is_closed(self):
        import json
        a, b = 'https://firma.com.tr/staj', 'https://firma.com.tr/genc-yetenek'
        prog = lambda u: dict(url=u, title='Staj', status='Başvuru açık', kind='Staj', text='metin', location='Türkiye', links=[])
        c = dict(id=1, name='Firma', program_urls=json.dumps([a, b]))
        with mock.patch.object(scanner.programs, 'read', side_effect=lambda u, c: prog(u)):
            scanner.scan_programs(self.con, c)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM jobs WHERE source='program' AND active=1").fetchone()[0], 2)

        def read(u, c):
            if u == b:
                raise HttpError('robots', u, 'robots.txt izin vermiyor')
            return None  # a: gecici hata (okunamadi)
        with mock.patch.object(scanner.programs, 'read', side_effect=read):
            scanner.scan_programs(self.con, c)
        active = {r[0] for r in self.con.execute("SELECT ext_id FROM jobs WHERE source='program' AND active=1")}
        self.assertEqual(active, {a})     # gecici hata kapatmaz, robots engeli kapatir
        self.assertEqual(json.loads(self.con.execute('SELECT program_urls FROM companies WHERE id=1').fetchone()[0]), [a])


class JobBoards(unittest.TestCase):
    def test_boards(self):
        for url in ('https://www.kariyer.net', 'https://tr.linkedin.com/company/x', 'youthall.com', 'https://jobs.techcareer.net/x',
                    'https://turbin.ai/jobs'):
            self.assertTrue(scanner.is_job_board(url), url)

    def test_companies(self):
        for url in ('https://www.turkcell.com.tr', 'https://notkariyer.net', 'https://kariyer.net.evil.com', '', None):
            self.assertFalse(scanner.is_job_board(url), url)


class UpsertBase(TempDb):
    def setUp(self):
        super().setUp()
        scanner._NEW_IDS.clear()

    def job(self, ext, **kw):
        d = dict(id=ext, title=f'Backend Developer {ext}', url=f'https://x/{ext}', location='Istanbul')
        d.update(kw)
        return d

    def row(self, ext, source='lever'):
        return self.con.execute('SELECT * FROM jobs WHERE company_id=1 AND source=? AND ext_id=?', (source, ext)).fetchone()

    def active(self, source='lever'):
        return {r['ext_id'] for r in self.con.execute('SELECT ext_id FROM jobs WHERE company_id=1 AND source=? AND active=1', (source,))}


class UpsertInsert(UpsertBase):
    def test_return_values_on_first_insert(self):
        new, closed, prev, overlap, rows = scanner.upsert(self.con, 1, 'lever', [self.job('a'), self.job('b')])
        self.assertEqual((new, closed, prev, overlap), (2, 0, 0, None))
        self.assertEqual([r[1]['id'] for r in rows], ['a', 'b'])

    def test_fields_are_classified_and_stored(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a', title='Junior Python Developer', location='Ankara', team='Platform',
                                                          posted='2026-01-05', desc='en az 1 yıl deneyim')])
        r = self.row('a')
        self.assertEqual((r['level'], r['is_tech'], r['region']), ('Junior / Yeni mezun', 1, 'Türkiye'))
        self.assertEqual((r['posted'], r['team'], r['active'], r['hidden'], r['applied']), ('2026-01-05', 'Platform', 1, 0, 0))
        self.assertEqual(r['exp_min'], 1)

    def test_level_comes_from_description_when_title_is_silent(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a', desc='En az 5 yıl deneyim')])
        self.assertEqual((self.row('a')['level'], self.row('a')['exp_min']), ('Kıdemli+', 5))

    def test_explicit_level_overrides_everything(self):
        scanner.upsert(self.con, 1, 'program', [self.job('p', title='Senior Program', level='Staj', desc='en az 8 yıl')])
        r = self.row('p', 'program')
        self.assertEqual((r['level'], r['exp_min']), ('Staj', None))

    def test_explicit_tech_flag_overrides_title(self):
        scanner.upsert(self.con, 1, 'program', [self.job('p', title='Muhasebe Programı', tech=True)])
        scanner.upsert(self.con, 1, 'program', [self.job('q', title='Backend Developer', tech=False)])
        self.assertEqual((self.row('p', 'program')['is_tech'], self.row('q', 'program')['is_tech']), (1, 0))

    def test_remote_flag_sets_region(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a', location='', remote=True), self.job('b', location='Berlin', remote=True)])
        self.assertEqual(self.row('a')['region'], 'Uzaktan')
        self.assertIsNone(self.row('b'))

    def test_new_ids_are_tracked(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a'), self.job('b')])
        ids = {self.row('a')['id'], self.row('b')['id']}
        self.assertEqual(set(scanner._NEW_IDS), ids)

    def test_skips_jobs_without_title(self):
        new, *_ = scanner.upsert(self.con, 1, 'lever', [self.job('empty', title=''), self.job('none', title=None), self.job('ok')])
        self.assertEqual((new, self.active()), (1, {'ok'}))

    def test_url_is_used_when_id_missing(self):
        scanner.upsert(self.con, 1, 'lever', [{'title': 'Dev', 'url': 'https://x/only-url', 'location': 'Istanbul'}])
        self.assertEqual(self.active(), {'https://x/only-url'})

    def test_duplicate_ids_in_one_list_are_inserted_once(self):
        new, *_ = scanner.upsert(self.con, 1, 'lever', [self.job('a'), self.job('a', title='Other')])
        self.assertEqual(new, 1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)

    def test_numeric_ids_are_stringified(self):
        scanner.upsert(self.con, 1, 'lever', [self.job(12345)])
        self.assertEqual(self.active(), {'12345'})

    def test_long_ids_and_descriptions_are_truncated(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('x' * 800, desc='d' * 9000)])
        r = self.con.execute('SELECT ext_id, description FROM jobs').fetchone()
        self.assertEqual((len(r['ext_id']), len(r['description'])), (500, 6000))

    def test_same_ext_id_in_different_sources_or_companies_is_separate(self):
        self.con.execute("INSERT INTO companies(id, name) VALUES(2, 'Baska')")
        self.con.commit()
        scanner.upsert(self.con, 1, 'lever', [self.job('a')])
        scanner.upsert(self.con, 1, 'genel', [self.job('a')])
        scanner.upsert(self.con, 2, 'lever', [self.job('a')])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 3)

    def test_detail_defaults(self):
        scanner.upsert(self.con, 1, 'genel', [self.job('g')])
        scanner.upsert(self.con, 1, 'lever', [self.job('l')])
        scanner.upsert(self.con, 1, 'workday', [self.job('w', detail=('workday', 'https://x/api/w'))])
        g, l, w = self.row('g', 'genel'), self.row('l'), self.row('w', 'workday')
        self.assertEqual((g['detail_kind'], g['detail_url']), ('page', 'https://x/g'))     # genel/ozel: ilan sayfasi
        self.assertEqual((l['detail_kind'], l['detail_url']), (None, None))               # ATS: aciklama listede geliyor
        self.assertEqual((w['detail_kind'], w['detail_url']), ('workday', 'https://x/api/w'))


class HiddenCompany(UpsertBase):
    def test_new_jobs_of_hidden_company_go_to_hidden(self):
        self.con.execute('UPDATE companies SET hide_jobs=1 WHERE id=1')
        self.con.commit()
        scanner.upsert(self.con, 1, 'lever', [self.job('a')])
        self.assertEqual(self.row('a')['hidden'], 1)
        _, fit = scanner._summarize_new()  # gizli ilan "bana uygun" bildirimine girmez
        self.assertEqual(fit, [])

    def test_user_unhide_survives_rescan(self):
        self.con.execute('UPDATE companies SET hide_jobs=1 WHERE id=1')
        self.con.commit()
        scanner.upsert(self.con, 1, 'lever', [self.job('a')])
        self.con.execute("UPDATE jobs SET hidden=0 WHERE ext_id='a'")
        self.con.commit()
        scanner.upsert(self.con, 1, 'lever', [self.job('a')])
        self.assertEqual(self.row('a')['hidden'], 0)

    def test_default_hidden_companies(self):
        for i, n in ((2, 'Baykar'), (3, 'TUSAŞ (Türk Havacılık ve Uzay Sanayii)'), (4, 'ROKETSAN'), (5, 'ASELSAN'),
                     (6, 'TÜBİTAK BİLGEM'), (7, 'Trendyol')):
            self.con.execute('INSERT INTO companies(id, name) VALUES(?, ?)', (i, n))
        self.con.execute("INSERT INTO jobs(company_id, source, ext_id, title) VALUES(5, 'genel', 'x', 'Yazılım Mühendisi')")
        db._hide_defaults(self.con)
        hidden = {r[0] for r in self.con.execute('SELECT id FROM companies WHERE hide_jobs=1')}
        self.assertEqual(hidden, {2, 3, 4, 5, 6})
        self.assertEqual(self.con.execute("SELECT hidden FROM jobs WHERE ext_id='x'").fetchone()[0], 1)


class UpsertUpdate(UpsertBase):
    def test_update_keeps_user_marks_and_first_seen(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a')])
        self.con.execute("UPDATE jobs SET applied=1, starred=1, hidden=1, note='not', seen=1, first_seen='2026-01-01'")
        self.con.commit()
        new, *_ = scanner.upsert(self.con, 1, 'lever', [self.job('a', title='Backend Developer (guncel)')])
        r = self.row('a')
        self.assertEqual(new, 0)
        self.assertEqual((r['applied'], r['starred'], r['hidden'], r['note'], r['seen'], r['first_seen']), (1, 1, 1, 'not', 1, '2026-01-01'))
        self.assertEqual(r['title'], 'Backend Developer (guncel)')

    def test_update_does_not_count_as_new(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a')])
        scanner._NEW_IDS.clear()
        scanner.upsert(self.con, 1, 'lever', [self.job('a')])
        self.assertEqual(scanner._NEW_IDS, [])

    def test_existing_description_is_kept_when_list_has_none(self):
        scanner.upsert(self.con, 1, 'workday', [self.job('a', desc='en az 3 yıl deneyim')])
        scanner.upsert(self.con, 1, 'workday', [self.job('a')])                     # liste ucu aciklama vermiyor
        r = self.row('a', 'workday')
        self.assertEqual(r['description'], 'en az 3 yıl deneyim')
        self.assertEqual((r['level'], r['exp_min']), ('Orta (2-4 yıl)', 3))         # seviye eski aciklamadan yeniden hesaplanir

    def test_new_description_replaces_old(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a', desc='eski')])
        scanner.upsert(self.con, 1, 'lever', [self.job('a', desc='yeni metin')])
        self.assertEqual(self.row('a')['description'], 'yeni metin')

    def test_posted_date_is_not_erased(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a', posted='2026-02-01')])
        scanner.upsert(self.con, 1, 'lever', [self.job('a')])
        self.assertEqual(self.row('a')['posted'], '2026-02-01')
        scanner.upsert(self.con, 1, 'lever', [self.job('a', posted='2026-02-09')])
        self.assertEqual(self.row('a')['posted'], '2026-02-09')

    def test_closed_job_reopens_when_it_returns(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a'), self.job('b')])
        scanner.upsert(self.con, 1, 'lever', [self.job('b')])
        self.assertEqual(self.row('a')['active'], 0)
        new, *_ = scanner.upsert(self.con, 1, 'lever', [self.job('a'), self.job('b')])
        self.assertEqual((self.row('a')['active'], new), (1, 0))                    # yeniden acilan ilan "yeni" degil


class UpsertClose(UpsertBase):
    def fill(self, n, source='lever'):
        scanner.upsert(self.con, 1, source, [self.job(f'j{i}') for i in range(n)])

    def test_missing_jobs_are_closed_and_counted(self):
        self.fill(3)
        new, closed, prev, overlap, _ = scanner.upsert(self.con, 1, 'lever', [self.job('j0'), self.job('j1'), self.job('n')])
        self.assertEqual((new, closed, prev), (1, 1, 3))
        self.assertAlmostEqual(overlap, 2 / 3)
        self.assertEqual(self.active(), {'j0', 'j1', 'n'})

    def test_closing_only_touches_the_same_source(self):
        self.fill(2)
        self.fill(2, 'genel')
        scanner.upsert(self.con, 1, 'lever', [self.job('j0')])
        self.assertEqual(self.active('genel'), {'j0', 'j1'})

    def test_non_definitive_never_closes(self):
        self.fill(3)
        _, closed, *_ = scanner.upsert(self.con, 1, 'lever', [self.job('j0')], definitive=False)
        self.assertEqual(closed, 0)
        self.assertEqual(self.active(), {'j0', 'j1', 'j2'})

    def test_guard_keeps_jobs_when_big_source_suddenly_empty(self):
        self.fill(10)
        _, closed, prev, overlap, _ = scanner.upsert(self.con, 1, 'lever', [])
        self.assertEqual((closed, prev, overlap), (0, 10, 0.0))
        self.assertEqual(len(self.active()), 10)

    def test_guard_allows_closing_tiny_source(self):
        self.fill(3)
        _, closed, *_ = scanner.upsert(self.con, 1, 'lever', [])
        self.assertEqual(closed, 3)

    def test_guard_boundary_is_three_jobs(self):
        self.fill(4)
        _, closed, *_ = scanner.upsert(self.con, 1, 'lever', [])
        self.assertEqual(closed, 0)

    def test_guard_disabled_closes_everything(self):
        self.fill(10)
        _, closed, *_ = scanner.upsert(self.con, 1, 'lever', [], guard=False)
        self.assertEqual(closed, 10)

    def test_invalid_only_list_counts_as_empty_for_guard(self):
        self.fill(10)
        _, closed, *_ = scanner.upsert(self.con, 1, 'lever', [{'id': 'x', 'title': ''}])
        self.assertEqual(closed, 0)

    def test_overlap_none_on_first_run_and_zero_on_full_replacement(self):
        self.assertIsNone(scanner.upsert(self.con, 1, 'lever', [self.job('a')])[3])
        self.assertEqual(scanner.upsert(self.con, 1, 'lever', [self.job('b')])[3], 0.0)


class Enrich(UpsertBase):
    def setUp(self):
        super().setUp()
        self.pace = mock.patch.object(enrich, 'pace', lambda: None)
        self.pace.start()
        self.addCleanup(self.pace.stop)

    def add(self, ext, **kw):
        # definitive=False: tek ilanlik listeler oncekileri kapatmasin
        scanner.upsert(self.con, 1, 'workday', [self.job(ext, detail=('workday', f'https://x/d/{ext}'), **kw)], definitive=False)

    def test_fills_description_level_and_date(self):
        self.add('a')
        with mock.patch.object(enrich, 'fetch_detail', return_value=('en az 6 yıl deneyim', '2026-03-01', None)) as f:
            self.assertEqual(scanner.enrich_pending(1), 1)
        f.assert_called_once_with('workday', 'https://x/d/a')
        r = self.row('a', 'workday')
        self.assertEqual((r['description'], r['level'], r['exp_min'], r['posted'], r['detail_checked']),
                         ('en az 6 yıl deneyim', 'Kıdemli+', 6, '2026-03-01', 1))

    def test_title_level_survives_enrichment(self):
        scanner.upsert(self.con, 1, 'workday', [self.job('a', title='Junior Developer', detail=('workday', 'https://x/d/a'))])
        with mock.patch.object(enrich, 'fetch_detail', return_value=('en az 6 yıl deneyim', None, None)):
            scanner.enrich_pending(1)
        self.assertEqual(self.row('a', 'workday')['level'], 'Junior / Yeni mezun')

    def test_existing_posted_date_is_kept(self):
        self.add('a', posted='2026-01-01')
        with mock.patch.object(enrich, 'fetch_detail', return_value=('metin', '2026-03-01', None)):
            scanner.enrich_pending(1)
        self.assertEqual(self.row('a', 'workday')['posted'], '2026-01-01')

    def test_failed_fetch_is_marked_checked_and_not_retried(self):
        self.add('a')
        with mock.patch.object(enrich, 'fetch_detail', return_value=(None, None, None)):
            self.assertEqual(scanner.enrich_pending(1), 0)
        r = self.row('a', 'workday')
        self.assertEqual((r['description'], r['detail_checked']), (None, 1))
        with mock.patch.object(enrich, 'fetch_detail') as f:
            scanner.enrich_pending(1)
        f.assert_not_called()

    def test_skips_abroad_and_already_described_and_closed(self):
        self.add('abroad', location='London, UK')
        self.add('described', desc='zaten var')
        self.add('closed')
        self.con.execute("UPDATE jobs SET active=0 WHERE ext_id='closed'")
        self.add('ok', location='')                                                  # konum belirtilmemis: cekilir
        self.con.commit()
        with mock.patch.object(enrich, 'fetch_detail', return_value=('metin', None, None)) as f:
            self.assertEqual(scanner.enrich_pending(1), 1)
        f.assert_called_once_with('workday', 'https://x/d/ok')

    def test_skips_jobs_without_detail_url(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a')])
        with mock.patch.object(enrich, 'fetch_detail') as f:
            scanner.enrich_pending(1)
        f.assert_not_called()

    def test_per_company_limit_and_tech_first(self):
        for i in range(5):
            self.add(f'x{i}', title=f'Muhasebe {i}')
        self.add('tech', title='Backend Developer')
        calls = []
        with mock.patch.object(enrich, 'MAX_PER_COMPANY', 3), \
                mock.patch.object(enrich, 'fetch_detail', side_effect=lambda k, u: calls.append(u) or ('metin', None, None)):
            self.assertEqual(scanner.enrich_pending(1), 3)
        self.assertEqual(calls[0], 'https://x/d/tech')                               # teknik ilanlar once
        self.assertEqual(len(calls), 3)

    def test_other_companies_are_untouched(self):
        self.con.execute("INSERT INTO companies(id, name) VALUES(2, 'Baska')")
        self.con.commit()
        scanner.upsert(self.con, 2, 'workday', [self.job('z', detail=('workday', 'https://x/d/z'))])
        with mock.patch.object(enrich, 'fetch_detail') as f:
            scanner.enrich_pending(1)
        f.assert_not_called()


class FetchDetail(unittest.TestCase):
    def test_http_error_returns_none_triple(self):
        with mock.patch.dict(enrich.KINDS, {'page': mock.Mock(side_effect=HttpError(404, 'u'))}):
            self.assertEqual(enrich.fetch_detail('page', 'u'), (None, None, None))

    def test_bad_json_returns_none_triple(self):
        with mock.patch.object(enrich, 'fetch', return_value=(200, 'u', 'not json')):
            self.assertEqual(enrich.fetch_detail('workday', 'u'), (None, None, None))

    def test_unknown_kind_returns_none_triple(self):
        self.assertEqual(enrich.fetch_detail('nope', 'u'), (None, None, None))

    def test_workday_payload(self):
        body = '{"jobPostingInfo": {"jobDescription": "<p>Ho\\u015f   <b>geldin</b></p>", "startDate": "2026-04-02T00:00:00"}}'
        with mock.patch.object(enrich, 'fetch', return_value=(200, 'u', body)):
            self.assertEqual(enrich.fetch_detail('workday', 'u'), ('Hoş geldin', '2026-04-02', None))

    def test_page_strips_scripts_and_styles(self):
        html = '<html><script>var x=1</script><style>p{}</style><nav>menu</nav><p>Ilan   metni</p><footer>alt</footer></html>'
        with mock.patch.object(enrich, 'fetch', return_value=(200, 'u', html)):
            self.assertEqual(enrich.fetch_detail('page', 'u'), ('Ilan metni', None, None))


class ScanKnown(UpsertBase):
    """scan_known: okuyucu cevabini veritabanina ve firma durumuna yansitir; hata dallari."""

    def setUp(self):
        super().setUp()
        for k in ('new', 'closed', 'ok', 'failed'):
            scanner.STATE[k] = 0
        scanner.STATE['log'].clear()
        p = mock.patch.object(scanner, 'enrich_pending', lambda cid: 0)
        p.start()
        self.addCleanup(p.stop)

    def company(self, **kw):
        base = dict(id=1, name='Firma', ats='lever', ats_slug='firma', ats_extra=None, job_count=0)
        base.update(kw)
        return base

    def status(self):
        return self.con.execute('SELECT status, status_note, job_count, ats, ats_extra, checked_at FROM companies WHERE id=1').fetchone()

    def runs(self):
        return [dict(r) for r in self.con.execute('SELECT source, ok, count, new, closed, prev_active, error FROM source_runs ORDER BY id')]

    def test_success_with_ats(self):
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=[self.job('a'), self.job('b')]):
            scanner.scan_known(self.con, self.company())
        s = self.status()
        self.assertEqual((s['status'], s['job_count']), ('ats', 2))
        self.assertIn('lever: 2 ilan', s['status_note'])
        self.assertEqual(self.runs(), [dict(source='lever', ok=1, count=2, new=2, closed=0, prev_active=0, error=None)])
        self.assertEqual((scanner.STATE['new'], scanner.STATE['ok'], scanner.STATE['failed']), (2, 1, 0))

    def test_success_with_custom_reader(self):
        with mock.patch.dict(scanner.custom.REGISTRY, {'acme': lambda: [self.job('a')]}):
            scanner.scan_known(self.con, self.company(ats='custom', ats_slug='acme'))
        self.assertEqual(self.status()['status'], 'ozel')
        self.assertEqual(self.runs()[0]['source'], 'ozel')
        self.assertEqual(self.row('a', 'ozel')['detail_kind'], 'page')

    def test_warns_when_no_job_is_in_turkey(self):
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=[self.job('a', location='Berlin')]):
            scanner.scan_known(self.con, self.company())
        self.assertIn('yanlis eslesme', self.status()['status_note'])

    def test_no_warning_for_custom_reader(self):
        with mock.patch.dict(scanner.custom.REGISTRY, {'acme': lambda: [self.job('a', location='Berlin')]}):
            scanner.scan_known(self.con, self.company(ats='custom', ats_slug='acme'))
        self.assertNotIn('yanlis eslesme', self.status()['status_note'])

    def test_health_warning_is_recorded(self):
        scanner.upsert(self.con, 1, 'lever', [self.job(f'j{i}') for i in range(20)])
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=[self.job('j0'), self.job('j1')]):
            scanner.scan_known(self.con, self.company(job_count=20))
        self.assertIn('SAGLIK', self.status()['status_note'])
        self.assertTrue(any('kaynak sagligi' in m for m in scanner.STATE['log']))

    def test_closed_jobs_are_counted(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a'), self.job('b')])
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=[self.job('a')]):
            scanner.scan_known(self.con, self.company())
        self.assertEqual((scanner.STATE['closed'], self.runs()[-1]['closed']), (1, 1))

    def test_dead_ats_account_falls_back_to_generic(self):
        for code in (403, 404, 410):
            self.con.execute("UPDATE companies SET ats='lever', ats_extra=NULL, checked_at='2026-01-01'")
            self.con.commit()
            with mock.patch.object(atsmod, 'fetch_jobs', side_effect=HttpError(code, 'u')):
                scanner.scan_known(self.con, self.company(job_count=7))
            s = self.status()
            self.assertEqual((s['ats'], s['ats_extra'], s['checked_at']), ('generic', 'lever', None), code)   # yeniden kesfedilecek
            self.assertEqual((s['status'], s['job_count']), ('hata', 7), code)
            self.assertIn(str(code), s['status_note'])

    def test_other_errors_keep_ats_and_job_count(self):
        with mock.patch.object(atsmod, 'fetch_jobs', side_effect=HttpError(500, 'u')):
            scanner.scan_known(self.con, self.company(job_count=7))
        s = self.status()
        self.assertEqual((s['ats'], s['status'], s['job_count']), (None, 'hata', 7))     # test firmasinda ats NULL'di: degismedi, 'generic' olmadi
        self.assertIn('okunamadi', s['status_note'])
        (run,) = self.runs()
        self.assertEqual((run['source'], run['ok'], run['count']), ('lever', 0, 0))
        self.assertTrue(run['error'])
        self.assertEqual((scanner.STATE['failed'], scanner.STATE['ok']), (1, 0))

    def test_custom_reader_404_does_not_trigger_fallback(self):
        def boom():
            raise HttpError(404, 'u')
        self.con.execute("UPDATE companies SET ats='custom', ats_slug='acme'")
        self.con.commit()
        with mock.patch.dict(scanner.custom.REGISTRY, {'acme': boom}):
            scanner.scan_known(self.con, self.company(ats='custom', ats_slug='acme'))
        self.assertEqual(self.status()['ats'], 'custom')

    def test_failure_does_not_close_existing_jobs(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a'), self.job('b')])
        with mock.patch.object(atsmod, 'fetch_jobs', side_effect=OSError('ag yok')):
            scanner.scan_known(self.con, self.company())
        self.assertEqual(self.active(), {'a', 'b'})

    def test_confirmed_empty_list_closes_old_jobs(self):  # Workday: hesapta Turkiye ilani yok
        scanner.upsert(self.con, 1, 'workday', [self.job(f'j{i}') for i in range(20)])
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=atsmod.Jobs(note="Turkiye'de ilani yok (toplam 20)", confirmed=True)):
            scanner.scan_known(self.con, self.company(ats='workday'))
        self.assertEqual(self.active('workday'), set())
        self.assertIn("workday: 0 ilan (Turkiye'de ilani yok", self.status()['status_note'])

    def test_unconfirmed_empty_list_keeps_old_jobs(self):
        scanner.upsert(self.con, 1, 'workday', [self.job(f'j{i}') for i in range(20)])
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=atsmod.Jobs()):
            scanner.scan_known(self.con, self.company(ats='workday'))
        self.assertEqual(len(self.active('workday')), 20)

    def test_reader_note_is_shown(self):
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=atsmod.Jobs([self.job('a')], note='Turkiye filtresi: 1 / 900 ilan')):
            scanner.scan_known(self.con, self.company(ats='workday'))
        self.assertIn('workday: 1 ilan (Turkiye filtresi: 1 / 900 ilan)', self.status()['status_note'])

    def test_identity_churn_jobs_are_not_new(self):
        scanner.upsert(self.con, 1, 'lever', [self.job(f'old{i}') for i in range(10)])
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=[self.job(f'new{i}') for i in range(10)]):
            scanner.scan_known(self.con, self.company())
        self.assertEqual({self.row(f'new{i}')['is_baseline'] for i in range(10)}, {1})
        self.assertIn('SAGLIK', self.status()['status_note'])
        self.assertTrue(any('kimlik kaymasi' in m for m in scanner.STATE['log']))
        self.assertEqual(scanner._summarize_new()[0], 0)

    def test_robots_block_closes_jobs_and_is_not_a_failure(self):  # Garanti: robots.txt arama motorlari disini engelliyor
        def blocked():
            raise HttpError('robots', 'https://kariyer.ornek.com.tr/', 'robots.txt izin vermiyor')
        self.con.execute("UPDATE companies SET ats='custom', ats_slug='acme'")
        self.con.commit()
        scanner.upsert(self.con, 1, 'ozel', [self.job('a'), self.job('b')])
        with mock.patch.dict(scanner.custom.REGISTRY, {'acme': blocked}):
            scanner.scan_known(self.con, self.company(ats='custom', ats_slug='acme', job_count=2))
        s = self.status()
        self.assertEqual((s['status'], s['job_count'], s['ats']), ('robots', 0, 'custom'))
        self.assertIn('robots.txt', s['status_note'])
        self.assertEqual(self.active('ozel'), set())
        self.assertEqual((scanner.STATE['failed'], scanner.STATE['ok'], scanner.STATE['closed']), (0, 1, 2))
        self.assertEqual(self.runs()[-1]['ok'], 1)

    def test_normal_new_jobs_stay_new(self):
        scanner.upsert(self.con, 1, 'lever', [self.job(f'old{i}') for i in range(10)])
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=[self.job(f'old{i}') for i in range(10)] + [self.job('yeni')]):
            scanner.scan_known(self.con, self.company())
        self.assertEqual(self.row('yeni')['is_baseline'], 0)
        self.assertNotIn('SAGLIK', self.status()['status_note'])


class ScanDiscoverGeneric(UpsertBase):
    """scan_discover: kariyer sayfasindan genel ayristirici ile okunan firmalar; saglik kontrolu ve ilan siteleri."""

    def setUp(self):
        super().setUp()
        for k in ('new', 'closed', 'ok', 'failed'):
            scanner.STATE[k] = 0
        scanner.STATE['log'].clear()
        self.con.execute("UPDATE companies SET ats='generic', status='genel', career_url='https://firma.com.tr/kariyer', "
                         "checked_at='2026-10-20T10:00', website='https://firma.com.tr'")
        self.con.commit()
        p = mock.patch.object(scanner, 'enrich_pending', lambda cid: 0)
        p.start()
        self.addCleanup(p.stop)

    def company(self):
        return dict(self.con.execute('SELECT * FROM companies WHERE id=1').fetchone())

    def scan(self, jobs):
        with mock.patch.object(scanner.browser, 'render', return_value=('https://firma.com.tr/kariyer', '', [], [])), \
                mock.patch.object(scanner.generic, 'extract', return_value=jobs):
            scanner.scan_discover(self.con, self.company())

    def note(self):
        return self.con.execute('SELECT status_note FROM companies WHERE id=1').fetchone()[0]

    def test_identity_churn_is_flagged_and_not_new(self):  # Turbin / Ericsson: her taramada baska ilanlar
        self.scan([self.job(f'a{i}') for i in range(6)])
        self.scan([self.job(f'b{i}') for i in range(6)])
        self.assertIn('SAGLIK', self.note())
        self.assertEqual({self.row(f'b{i}', 'genel')['is_baseline'] for i in range(6)}, {1})
        self.assertEqual(scanner._summarize_new()[0], 0)

    def test_stable_list_is_healthy_and_new_job_counts(self):
        self.scan([self.job(f'a{i}') for i in range(6)])
        self.scan([self.job(f'a{i}') for i in range(6)] + [self.job('a6')])
        self.assertNotIn('SAGLIK', self.note())
        self.assertEqual(self.row('a6', 'genel')['is_baseline'], 0)

    def test_robots_block_on_career_page(self):  # Ericsson: jobs.ericsson.com robots.txt ile engelli
        self.scan([self.job(f'a{i}') for i in range(6)])
        with mock.patch.object(scanner.browser, 'render', side_effect=HttpError('robots', 'u', 'robots.txt izin vermiyor')):
            scanner.scan_discover(self.con, self.company())
        s = self.con.execute('SELECT status, status_note FROM companies WHERE id=1').fetchone()
        self.assertEqual(s['status'], 'robots')
        self.assertEqual(self.active('genel'), set())

    def test_robots_block_found_during_discovery(self):
        self.scan([self.job(f'a{i}') for i in range(6)])
        self.con.execute('UPDATE companies SET checked_at=NULL')
        self.con.commit()
        r = dict(career_url=None, ats=None, ats_slug=None, ats_extra=None, status='robots', status_note='robots.txt izin vermiyor', jobs=None)
        with mock.patch.object(scanner.careers, 'discover', return_value=r):
            scanner.scan_discover(self.con, self.company())
        self.assertEqual(self.con.execute('SELECT status FROM companies WHERE id=1').fetchone()[0], 'robots')
        self.assertEqual(self.active('genel'), set())

    def test_job_board_site_is_not_scanned(self):
        self.scan([self.job(f'a{i}') for i in range(6)])
        self.con.execute("UPDATE companies SET website='https://turbin.ai', career_url='https://turbin.ai/jobs'")
        self.con.commit()
        with mock.patch.object(scanner.browser, 'render') as render:
            scanner.scan_discover(self.con, self.company())
        render.assert_not_called()
        s = self.con.execute('SELECT status FROM companies WHERE id=1').fetchone()[0]
        self.assertEqual((s, self.active('genel')), ('ilan-sitesi', set()))


class SummarizeNew(UpsertBase):
    """upsert -> _summarize_new: yeni sayilanlar ve 'bana uygun' olanlar."""

    def test_counts_only_non_baseline_recent_jobs(self):
        self.con.execute("INSERT INTO source_runs(run_at, company_id, source, ok) VALUES('2020-01-01T00:00:00', 1, 'lever', 1)")
        self.con.commit()
        scanner.upsert(self.con, 1, 'lever', [self.job('fit', title='Junior Backend Developer'), self.job('senior', title='Senior Backend Developer'),
                                              self.job('abroad', title='Junior Backend Developer', location='London, UK')])
        fresh, fit = scanner._summarize_new()
        self.assertEqual(fresh, 2)
        self.assertEqual([f['title'] for f in fit], ['Junior Backend Developer'])
        self.assertEqual(fit[0]['company'], 'Firma')

    def test_first_scan_counts_nothing(self):
        scanner.upsert(self.con, 1, 'lever', [self.job('a', title='Junior Backend Developer')])
        self.assertEqual(scanner._summarize_new(), (0, []))


class StopScan(unittest.TestCase):
    def test_stop_sets_event_only_when_running(self):
        scanner._stop.clear()
        scanner.STATE['running'] = False
        scanner.STATE['stopping'] = False
        self.assertFalse(scanner.stop())
        self.assertFalse(scanner._stop.is_set())
        scanner.STATE['running'] = True
        try:
            self.assertTrue(scanner.stop())
            self.assertTrue(scanner._stop.is_set())
            self.assertTrue(scanner.STATE['stopping'])
        finally:
            scanner._stop.clear()
            scanner.STATE['running'] = False
            scanner.STATE['stopping'] = False


if __name__ == '__main__':
    unittest.main()


class TrOnly(UpsertBase):
    """Cok uluslu firmalar (tr_only=1): kaynagin yalnizca Turkiye'deki ilanlari alinir."""

    def setUp(self):
        super().setUp()
        for k in ('new', 'closed', 'ok', 'failed'):
            scanner.STATE[k] = 0
        p = mock.patch.object(scanner, 'enrich_pending', lambda cid: 0)
        p.start()
        self.addCleanup(p.stop)

    def company(self):
        return dict(id=1, name='Firma', ats='greenhouse', ats_slug='firma', ats_extra=None, job_count=0, tr_only=1)

    def test_only_turkey_jobs_are_kept(self):
        jobs = [self.job('a', location='Istanbul, Turkey'), self.job('b', location='London, UK'), self.job('c', location='Ankara')]
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=jobs):
            scanner.scan_known(self.con, self.company())
        self.assertEqual(self.active('greenhouse'), {'a', 'c'})
        self.assertIn('Turkiye filtresi: 2 / 3', self.con.execute('SELECT status_note FROM companies WHERE id=1').fetchone()[0])

    def test_no_turkey_jobs_left_closes_old_ones(self):
        many = [self.job(str(i), location='Istanbul') for i in range(12)]
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=many):
            scanner.scan_known(self.con, self.company())
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=[self.job('x', location='Berlin, Germany')]):
            scanner.scan_known(self.con, self.company())
        self.assertEqual(self.active('greenhouse'), set())  # kaynak calisiyor, Turkiye'de ilan kalmadi: koruma devreye girmez

    def test_broken_source_does_not_close(self):
        many = [self.job(str(i), location='Istanbul') for i in range(12)]
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=many):
            scanner.scan_known(self.con, self.company())
        with mock.patch.object(atsmod, 'fetch_jobs', return_value=[]):
            scanner.scan_known(self.con, self.company())
        self.assertEqual(len(self.active('greenhouse')), 12)


class Seeds(TempDb):
    def write(self, items):
        import json
        import os
        path = os.path.join(self.tmp, 'seeds.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(items, f)
        return path

    def test_new_company_is_added_with_ats(self):
        path = self.write([{'firma': 'Mastercard', 'ats': 'workday', 'slug': 'mastercard', 'extra': 'wd1|CorporateCareers',
                            'web': 'https://mastercard.com'}])
        self.assertEqual(db.sync_seeds(self.con, path), (1, 0))
        r = self.con.execute("SELECT * FROM companies WHERE name='Mastercard'").fetchone()
        self.assertEqual((r['ats'], r['ats_slug'], r['ats_extra'], r['tr_only'], r['size']),
                         ('workday', 'mastercard', 'wd1|CorporateCareers', 1, 'Büyük / kurumsal'))
        self.assertEqual(db.sync_seeds(self.con, path), (0, 0))  # ikinci calisma bir sey degistirmez

    def test_existing_company_without_ats_is_linked_and_generic_jobs_closed(self):
        self.con.execute("INSERT INTO companies(id, name, ats, status) VALUES(2, 'Vodafone Türkiye', 'generic', 'sayfa-var-ilan-yok')")
        self.con.execute("INSERT INTO jobs(company_id, source, ext_id, title, active) VALUES(2, 'genel', 'x', 'Kariyer', 1)")
        path = self.write([{'firma': 'Vodafone', 'eslesme': ['Vodafone Türkiye'], 'ats': 'eightfold', 'slug': 'jobs.vodafone.com',
                            'extra': 'vodafone.com'}])
        self.assertEqual(db.sync_seeds(self.con, path), (0, 1))
        r = self.con.execute('SELECT ats, ats_slug, tr_only FROM companies WHERE id=2').fetchone()
        self.assertEqual(tuple(r), ('eightfold', 'jobs.vodafone.com', 1))
        self.assertEqual(self.con.execute("SELECT active FROM jobs WHERE ext_id='x'").fetchone()[0], 0)

    def test_failed_ats_is_not_relinked(self):  # scan_known 404 sonrasi genel'e dusurdu (ats_extra = eski ATS)
        self.con.execute("INSERT INTO companies(id, name, ats, ats_extra) VALUES(2, 'Uber', 'generic', 'oracle')")
        path = self.write([{'firma': 'Uber', 'ats': 'oracle', 'slug': 'UberCareers', 'extra': 'x.oraclecloud.com'}])
        self.assertEqual(db.sync_seeds(self.con, path), (0, 0))
        self.assertEqual(self.con.execute('SELECT ats FROM companies WHERE id=2').fetchone()[0], 'generic')

    def test_company_with_other_ats_is_left_alone(self):
        self.con.execute("INSERT INTO companies(id, name, ats, ats_slug) VALUES(2, 'Amazon Türkiye', 'custom', 'amazon')")
        path = self.write([{'firma': 'Amazon', 'eslesme': ['Amazon Türkiye'], 'ats': 'workday', 'slug': 'amazon', 'extra': 'wd1|x'}])
        self.assertEqual(db.sync_seeds(self.con, path), (0, 0))
        self.assertEqual(self.con.execute('SELECT ats FROM companies WHERE id=2').fetchone()[0], 'custom')

    def test_repo_seed_file_is_valid(self):
        import json
        with open(db.SEEDS, encoding='utf-8') as f:
            seeds = json.load(f)
        names = [s['firma'] for s in seeds]
        self.assertEqual(len(names), len(set(names)), 'ayni firma iki kez')
        for s in seeds:
            self.assertIn(s['ats'], atsmod.READERS, s)
            self.assertTrue(atsmod.has_reader(s['ats'], s.get('extra')), s)


class Aggregators(UpsertBase):
    """Workable genel aramasi: ilanlar firmalara dagitilir; yeni firma yalnizca teknik ilani varsa eklenir."""

    def setUp(self):
        super().setUp()
        for k in ('new', 'closed', 'ok', 'failed'):
            scanner.STATE[k] = 0
        scanner.STATE['log'].clear()

    def wj(self, jid, title, company, website='', loc='Istanbul, İstanbul, Turkey'):
        return dict(id=jid, title=title, location=loc, team='', url=f'https://jobs.workable.com/view/{jid}', posted=None, remote=False,
                    desc='', company=dict(key=company, name=company, website=website))

    def run_with(self, jobs):
        with mock.patch.object(scanner.agg, 'workable_turkey', return_value=jobs):
            scanner.scan_aggregators(self.con)

    def test_new_tech_company_added_nontech_skipped(self):
        self.run_with([self.wj('1', 'Backend Developer', 'Yeni Teknoloji', 'https://yeni.io'), self.wj('2', 'Chef de Partie', 'Otel A.Ş.')])
        names = {r[0] for r in self.con.execute("SELECT name FROM companies WHERE ats='agg'")}
        self.assertEqual(names, {'Yeni Teknoloji'})
        r = self.con.execute("SELECT * FROM companies WHERE name='Yeni Teknoloji'").fetchone()
        self.assertEqual((r['category'], r['city'], r['tr_only'], r['job_count']), (scanner.AGG_CATEGORY, 'Istanbul', 1, 1))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM jobs WHERE source='workable-tr'").fetchone()[0], 1)

    def test_company_with_own_source_is_skipped(self):
        self.con.execute("UPDATE companies SET name='Vertigo Games', website='https://vertigogames.co', ats='lever', ats_slug='v' WHERE id=1")
        self.con.commit()
        self.run_with([self.wj('1', 'Unity Developer', 'Vertigo', 'https://vertigogames.co/')])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM jobs WHERE source='workable-tr'").fetchone()[0], 0)

    def test_existing_company_without_source_is_matched_by_site(self):
        self.con.execute("UPDATE companies SET website='https://www.huawei.com' WHERE id=1")
        self.con.commit()
        self.run_with([self.wj('1', 'Cloud Data Center Operator', 'Huawei Telekomünikasyon Dış Ticaret Ltd', 'https://www.huawei.com/en/')])
        r = self.con.execute('SELECT ats, ats_slug, job_count FROM companies WHERE id=1').fetchone()
        self.assertEqual(tuple(r), ('agg', 'workable-tr', 1))

    def test_similar_name_is_not_matched(self):  # 'PLANET S.A.' (planet.gr) listedeki 'Digital Planet' (planet.com) degildir
        self.con.execute("UPDATE companies SET name='Digital Planet', website='https://www.planet.com' WHERE id=1")
        self.con.commit()
        self.run_with([self.wj('1', 'Software Engineer', 'PLANET S.A.', 'http://www.planet.gr')])
        self.assertIsNone(self.con.execute('SELECT ats FROM companies WHERE id=1').fetchone()[0])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM companies WHERE name='PLANET S.A.'").fetchone()[0], 1)

    def test_company_gone_from_search_is_closed_but_empty_search_closes_nothing(self):
        self.run_with([self.wj('1', 'Backend Developer', 'Yeni Teknoloji')])
        self.run_with([])  # arama bos/bozuk: dokunulmaz
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM jobs WHERE active=1').fetchone()[0], 1)
        self.run_with([self.wj('9', 'Frontend Developer', 'Baska Firma')])
        self.assertEqual({r[0] for r in self.con.execute('SELECT ext_id FROM jobs WHERE active=1')}, {'9'})

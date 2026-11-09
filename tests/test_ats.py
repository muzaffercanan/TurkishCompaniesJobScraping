"""ATS okuyuculari: Workday ulke filtresi ve konum. Internet yok, sahte Workday yanitlari."""
import json
import unittest
from unittest import mock

from app import ats


def posting(path, loc=None):
    d = {'title': 'Software Engineer', 'externalPath': path}
    if loc is not None:
        d['locationsText'] = loc
    return d


def country_facet(*values, nested=True, param='locationCountry'):
    f = {'facetParameter': param, 'descriptor': 'Ülke', 'values': [{'descriptor': n, 'id': i, 'count': c} for n, i, c in values]}
    return [{'facetParameter': 'jobFamilyGroup', 'values': [{'descriptor': 'R&D', 'id': 'rd', 'count': 3}]},
            {'facetParameter': 'locationMainGroup', 'values': [f]} if nested else f]


class FakeWorkday:
    """Workday CXS ucu: appliedFacets bossa tum ilanlar, doluysa Turkiye ilanlari; toplam yalnizca ilk sayfada."""

    def __init__(self, all_jobs, tr_jobs=(), facets=(), total=None):
        self.all_jobs, self.tr_jobs, self.facets, self.total, self.calls = list(all_jobs), list(tr_jobs), list(facets), total, []

    def __call__(self, url, data=None, method=None, headers=None, **kw):
        body = json.loads(data)
        self.calls.append(body)
        jobs, off = (self.tr_jobs if body['appliedFacets'] else self.all_jobs), body['offset']
        d = {'total': 0, 'jobPostings': jobs[off:off + 20]}
        if off == 0:
            d['total'] = len(jobs) if body['appliedFacets'] or self.total is None else self.total
            if not body['appliedFacets']:
                d['facets'] = self.facets
        return 200, url, json.dumps(d)


class WorkdayRules(unittest.TestCase):
    def test_nested_country_facet(self):
        facets = country_facet(('Fransa', 'fr', 30), ('Türkiye', 'tr', 2))
        self.assertEqual(ats._wd_country(facets), ('locationCountry', ['tr'], 32))

    def test_top_level_country_facet_in_english(self):
        facets = country_facet(('Turkey', 't', 1), ('United States', 'us', 5), nested=False, param='Location_Country')
        self.assertEqual(ats._wd_country(facets), ('Location_Country', ['t'], 6))

    def test_country_facet_without_turkey(self):
        self.assertEqual(ats._wd_country(country_facet(('Fransa', 'fr', 30))), ('locationCountry', [], 30))

    def test_no_country_facet(self):
        self.assertIsNone(ats._wd_country([{'facetParameter': 'jobFamilyGroup', 'values': [{'descriptor': 'R&D', 'id': 'x'}]}]))
        self.assertIsNone(ats._wd_country(None))

    def test_location(self):
        self.assertEqual(ats._wd_location(posting('/job/Austin/X_1', 'Austin, TX, USA')), 'Austin, TX, USA')
        self.assertEqual(ats._wd_location(posting('/job/Bogota-Carrera-7/X_1')), 'Bogota Carrera 7')       # locationsText yok
        self.assertEqual(ats._wd_location(posting('/job/Guyancourt/X_1', '2 Locations')), 'Guyancourt')    # birden fazla konum
        self.assertEqual(ats._wd_location(posting('/job/Istanbul/X_1'), turkey=True), 'Istanbul, Türkiye')
        self.assertEqual(ats._wd_location(posting('/job/X/Y', 'Istanbul, Turkey'), turkey=True), 'Istanbul, Turkey')
        self.assertEqual(ats._wd_location(posting(''), turkey=True), 'Türkiye')


class WorkdayReader(unittest.TestCase):
    def run_reader(self, fake):
        with mock.patch.object(ats, 'fetch', fake), mock.patch.object(ats.time, 'sleep'):
            return ats.workday('acme', 'wd3|Careers')

    def test_turkey_filter_is_applied(self):
        fake = FakeWorkday([posting(f'/job/Paris/J{i}') for i in range(32)], [posting('/job/Istanbul/T1'), posting('/job/Ankara/T2')],
                           country_facet(('Fransa', 'fr', 30), ('Türkiye', 'tr', 2)))
        jobs = self.run_reader(fake)
        self.assertEqual([j['id'] for j in jobs], ['/job/Istanbul/T1', '/job/Ankara/T2'])
        self.assertEqual([j['location'] for j in jobs], ['Istanbul, Türkiye', 'Ankara, Türkiye'])
        self.assertEqual([c['appliedFacets'] for c in fake.calls], [{}, {'locationCountry': ['tr']}])
        self.assertIsInstance(jobs, ats.Jobs)
        self.assertFalse(jobs.confirmed)
        self.assertIn('Turkiye filtresi: 2 / 32', jobs.note)

    def test_filtered_paging(self):
        fake = FakeWorkday([posting('/job/Paris/J')], [posting(f'/job/Istanbul/T{i}') for i in range(45)],
                           country_facet(('Türkiye', 'tr', 45), ('Fransa', 'fr', 1)))
        self.assertEqual(len(self.run_reader(fake)), 45)
        self.assertEqual([c['offset'] for c in fake.calls], [0, 0, 20, 40])

    def test_no_turkey_in_complete_country_facet_is_confirmed_empty(self):
        fake = FakeWorkday([posting(f'/job/Paris/J{i}') for i in range(30)], facets=country_facet(('Fransa', 'fr', 30)))
        jobs = self.run_reader(fake)
        self.assertEqual(list(jobs), [])
        self.assertTrue(jobs.confirmed)
        self.assertIn("Turkiye'de ilani yok", jobs.note)
        self.assertEqual(len(fake.calls), 1)

    def test_nearly_complete_country_facet_without_turkey_is_confirmed_empty(self):  # Samsung: 649 / 658 ilanda ulke var
        fake = FakeWorkday([posting(f'/job/Austin/J{i}') for i in range(100)], facets=country_facet(('United States', 'us', 96)))
        self.assertTrue(self.run_reader(fake).confirmed)

    def test_incomplete_country_facet_reads_everything(self):
        # ulke filtresi ilanlarin yalnizca bir kismini kapsiyor: Turkiye'nin olmadigi kesin degil, tum liste alinir
        fake = FakeWorkday([posting(f'/job/Paris/J{i}') for i in range(30)], facets=country_facet(('Fransa', 'fr', 10)))
        jobs = self.run_reader(fake)
        self.assertEqual(len(jobs), 30)
        self.assertNotIsInstance(jobs, ats.Jobs)
        self.assertEqual(jobs[0]['location'], 'Paris')

    def test_no_country_facet_reads_everything(self):
        jobs = self.run_reader(FakeWorkday([posting('/job/Paris/J1', 'Paris, France')]))
        self.assertEqual([j['location'] for j in jobs], ['Paris, France'])

    def test_empty_filtered_result_is_not_confirmed(self):
        # filtre "Turkiye'de 2 ilan var" diyor ama liste bos: okuyucu/uc nokta bozulmus olabilir, eski ilanlar korunmali
        fake = FakeWorkday([posting('/job/Paris/J1')], [], country_facet(('Türkiye', 'tr', 2), ('Fransa', 'fr', 1)))
        jobs = self.run_reader(fake)
        self.assertEqual(list(jobs), [])
        self.assertFalse(jobs.confirmed)


class RipplingAndCustomDomainAts(unittest.TestCase):
    def test_rippling_reader(self):
        payload = {'items': [
            {'uuid': 'u1', 'name': 'Backend Engineer', 'url': 'https://ats.rippling.com/black-kite/jobs/u1',
             'locations': [{'name': 'Istanbul, Turkey'}], 'department': {'name': 'Engineering'}, 'createdOn': '2026-10-15T10:00:00Z'}
        ], 'totalPages': 1}
        with mock.patch.object(ats, 'fetch_json', return_value=payload):
            jobs = ats.rippling('black-kite')
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['id'], 'u1')
        self.assertEqual(jobs[0]['title'], 'Backend Engineer')
        self.assertEqual(jobs[0]['location'], 'Istanbul, Turkey')
        self.assertEqual(jobs[0]['team'], 'Engineering')
        self.assertEqual(jobs[0]['posted'], '2026-10-15')

    def test_recruitee_custom_domain_detect_and_read(self):
        blob = 'https://careers.obilet.com/\n<script src="https://careers-analytics.recruitee.com/analytics.js"></script><a href="/o/yazilim-uzmani">Job</a>'
        det = ats.detect(blob)
        self.assertEqual(det, ('recruitee', 'obilet', 'careers.obilet.com'))
        with mock.patch.object(ats, 'fetch_json', return_value={'offers': [{'id': 7, 'title': 'Go Developer', 'location': 'Istanbul', 'careers_url': 'https://careers.obilet.com/o/go'}]}) as fj:
            jobs = ats.recruitee('obilet', 'careers.obilet.com')
            fj.assert_called_once_with('https://careers.obilet.com/api/offers/')
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['title'], 'Go Developer')

    def test_successfactors_rmk_custom_domain_detect(self):
        blob = 'https://career.yasar.com.tr/\n<script>var j2w = j2w || {}; j2w.init({ "company" : "Yaşar" });</script><form class="talentCommunitySearch"></form>'
        det = ats.detect(blob)
        self.assertEqual(det, ('successfactors', 'yasar', 'career.yasar.com.tr'))


class NewPlatforms(unittest.TestCase):
    """Cok uluslu firmalarin kariyer platformlari: tespit ve Turkiye filtresi."""

    def test_detect(self):
        cases = {
            'https://careers.dhl.com/global/en/search-results <script src="https://cdn.phenompeople.com/a.js"></script>':
                ('phenom', 'careers.dhl.com', 'en_global'),
            'https://jobs.citi.com/location/x <img src="//tbcdn.talentbrew.com/company/287/cms/a.webp">': ('talentbrew', 'jobs.citi.com', '287'),
            'https://jobs.vodafone.com/careers <script src="https://static.vscdn.net/a.js"></script> /api/pcsx/search?domain=vodafone.com':
                ('eightfold', 'jobs.vodafone.com', 'vodafone.com'),
            'https://kariyer.firma.com/ <link href="https://cdn.talentics.app/x/favicon">': ('talentics', 'kariyer', 'kariyer.firma.com'),
            'https://firma.com/kariyer <a href="https://firma.talentics.app/">Ilanlar</a>': ('talentics', 'firma', None),
            'https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs': ('oracle', 'CX_1001', 'jpmc.fa.oraclecloud.com'),
            'https://eachlabs.ai/careers <a href="https://eachlabs.hrpanda.co/full-stack-engineer">Jobs</a>': ('hrpanda', 'eachlabs', None),
        }
        for blob, want in cases.items():
            self.assertEqual(ats.detect(blob), want, blob)
            self.assertTrue(ats.has_reader(want[0], want[2]), want)

    def test_hrpanda_panel_links_are_not_a_board(self):  # 'Powered by HrPanda' giris baglantilari firma sayfasi degildir
        self.assertIsNone(ats.detect('https://firma.com/ <a href="https://dashboard.hrpanda.co/auth/jwt/login">x</a>'))

    def test_eightfold_drops_fuzzy_non_turkey_matches(self):
        page = {'data': {'count': 2, 'positions': [
            {'id': 1, 'name': 'Backend Engineer', 'locations': ['Budapest, HUN', 'Sincan Ankara, TUR, 06930'], 'positionUrl': '/careers/job/1'},
            {'id': 2, 'name': 'Sales', 'locations': ['Budapest, HUN'], 'standardizedLocations': ['Budapest, HU']}]}}
        with mock.patch.object(ats, 'fetch_json', return_value=page):
            jobs = ats.eightfold('jobs.ornek.com', 'ornek.com')
        self.assertEqual([j['title'] for j in jobs], ['Backend Engineer'])
        self.assertTrue(jobs[0]['location'].startswith('Sincan Ankara'))  # Turkiye konumu basta: bolge Turkiye olur
        self.assertTrue(jobs.confirmed)

    def test_phenom_without_turkey_is_confirmed_empty(self):
        first = {'totalHits': 50, 'data': {'aggregations': [{'field': 'country', 'value': {'Germany': 40, 'Turkey': 0}}]}}
        with mock.patch.object(ats, '_ph_search', return_value=first) as ps:
            jobs = ats.phenom('careers.ornek.com', 'en_global')
        self.assertEqual((list(jobs), jobs.confirmed), ([], True))
        ps.assert_called_once()

    def test_oracle_without_turkey_location_is_confirmed_empty(self):
        with mock.patch.object(ats, 'fetch_json', return_value={'items': [{'Id': '1', 'Level': 3, 'Country': 'United States', 'Name': 'Turkey, TX'}]}):
            jobs = ats.oracle('CX_1', 'x.oraclecloud.com')
        self.assertEqual((list(jobs), jobs.confirmed), ([], True))

    def test_workday_location_facet_filter(self):
        facets = [{'facetParameter': 'locationMainGroup', 'values': [{'facetParameter': 'locations', 'values': [
            {'descriptor': 'Besiktas, Istanbul Turkey', 'id': 'a', 'count': 17}, {'descriptor': 'Madrid, Spain', 'id': 'b', 'count': 30}]}]}]
        self.assertIsNone(ats._wd_country(facets))
        self.assertEqual(ats._wd_places(facets), ('locations', ['a'], 47))


if __name__ == '__main__':
    unittest.main()

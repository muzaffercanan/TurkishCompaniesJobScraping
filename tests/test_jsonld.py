"""schema.org JobPosting (application/ld+json): liste sayfasinda ilan, detay sayfasinda aciklama/tarih/konum. Internet yok."""
import json
import unittest
from unittest import mock

from app import enrich, generic, scanner
from tests.tempdb import TempDb

PAGE = 'https://ornek.com.tr/kariyer'


def ld(*objs, comment=False):
    body = json.dumps(objs[0] if len(objs) == 1 else list(objs), ensure_ascii=False)
    if comment:
        body = f'<!-- {body} -->'
    return f'<html><head><script type="application/ld+json">{body}</script></head><body><p>Kariyer</p></body></html>'


POSTING = {'@context': 'https://schema.org', '@type': 'JobPosting', 'title': 'Backend Developer', 'url': '/kariyer/ilan/42',
           'datePosted': '2026-10-20T09:00:00+03:00', 'description': '&lt;p&gt;En az 2 yıl &lt;b&gt;Python&lt;/b&gt;&lt;/p&gt;',
           'jobLocation': {'@type': 'Place', 'address': {'@type': 'PostalAddress', 'addressLocality': 'Ankara',
                                                         'addressCountry': {'@type': 'Country', 'name': 'TR'}}},
           'occupationalCategory': 'Yazılım'}


class JsonLd(unittest.TestCase):
    def test_single_posting(self):
        (j,) = generic.jsonld_jobs(PAGE, ld(POSTING))
        self.assertEqual((j['title'], j['url'], j['id'], j['posted'], j['location'], j['team']),
                         ('Backend Developer', 'https://ornek.com.tr/kariyer/ilan/42', 'https://ornek.com.tr/kariyer/ilan/42',
                          '2026-10-20', 'Ankara, TR', 'Yazılım'))
        self.assertEqual(j['desc'], 'En az 2 yıl Python')
        self.assertFalse(j['remote'])
        self.assertIsNone(j['detail'])
        self.assertEqual(scanner.region_of(j['location']), 'Türkiye')

    def test_graph_item_list_and_type_list(self):
        page = {'@context': 'https://schema.org', '@graph': [
            {'@type': 'WebPage', 'name': 'Kariyer'},
            {'@type': 'ItemList', 'itemListElement': [
                {'@type': 'ListItem', 'item': dict(POSTING, title='QA Engineer', url='https://ornek.com.tr/ilan/1')},
                {'@type': 'ListItem', 'item': dict(POSTING, **{'@type': ['JobPosting', 'Thing']}, title='Data Analyst',
                                                   url='https://ornek.com.tr/ilan/2')}]}]}
        self.assertEqual([j['title'] for j in generic.jsonld_jobs(PAGE, ld(page))], ['QA Engineer', 'Data Analyst'])

    def test_expired_and_untitled_postings_are_skipped(self):
        jobs = generic.jsonld_jobs(PAGE, ld(dict(POSTING, validThrough='2020-01-01'), dict(POSTING, title='', url='/x'),
                                            dict(POSTING, title='Açık', url='/y', validThrough='2099-12-31')))
        self.assertEqual([j['title'] for j in jobs], ['Açık'])

    def test_remote_and_list_locations(self):
        p = dict(POSTING, jobLocationType='TELECOMMUTE', jobLocation=None,
                 applicantLocationRequirements={'@type': 'Country', 'name': 'Türkiye'})
        (j,) = generic.jsonld_jobs(PAGE, ld(p))
        self.assertEqual((j['remote'], j['location']), (True, 'Türkiye'))
        p = dict(POSTING, jobLocation=[{'address': {'addressLocality': 'İstanbul', 'addressCountry': 'TR'}},
                                       {'address': {'addressLocality': 'İzmir', 'addressCountry': 'TR'}}])
        self.assertEqual(generic.jsonld_jobs(PAGE, ld(p))[0]['location'], 'İstanbul, TR; İzmir, TR')

    def test_postings_without_url_get_stable_ids_and_no_detail(self):
        jobs = generic.jsonld_jobs(PAGE, ld(dict(POSTING, url=None, identifier={'value': 'R-7'}), dict(POSTING, url=None, title='Tester')))
        self.assertEqual([j['id'] for j in jobs], [PAGE + '#R-7', PAGE + '#Tester'])
        self.assertEqual({j['url'] for j in jobs}, {PAGE})
        self.assertEqual({j['detail'] for j in jobs}, {(None, None)})

    def test_bad_or_commented_json(self):
        self.assertEqual(generic.jsonld_jobs(PAGE, '<script type="application/ld+json">{bozuk</script>'), [])
        self.assertEqual(len(generic.jsonld_jobs(PAGE, ld(POSTING, comment=True))), 1)
        self.assertEqual(generic.jsonld_jobs(PAGE, ''), [])

    def test_extract_prefers_structured_data_and_keeps_other_links(self):
        links = [('https://ornek.com.tr/kariyer/ilan/42', 'Backend Developer', ''),
                 ('https://ornek.com.tr/kariyer/ilan/43', 'Frontend Developer', '')]
        jobs = generic.extract(PAGE, links, ld(POSTING))
        self.assertEqual([(j['title'], j['location']) for j in jobs], [('Backend Developer', 'Ankara, TR'), ('Frontend Developer', '')])
        self.assertEqual(generic.extract(PAGE, links), generic._extract_links(PAGE, links))   # html yoksa eski davranis


class DetailPage(unittest.TestCase):
    def test_detail_page_uses_job_posting(self):
        with mock.patch.object(enrich, 'fetch', return_value=(200, 'https://ornek.com.tr/kariyer/ilan/42', ld(POSTING))):
            self.assertEqual(enrich.fetch_detail('page', 'u'), ('En az 2 yıl Python', '2026-10-20', 'Ankara, TR'))


class EnrichLocation(TempDb):
    @staticmethod
    def job(ext, location='', remote=False):
        return dict(id=ext, title='Backend Developer', url=f'https://ornek.com.tr/{ext}', location=location, remote=remote)

    def region(self, ext):
        return tuple(self.con.execute("SELECT location, region FROM jobs WHERE ext_id=?", (ext,)).fetchone())

    def test_location_from_detail_fills_empty_location(self):
        scanner.upsert(self.con, 1, 'genel', [self.job('a'), self.job('b', location='İzmir'), self.job('c', remote=True)])
        with mock.patch.object(enrich, 'fetch_detail', return_value=('metin', None, 'Berlin, DE')), mock.patch.object(enrich, 'pace'):
            scanner.enrich_pending(1)
        self.assertEqual(self.region('a'), ('Berlin, DE', 'Yurt dışı'))
        self.assertEqual(self.region('b'), ('İzmir', 'Türkiye'))          # listedeki konum korunur
        self.assertEqual(self.region('c'), ('Berlin, DE', 'Uzaktan'))     # uzaktan isaretli ilan uzaktan kalir


if __name__ == '__main__':
    unittest.main()

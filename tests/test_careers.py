"""Kariyer sayfasi kesfi: robots.txt engeli ayri bir durum olarak doner (erisilemedi ile karismaz). Internet yok."""
import unittest
from unittest import mock

from app import careers
from app.util import HttpError

ROBOTS = HttpError('robots', 'u', 'robots.txt izin vermiyor')
HOME = ('https://firma.com.tr/', '<html></html>', [('https://firma.com.tr/kariyer', 'Kariyer', '')], [], 'http')


class DiscoverRobots(unittest.TestCase):
    def test_home_page_blocked(self):
        with mock.patch.object(careers, '_page', side_effect=ROBOTS):
            r = careers.discover(dict(website='https://firma.com.tr'))
        self.assertEqual(r['status'], 'robots')

    def test_career_page_blocked(self):
        with mock.patch.object(careers, '_page', side_effect=[HOME, ROBOTS]):
            r = careers.discover(dict(website='https://firma.com.tr'))
        self.assertEqual((r['status'], r['career_url']), ('robots', 'https://firma.com.tr/kariyer'))

    def test_other_errors_stay_unreachable(self):
        with mock.patch.object(careers, '_page', side_effect=HttpError(500, 'u')):
            self.assertEqual(careers.discover(dict(website='https://firma.com.tr'))['status'], 'erisilemedi')


    def test_redirect_only_links_do_not_fetch_external_board(self):
        home = ('https://firma.com.tr/', '<html></html>',
                [('https://www.linkedin.com/company/firma/jobs/', 'Kariyer', 'Açık pozisyonlar')], [], 'http')
        with mock.patch.object(careers, '_page', side_effect=[home, AssertionError('external board should not be fetched')]), \
                mock.patch.object(careers, 'fetch', side_effect=HttpError('timeout', 'u')), \
                mock.patch.object(careers, '_resolves', return_value=False):
            r = careers.discover(dict(website='https://firma.com.tr'))
        self.assertEqual(r['status'], 'yonlendirme')
        self.assertEqual(r['ats_extra'], 'linkedin')

    def test_two_step_sub_listing_discovery(self):
        home = ('https://peak.com/', '<html></html>', [('https://peak.com/jobs', 'Jobs', '')], [], 'browser')
        landing = ('https://peak.com/jobs', '<html></html>', [('https://peak.com/open-positions', 'See All Open Positions', '')], [], 'browser')
        subpage = ('https://peak.com/open-positions', '<html></html>', [
            ('https://peak.com/open-positions/software-engineer', 'Software Engineer', 'Engineering'),
            ('https://peak.com/open-positions/backend-developer', 'Backend Developer', 'Engineering'),
        ], [], 'browser')
        with mock.patch.object(careers, '_page', side_effect=[home, landing, subpage]):
            r = careers.discover(dict(website='https://peak.com'))
        self.assertEqual(r['status'], 'genel')
        self.assertEqual(r['career_url'], 'https://peak.com/open-positions')
        self.assertEqual(len(r['jobs']), 2)


if __name__ == '__main__':
    unittest.main()

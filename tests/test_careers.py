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


if __name__ == '__main__':
    unittest.main()

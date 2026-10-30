"""Ortak HTTP katmani: sertifika dogrulama ve geri dusus, sunucu basina eszamanlilik siniri, robots.txt, kimlik.
Internet yok: urllib.request.urlopen taklit edilir."""
import ssl
import threading
import time
import unittest
import urllib.error
from unittest import mock

from app import util
from app.util import HttpError


class FakeResponse:
    def __init__(self, url, body='ok', status=200):
        self.url, self.body, self.status = url, body, status
        self.headers = mock.Mock(get_content_charset=lambda: 'utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        return self.body.encode()

    def geturl(self):
        return self.url


def cert_error():
    return urllib.error.URLError(ssl.SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate'))


class Base(unittest.TestCase):
    def setUp(self):
        self._insecure = set(util.INSECURE_HOSTS)
        util.INSECURE_HOSTS.clear()
        util._robots.clear()

    def tearDown(self):
        util.INSECURE_HOSTS.clear()
        util.INSECURE_HOSTS.update(self._insecure)
        util._robots.clear()


class Tls(Base):
    def test_certificate_is_verified_first(self):
        with mock.patch('urllib.request.urlopen', return_value=FakeResponse('https://a.com.tr/')) as op:
            self.assertEqual(util.fetch('https://a.com.tr/'), (200, 'https://a.com.tr/', 'ok'))
        self.assertIs(op.call_args.kwargs['context'], util._CTX)
        self.assertEqual(util._CTX.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(util._CTX.check_hostname)

    def test_falls_back_only_for_that_host_on_cert_error(self):
        calls = []

        def op(req, timeout, context):
            calls.append((req.full_url, context))
            if context is util._CTX and 'eksik' in req.full_url:
                raise cert_error()
            return FakeResponse(req.full_url)
        with mock.patch('urllib.request.urlopen', side_effect=op), mock.patch.object(util.time, 'sleep'),                 self.assertLogs('ilan_radari', 'WARNING'):
            self.assertEqual(util.fetch('https://eksik-zincir.com.tr/kariyer', tries=1)[0], 200)   # tek deneme hakkinda bile
            util.fetch('https://eksik-zincir.com.tr/ikinci')
            util.fetch('https://saglam.com.tr/')
        self.assertEqual([c is util._INSECURE_CTX for _, c in calls], [False, True, True, False])
        self.assertEqual(util.INSECURE_HOSTS, {'eksik-zincir.com.tr'})

    def test_other_network_errors_are_not_treated_as_cert_errors(self):
        with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError('baglanti reddedildi')), \
                mock.patch.object(util.time, 'sleep'):
            with self.assertRaises(HttpError):
                util.fetch('https://kapali.com.tr/', tries=2)
        self.assertEqual(util.INSECURE_HOSTS, set())

    def test_user_agent_identifies_the_app(self):
        with mock.patch('urllib.request.urlopen', return_value=FakeResponse('https://a.com/')) as op:
            util.fetch('https://a.com/')
        self.assertIn('IlanRadari/1.0', op.call_args.args[0].get_header('User-agent'))


class HostLimit(Base):
    def run_parallel(self, urls):
        lock, state = threading.Lock(), dict(now=0, peak={})

        def op(req, timeout, context):
            host = util.host_of(req.full_url)
            with lock:
                state['now'] += 1
                state['peak'][host] = max(state['peak'].get(host, 0), sum(1 for h in running if h == host) + 1)
                running.append(host)
            time.sleep(0.05)
            with lock:
                running.remove(host)
            return FakeResponse(req.full_url)
        running = []
        with mock.patch('urllib.request.urlopen', side_effect=op):
            ts = [threading.Thread(target=util.fetch, args=(u,)) for u in urls]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        return state['peak']

    def test_same_host_is_limited(self):
        peak = self.run_parallel(['https://api.lever.co/v0/postings/a'] * 8 + ['https://boards-api.greenhouse.io/x'] * 8)
        self.assertEqual(peak, {'api.lever.co': util.HOST_LIMIT, 'boards-api.greenhouse.io': util.HOST_LIMIT})


class Robots(Base):
    ROBOTS = 'User-agent: Googlebot\nAllow: /\n\nUser-agent: *\nDisallow: /\n'

    def robots(self, text=None, error=None):
        def f(url, **kw):
            self.assertTrue(url.endswith('/robots.txt'))
            if error:
                raise HttpError(error, url)
            return 200, url, text
        return mock.patch.object(util, 'fetch', side_effect=f)

    def test_disallow_all_but_search_engines(self):
        with self.robots(self.ROBOTS) as f:
            self.assertFalse(util.robots_ok('https://kariyer.ornek.com.tr/ilanlar'))
            self.assertFalse(util.robots_ok('https://kariyer.ornek.com.tr/baska'))
        self.assertEqual(f.call_count, 1)  # site basina bir kez okunur

    def test_partial_rules(self):
        with self.robots('User-agent: *\nDisallow: /api/\n'):
            self.assertTrue(util.robots_ok('https://ornek.com/kariyer'))
            self.assertFalse(util.robots_ok('https://ornek.com/api/jobs'))

    def test_rules_for_our_agent(self):
        with self.robots('User-agent: IlanRadari\nDisallow: /\n\nUser-agent: *\nAllow: /\n'):
            self.assertFalse(util.robots_ok('https://ornek.com/kariyer'))

    def test_longest_match_wins(self):  # RFC 9309: 'Disallow: /' olsa da daha uzun 'Allow' kurali kazanir (Eightfold siteleri)
        with self.robots('User-agent: *\nDisallow: /\nAllow: /$\nAllow: /api/pcsx\n'):
            self.assertTrue(util.robots_ok('https://jobs.ornek.com/api/pcsx/search?domain=ornek.com&start=10'))
            self.assertTrue(util.robots_ok('https://jobs.ornek.com/'))
            self.assertFalse(util.robots_ok('https://jobs.ornek.com/api/other'))

    def test_wildcards_and_tie(self):
        r = util.Robots('User-agent: *\nDisallow: /*.pdf$\nDisallow: /kariyer\nAllow: /kariyer\nDisallow: /a*/b\n')
        self.assertFalse(r.allowed('https://x.com/dosya.pdf'))
        self.assertTrue(r.allowed('https://x.com/dosya.pdf?v=1'))
        self.assertTrue(r.allowed('https://x.com/kariyer/ilan'))  # esit uzunlukta Allow kazanir
        self.assertFalse(r.allowed('https://x.com/abc/b/c'))
        self.assertTrue(util.Robots('User-agent: *\nDisallow:\n').allowed('https://x.com/a'))

    def test_missing_or_unreadable_robots_allows(self):
        for err in (404, 'URLError'):
            util._robots.clear()
            with self.robots(error=err):
                self.assertTrue(util.robots_ok('https://ornek.com/kariyer'), err)

    def test_fetch_with_robots_raises_without_requesting(self):
        util._robots['https://ornek.com'] = util.Robots(self.ROBOTS)
        with mock.patch('urllib.request.urlopen') as op:
            with self.assertRaises(HttpError) as cm:
                util.fetch('https://ornek.com/kariyer', robots=True)
            self.assertEqual(cm.exception.status, 'robots')
            op.assert_not_called()
            op.return_value = FakeResponse('https://ornek.com/kariyer')
            self.assertEqual(util.fetch('https://ornek.com/kariyer')[0], 200)   # API cagrilari (robots=False) etkilenmez


class Browser(Base):
    def test_render_respects_robots(self):
        from app import browser
        with mock.patch.object(util, 'robots_ok', return_value=False), mock.patch.object(browser, '_render') as r:
            with self.assertRaises(HttpError) as cm:
                browser.render('https://ornek.com/kariyer')
        self.assertEqual(cm.exception.status, 'robots')
        r.assert_not_called()

    def test_render_retries_insecure_on_cert_error(self):
        from app import browser
        seen = []

        def r(url, wait, timeout, insecure=False):
            seen.append(insecure)
            if not insecure:
                raise RuntimeError('page.goto: net::ERR_CERT_AUTHORITY_INVALID at https://eksik.com.tr/')
            return url, '', [], []
        with mock.patch.object(util, 'robots_ok', return_value=True), mock.patch.object(browser, '_render', side_effect=r),                 self.assertLogs('ilan_radari', 'WARNING'):
            browser.render('https://eksik.com.tr/')
            browser.render('https://eksik.com.tr/kariyer')
        self.assertEqual(seen, [False, True, True])
        self.assertIn('eksik.com.tr', util.INSECURE_HOSTS)


class FileLog(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self._handlers = list(util.log.handlers)

    def tearDown(self):
        import shutil
        for h in util.log.handlers[:]:
            if h not in self._handlers:
                util.log.removeHandler(h)
                h.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scan_log_and_tracebacks_are_written_to_file(self):
        import os
        from app import scanner
        path = os.path.join(self.tmp, 'logs', 'tarama.log')
        util.setup_file_log(path)
        util.setup_file_log(path)  # ikinci cagri ikinci bir dosya isleyicisi eklemez
        self.assertEqual(sum(1 for h in util.log.handlers if h not in self._handlers), 1)
        scanner._log('Firma: 3 yeni ilan (lever)')
        try:
            raise ValueError('bozuk yanit')
        except ValueError:
            util.log.warning('Firma: lever okunamadi', exc_info=True)
        for h in util.log.handlers:
            h.flush()
        with open(path, encoding='utf-8') as f:
            body = f.read()
        self.assertIn('Firma: 3 yeni ilan (lever)', body)
        self.assertIn('Traceback', body)
        self.assertIn('ValueError: bozuk yanit', body)


if __name__ == '__main__':
    unittest.main()

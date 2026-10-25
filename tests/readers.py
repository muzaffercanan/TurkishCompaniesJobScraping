"""Test edilen okuyucular ve kayit/oynatma altyapisi.
Kayit (canli siteden, internet gerekir):   python -m tests.record
Test (cevrimdisi, kaydedilmis yanitlarla): python -m unittest tests.test_readers -v"""
import json
import os
import time

from app import ats, custom, util

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')

# (test adi, tur, okuyucu, argumanlar)
CASES = [
    ('lever_trendyol', 'ats', 'lever', ('trendyol',)),
    ('greenhouse_goodjobgames', 'ats', 'greenhouse', ('goodjobgames',)),
    ('ashby_biggergames', 'ats', 'ashby', ('biggergames',)),
    ('recruitee_mikroyazilim', 'ats', 'recruitee', ('mikroyazilim',)),
    ('breezy_socradar', 'ats', 'breezy', ('socradar',)),
    ('manatal_netgsm', 'ats', 'manatal', ('netgsm',)),
    ('jazzhr_modanisa', 'ats', 'jazzhr', ('modanisa',)),
    ('workday_oyakrenault', 'ats', 'workday', None),   # slug/extra veritabanindan; hesapta Turkiye ilani yok (kesin bos liste)
    ('workday_accenture', 'ats', 'workday', ('accenture', 'wd103|AccentureCareers')),  # Turkiye ulke filtresi uygulanir
    ('teamtailor_pulsetto', 'ats', 'teamtailor', None),
    ('personio_kunbus', 'ats', 'personio', None),
    ('custom_turkcell', 'custom', 'turkcell', ()),
    ('custom_garanti', 'custom', 'garanti', ()),
    ('custom_havelsan', 'custom', 'havelsan', ()),
    ('custom_turktelekom', 'custom', 'turktelekom', ()),
    ('custom_amazon', 'custom', 'amazon', ()),
    ('custom_roketsan', 'custom', 'roketsan', ()),
    ('custom_baykar', 'custom', 'baykar', ()),
]
DB_ARGS = {'workday_oyakrenault': 'Oyak Renault', 'teamtailor_pulsetto': 'Pulsetto', 'personio_kunbus': 'Kunbus'}


def resolve_args(name, args):
    if args is not None:
        return args
    from app import db
    r = db.connect().execute('SELECT ats_slug, ats_extra FROM companies WHERE name=?', (DB_ARGS[name],)).fetchone()
    return (r['ats_slug'], r['ats_extra'])


def run_case(kind, reader, args):
    if kind == 'custom':
        return custom.REGISTRY[reader]()
    return ats.fetch_jobs(reader, *args)


def _key(url, data=None, method=None):
    return f"{method or ('POST' if data is not None else 'GET')} {url} {data.decode('utf-8', 'replace') if isinstance(data, bytes) else data or ''}"


class Recorder:
    """util.fetch ve custom._open cagrilarini kaydeder ya da kayittan oynatir."""

    def __init__(self, path, mode):
        self.path, self.mode = path, mode
        if mode == 'replay':
            with open(path, encoding='utf-8') as f:
                self.calls = json.load(f)['calls']
        else:
            self.calls = {}
        self._orig = (util.fetch, ats.fetch, custom._open, time.sleep)

    def fetch(self, url, data=None, method=None, headers=None, **kw):
        k = _key(url, data, method)
        if self.mode == 'replay':
            if k not in self.calls:
                raise util.HttpError('kayitta-yok', url)
            c = self.calls[k]
            return c['status'], c['final'], c['text']
        st, final, txt = self._orig[0](url, data=data, method=method, headers=headers, **kw)
        self.calls[k] = dict(status=st, final=final, text=txt)
        return st, final, txt

    def open_(self, url, data=None, method=None, headers=None, tries=2):
        return self.fetch(url, data=data, method=method, headers=headers)[2]

    def __enter__(self):
        util.fetch = ats.fetch = self.fetch
        custom._open = self.open_
        if self.mode == 'replay':  # kayittan oynatirken nezaket beklemelerine gerek yok
            time.sleep = lambda *_a, **_k: None
        return self

    def __exit__(self, *exc):
        util.fetch, ats.fetch, custom._open, time.sleep = self._orig

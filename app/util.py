"""Ortak yardimcilar: HTTP (tek katman: uygulamadaki tum istekler buradan gecer), Turkce normallestirme, firma adi anahtari."""
import html
import logging
import os
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
import urllib.robotparser

log = logging.getLogger('ilan_radari')
log.addHandler(logging.NullHandler())  # dosyaya yazim setup_file_log ile acilir (uygulama baslarken; testlerde degil)


def setup_file_log(path):
    """Gunlugu dosyaya da yaz: taramalar, hatalarin tam izi (traceback), sertifika geri dususleri. Uygulama kapaninca kaybolmaz.
    1 MB'lik 5 dosya tutulur, eskiler kendiliginden silinir. Ikinci cagri bir sey yapmaz."""
    from logging.handlers import RotatingFileHandler
    if any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    h = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding='utf-8')
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s'))
    log.addHandler(h)
    log.setLevel(logging.INFO)

# Sertifika her zaman once dogrulanir. Dogrulanamayan sitelerde (cogu zaman ara sertifikasini gondermeyen sunucular)
# yalnizca o site icin dogrulamasiz baglanilir ve bu kayda gecer.
_CTX = ssl.create_default_context()
_INSECURE_CTX = ssl.create_default_context()
_INSECURE_CTX.check_hostname = False
_INSECURE_CTX.verify_mode = ssl.CERT_NONE
INSECURE_HOSTS = set()

# Kimligimizi saklamayiz: tarayici uyumlu UA + uygulama adi (robots.txt kurallarinda 'IlanRadari' olarak eslesir)
ROBOTS_AGENT = 'IlanRadari'
BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              f'(KHTML, like Gecko) Chrome/124.0 Safari/537.36 {ROBOTS_AGENT}/1.0')
HEADERS = {'User-Agent': BROWSER_UA, 'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
           'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8'}

HOST_LIMIT = 2  # ayni sunucuya ayni anda en fazla bu kadar istek (or. api.lever.co'yu onlarca firma paylasiyor)
_slots, _slots_lock = {}, threading.Lock()
_robots, _robots_lock = {}, threading.Lock()


class HttpError(Exception):
    def __init__(self, status, url, msg=''):
        super().__init__(f'{status} {url} {msg}'.strip())
        self.status = status


def _slot(host):
    with _slots_lock:
        s = _slots.get(host)
        if s is None:
            s = _slots[host] = threading.BoundedSemaphore(HOST_LIMIT)
        return s


def _cert_error(e):
    r = getattr(e, 'reason', e)
    return isinstance(r, ssl.SSLCertVerificationError) or 'CERTIFICATE_VERIFY_FAILED' in str(r)


def mark_insecure(host):
    """Sertifikasi dogrulanamayan site: bundan sonra bu sitede dogrulama yapilmaz (tarayici da ayni listeyi kullanir)."""
    if host not in INSECURE_HOSTS:
        INSECURE_HOSTS.add(host)
        log.warning('sertifika dogrulanamadi, bu sitede dogrulamasiz baglanilacak: %s', host)


def robots_ok(url):
    """robots.txt bu adrese izin veriyor mu? Site basina bir kez okunur. robots.txt yoksa ya da okunamazsa izinli sayilir."""
    p = urllib.parse.urlparse(url)
    root = f'{p.scheme}://{p.netloc}'
    with _robots_lock:
        rp = _robots.get(root)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            _, _, t = fetch(root + '/robots.txt', timeout=8, tries=1, max_bytes=500_000)
            rp.parse(t.splitlines())
        except HttpError:
            rp.parse([])  # kural yok: her yere izin
        with _robots_lock:
            _robots[root] = rp
    return rp.can_fetch(ROBOTS_AGENT, url)


def fetch(url, data=None, method=None, headers=None, timeout=20, tries=2, max_bytes=3_000_000, robots=False):
    """(status, final_url, text) dondurur; ag hatasinda HttpError firlatir.
    429/503 (cok fazla istek / gecici) yanitlarinda Retry-After suresine uyup en fazla 3 kez daha dener.
    robots=True: site taramasi (kariyer/program/ilan sayfalari, firma sitelerindeki uc noktalar); robots.txt izin vermezse
    HttpError('robots'). Belgelenmis ATS API'leri robots=False ile cagrilir."""
    if robots and not robots_ok(url):
        raise HttpError('robots', url, 'robots.txt izin vermiyor')
    host = host_of(url)
    last, i, throttled = None, 0, 0
    while i < tries:
        ctx = _INSECURE_CTX if host in INSECURE_HOSTS else _CTX
        try:
            req = urllib.request.Request(url, data=data, method=method, headers={**HEADERS, **(headers or {})})
            with _slot(host), urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read(max_bytes)
                cs = r.headers.get_content_charset() or 'utf-8'
                return r.status, r.geturl(), raw.decode(cs, 'replace')
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and throttled < 3:
                throttled += 1
                ra = e.headers.get('Retry-After') if e.headers else None
                wait = min(float(ra), 30.0) if ra and ra.replace('.', '', 1).isdigit() else 3.0 * throttled
                time.sleep(wait)
                continue  # bekleme denemesi 'tries' hakkindan dusmez
            if e.code in (404, 403, 401, 410, 429):
                raise HttpError(e.code, url)
            last = e
        except Exception as e:  # noqa: BLE001 - ag hatalari cesitli
            if ctx is _CTX and _cert_error(e):
                mark_insecure(host)
                continue  # dogrulamasiz tekrar dene (deneme hakkindan dusmez)
            last = e
        i += 1
        if i < tries:
            time.sleep(1.0)
    raise HttpError(getattr(last, 'code', type(last).__name__), url, str(last)[:80])


def fetch_json(url, **kw):
    import json
    _, _, t = fetch(url, headers={'Accept': 'application/json', **kw.pop('headers', {})}, **kw)
    return json.loads(t)


def text(s):
    """HTML parcasini duz metne cevir."""
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


_TR = str.maketrans({'İ': 'i', 'I': 'i', 'ı': 'i', 'ş': 's', 'Ş': 's', 'ğ': 'g', 'Ğ': 'g', 'ü': 'u', 'Ü': 'u',
                     'ö': 'o', 'Ö': 'o', 'ç': 'c', 'Ç': 'c', 'â': 'a', 'î': 'i', 'û': 'u'})


def norm(s):
    return (s or '').translate(_TR).lower()


def tokens(s):
    return [t for t in re.split(r'[^a-z0-9]+', norm(s)) if t]


LEGAL = {'limited', 'ltd', 'sti', 'sirketi', 'sirket', 'anonim', 'as', 'a', 's', 'san', 'sanayi', 've', 'tic', 'ticaret',
         'inc', 'co', 'llc', 'gmbh', 'bv', 'tld'}
GENERIC = LEGAL | {'yazilim', 'bilisim', 'teknoloji', 'teknolojileri', 'teknolojisi', 'bilgi', 'sistemleri', 'sistem', 'danismanlik',
                   'hizmetleri', 'muhendislik', 'elektronik', 'savunma', 'grup', 'group', 'holding', 'turkiye', 'turkey', 'tr',
                   'software', 'technology', 'technologies', 'tech', 'bilgisayar', 'otomasyon', 'dijital', 'digital', 'arge',
                   'ar', 'ge', 'gelistirme', 'uretim', 'pazarlama', 'egitim', 'com', 'net', 'cozumleri', 'solutions', 'systems',
                   'iletisim', 'haberlesme', 'arastirma', 'ic', 'dis', 'ithalat', 'ihracat', 'insaat', 'enerji', 'medikal',
                   'saglik', 'labs', 'lab', 'studio', 'studyo', 'games', 'game', 'oyun', 'ai', 'io', 'sube', 'subesi', 'ankara',
                   'istanbul', 'merkez', 'merkezi'}


def core_tokens(name):
    """Firmayi ayirt eden kelimeler (genel/hukuki ekler cikarilmis)."""
    name = re.sub(r'\(.*?\)', ' ', name or '')
    return [t for t in tokens(name) if t not in GENERIC and len(t) > 1]


def name_key(name):
    c = core_tokens(name)
    return '_'.join(c[:3]) if c else '_'.join(tokens(name)[:3])


def host_of(url):
    h = urllib.parse.urlparse(url if '://' in (url or '') else 'http://' + (url or '')).netloc.lower()
    return h[4:] if h.startswith('www.') else h


def absolute(base, href):
    return urllib.parse.urljoin(base, href)

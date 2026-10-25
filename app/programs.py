"""Genc yetenek / staj / yeni mezun PROGRAM sayfalari (or. https://kariyerim.turkcell.com.tr/genc-yetenek).
Bu sayfalar tek tek ilan degil, programin kendisini anlatir; basvuru donemleri acilip kapanir.
discover(company) -> [program]  : firmanin kendi sitesinde/kariyer sayfasinda program sayfalarini bulur ve DOGRULAR
read(url, company)  -> program  : sayfayi okuyup basvuru durumu, son basvuru tarihi ve icerigi cikarir
Dogruluk icin kurallar (yanlis sayfa eklememek, eksik eklemekten onemli):
  - sayfa firmanin kendi alan adinda (ya da alt alan adinda) olmali
  - adres ya da baglanti metni program kelimesi icermeli; haber/blog/basin/KVKK/giris sayfalari elenir
  - sayfa acilmali (200), 404/bulunamadi sayfasi olmamali, metinde program kelimeleri en az 3 kez gecmeli"""
import datetime as dt
import hashlib
import re
import urllib.parse

from . import browser, generic
from .util import HttpError, fetch, host_of, norm, text

STRONG = re.compile(r'genc[- ]?yetenek|gncytnk|young[- ]?talent|yeni[- ]?mezun|new[- ]?grad|graduate|\bstaj|internship|\binterns?\b|'
                    r'kampus|campus|management[- ]?trainee|yetenek[- ]?program|talent[- ]?program|early[- ]?careers?|\bstudents?\b|'
                    r'ogrenci|genc[- ]?profesyonel|future[- ]?talent|gelecegin yetenek|genc[- ]?kusak|lift[- ]?up', re.I)
EXCLUDE = re.compile(r'blog|haber|news|duyuru|basin|press|etkinlik|events?/|kvkk|cerez|cookie|privacy|gizlilik|aydinlatma|login|'
                     r'giris|uye-ol|signup|register|sikca|sik-sorulan|frequently-asked|faq|sss|iletisim|contact|'
                     r'/job/|/jobs?/\d|/ilan/\d|/position/|/requisition|\.(pdf|png|jpe?g|docx?|mp4)(\?|$)|'
                     r'youtube|linkedin|instagram|facebook|twitter|wa\.me|mailto:|tel:', re.I)
WEAK = re.compile(r'\bstudents?\b|ogrenci|kampus|campus', re.I)  # tek basina yeterli degil: kariyer baglaminda olmali
CAREER_CTX = re.compile(r'kariyer|career|insan-?kaynak|\bik\b|\bhr\b|jobs|is-?ilan|bize-?katil|aramiza-?katil|join-?us|yetenek|talent', re.I)
NEGATIVE = re.compile(r'kampanya|campaign|\bkart|card|indirim|tarife|hizmetler|urun|product|bankacilik|banking|kredi|loan|paket|magaza|'
                      r'shop|sigorta|insurance|faturali|faturaya|hesap|axess|bonus|cihaz|telefon|tablet|abonelik|odeme', re.I)
NON_TR = re.compile(r'\bu\.?s\.?\b|\busa\b|united states|canada|\buk\b|united kingdom|india|germany|deutschland|poland|'
                    r'mexico|brazil|china|japan|singapore|ireland|netherlands|spain|france|italy|sweden|australia|\bemea\b', re.I)
# Konum: NON_TR'deki ulkeler basliktaysa sayfa zaten elenir; bunlar baslik/adreste gecerse sayfa o ulkenin programidir
FOREIGN = re.compile(r'\b(finland|suomi|sweden|norway|denmark|estonia|hungary|romania|portugal|belgium|austria|switzerland|czechia|'
                     r'czech republic|israel|egypt|morocco|south africa|korea|taiwan|vietnam|philippines|malaysia|indonesia|argentina|'
                     r'chile|colombia|new zealand)\b')
TR_PAGE = re.compile(r'turkiye|turkey|turkish|istanbul|ankara|izmir|kocaeli|gebze|bursa|antalya|eskisehir|konya|adana|kayseri|'
                     r'sakarya|odtu|bilkent|teknokent|teknopark')
TR_LANG = re.compile(r'\b(ve|bir|icin|ile|olarak|olan|basvuru|programi|ogrenci|mezun)\b')  # sik Turkce kelimeler: sayfa Turkce mi
TR_PATH = re.compile(r'(^|/)tr([-_][a-z]{2})?(/|$)')
GLOBAL_NAME = re.compile(r'\b(turkiye|turkey)\b')  # 'Ericsson Turkiye', 'Boeing Turkey': cok uluslu sirketin Turkiye kolu
NOT_FOUND = re.compile(r'sayfa bulunamad|page not found|404 not found|aradiginiz sayfa|sayfa mevcut degil|content not ?found', re.I)
COMMON_PATHS = ('/genc-yetenek', '/staj', '/yeni-mezun', '/kariyer/genc-yetenek', '/kariyer/staj', '/kampus', '/campus',
                '/students', '/internship', '/early-careers')
OPEN_RX = re.compile(r'basvurular (acildi|basladi|devam ediyor|acik|alinmaya basla)|hemen basvur|basvuru yap|basvurunu yap|simdi basvur|'
                     r'apply now|apply today|applications (are )?open|son basvuru tarihi|basvuru icin tikla', re.I)
CLOSED_RX = re.compile(r'basvurular(imiz)? (kapandi|sona erdi|tamamlandi|kapanmistir|sona ermistir)|basvuru (donemi|suresi) (sona erdi|bitti|kapandi)|'
                       r'applications (are )?(now )?closed|yakinda (acilacak|basliyor|baslayacak)|coming soon|basvurulara kapali|ilan kapandi', re.I)
MONTHS = {'ocak': 1, 'subat': 2, 'mart': 3, 'nisan': 4, 'mayis': 5, 'haziran': 6, 'temmuz': 7, 'agustos': 8, 'eylul': 9, 'ekim': 10,
          'kasim': 11, 'aralik': 12, 'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6, 'july': 7, 'august': 8,
          'september': 9, 'october': 10, 'november': 11, 'december': 12}


def base_domain(h):
    """kariyerim.turkcell.com.tr -> turkcell.com.tr ; careers.example.com -> example.com"""
    parts = (h or '').lower().split('.')
    if len(parts) >= 3 and parts[-2] in ('com', 'net', 'org', 'gov', 'edu', 'gen', 'web', 'av', 'bel', 'k12', 'co') and len(parts[-1]) == 2:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])


def clean_url(u):
    """#parca ve utm_/izleme parametreleri olmadan adres"""
    p = urllib.parse.urlparse(u.split('#')[0])
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not re.match(r'utm_|gclid|fbclid|ref$|source$', k, re.I)]
    return urllib.parse.urlunparse(p._replace(query=urllib.parse.urlencode(q)))


def _english_copy(p, found):
    """/en/ sayfasi ve ayni sitede Turkce bir program zaten bulunduysa: ayni programin Ingilizce kopyasidir"""
    path = urllib.parse.urlparse(p['url']).path.lower()
    if not re.search(r'(^|/)en(-[a-z]{2})?(/|$)', path):
        return False
    host = host_of(p['url'])
    return any(host_of(f['url']) == host and not re.search(r'(^|/)en(-[a-z]{2})?(/|$)', urllib.parse.urlparse(f['url']).path.lower())
               for f in found)


def _candidate(href, label, company, career_ctx):
    """Baglanti program adayi mi? Puan (0 = degil)"""
    if not href or not href.startswith('http') or EXCLUDE.search(href):
        return 0
    path = urllib.parse.urlparse(href).path
    if not path.strip('/'):
        return 0
    npath, nlabel = norm(urllib.parse.unquote(path)), norm(label or '')
    if _negative(npath) or not _same_company(href, company):
        return 0
    strong_any = STRONG.search(WEAK.sub(' ', npath + ' ' + nlabel))
    if not (career_ctx or CAREER_CTX.search(norm(href)) or strong_any):
        return 0  # ana sayfadaki 'ogrenci' baglantisi: kariyer baglami yok
    if not (STRONG.search(npath) or STRONG.search(nlabel)):
        return 0
    return (2 if STRONG.search(npath) else 0) + (1 if STRONG.search(nlabel) else 0) + (1 if career_ctx else 0)


def _same_company(url, company):
    bases = {base_domain(host_of(company.get(k) or '')) for k in ('website', 'career_url') if company.get(k)}
    bases.discard('')
    return base_domain(host_of(url)) in bases


def _page_text(html):
    return text(re.sub(r'<(script|style|noscript)\b.*?</\1>', ' ', html, flags=re.S | re.I))


def _negative(npath):
    """Urun/kampanya sayfasi mi? Adreste kariyer baglami varsa hayir (or. /yapi-kredi-hakkinda/insan-kaynaklari/...)"""
    return bool(NEGATIVE.search(npath)) and not CAREER_CTX.search(npath)


def _title(html, url):
    """h1, <title> ve adresin son parcasi arasindan program kelimesi gecen ilki (yoksa ilk gecerli olan)"""
    opts = []
    for rx in (r'<h1[^>]*>(.*?)</h1>', r'<title[^>]*>(.*?)</title>'):
        m = re.search(rx, html, flags=re.S | re.I)
        if m:
            t = re.split(r'\s+[|\-–—]\s+', text(m.group(1)))[0].strip()
            if 3 <= len(t) <= 120:
                opts.append(t)
    slug = urllib.parse.unquote(urllib.parse.urlparse(url).path.strip('/').split('/')[-1])
    slug = re.sub(r'\.(aspx?|html?|php)$', '', slug)
    slug = re.sub(r'[-_]+', ' ', re.sub(r'[-_]?\d+$', '', slug)).strip()
    if slug:
        opts.append(slug[:1].upper() + slug[1:])
    for t in opts:
        if STRONG.search(norm(t)):
            return t
    return opts[0] if opts else 'Program'


def _kind(head, body=''):
    """Baslik/adres belirleyici; belirsizse sayfa metni"""
    for s in (head, body):
        n = norm(s)
        grad = re.search(r'yeni mezun|graduate|new grad|management trainee|mt program|genc profesyonel', n)
        intern = re.search(r'\bstaj|intern|ogrenci|\bstudents?\b', n)
        if intern and not grad:
            return 'Staj'
        if grad and not intern:
            return 'Junior / Yeni mezun'
    return 'Junior / Yeni mezun'


def _location(url, title, nbody, company):
    """Program sayfasinin konumu (sabit 'Türkiye' yazilmaz):
      baslik/adres baska bir ulkeyi anlatiyorsa o ulke ('Finland');
      .tr alan adi, /tr/ sayfasi, Turkiye/sehir adi gecmesi ya da Turkce metin -> 'Türkiye';
      cok uluslu sirketin (kategori 'Global ...' ya da adinda Turkiye gecen) Turkiye'den soz etmeyen genel sayfasi ->
      'Küresel program sayfası' (bolgesi Yurt disi olur, 'bana uygun'a girmez);
      hicbiri degilse bos (Belirtilmemis: Ingilizce sayfasi olan yerli firmalar, or. Dream Games)."""
    p = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(p.path).lower()
    m = FOREIGN.search(norm(title + ' ' + path).replace('-', ' '))
    if m:
        return m.group(1).title()
    words = len(nbody.split())
    if host_of(url).endswith('.tr') or TR_PATH.search(path) or TR_PAGE.search(norm(title) + ' ' + nbody) or \
            (words >= 50 and len(TR_LANG.findall(nbody)) >= 0.03 * words):
        return 'Türkiye'
    if GLOBAL_NAME.search(norm(company.get('name'))) or norm(company.get('category')).startswith('global'):
        return 'Küresel program sayfası'
    return ''


def _deadline(t):
    """'son basvuru' ifadesine yakin ilk tarih (YYYY-MM-DD) ya da None"""
    n = norm(t)
    for m in re.finditer(r'son basvuru|deadline|basvurular[^.]{0,40}kadar|basvuru tarihi', n):
        win = n[m.start(): m.start() + 160]
        d = re.search(r'(\d{1,2})[./](\d{1,2})[./](20\d\d)', win)
        if d:
            return f'{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}'
        d = re.search(r'(\d{1,2})\s+(' + '|'.join(MONTHS) + r')\s+(20\d\d)', win)
        if d:
            return f'{d.group(3)}-{MONTHS[d.group(2)]:02d}-{int(d.group(1)):02d}'
    return None


def _fetch_page(url, min_links=5):
    """(final, html, links[(href, text, ctx, sig)]) ; duz HTTP, gerekirse gercek tarayici
    (sayfa JS ile doluyorsa ya da baglanti sayisi min_links altindaysa)"""
    try:
        st, final, html = fetch(url, timeout=15, tries=1, robots=True)
        if st == 200 and not generic.looks_js_only(html):
            links = generic.links_from_html(final, html)
            if len(links) >= min_links:
                return final, html, links
    except HttpError as e:
        if e.status in (404, 410, 'robots'):
            raise
    final, html, links, _frames = browser.render(url)
    return final, html, [tuple(x) for x in links]


def read(url, company):
    """Program sayfasini oku ve dogrula. Gecerli degilse None. robots.txt izin vermiyorsa HttpError('robots') firlatir
    (gecici hatadan farkli: sayfa artik okunmayacak, cagiran ilanini kapatir)."""
    try:
        final, html, links = _fetch_page(url, min_links=0)
    except HttpError as e:
        if e.status == 'robots':
            raise
        return None
    except Exception:  # noqa: BLE001
        return None
    path = norm(urllib.parse.unquote(urllib.parse.urlparse(final).path))
    if not _same_company(final, company) or EXCLUDE.search(path) or _negative(path):
        return None
    body = _page_text(html)
    nbody = norm(body)
    if NOT_FOUND.search(nbody[:3000]) or len(nbody) < 300:
        return None
    hits = len(STRONG.findall(nbody))
    if hits < 3:
        return None
    title = _title(html, final)
    if re.match(r'(404|hata|error|not found|sayfa bulunamad)', norm(title)):
        return None
    head = norm(title + ' ' + path)
    if NON_TR.search(head.replace('-', ' ')):
        return None  # baska bir ulkenin programi (or. 'Internships U.S. and Canada')
    if not STRONG.search(head):  # basligi ya da adresi program anlatmiyorsa genel kariyer sayfasidir
        return None
    if WEAK.search(head) and not STRONG.search(WEAK.sub(' ', head)) and not CAREER_CTX.search(norm(final)):
        return None  # 'ogrenci/kampus' sayfasi ama kariyer baglami yok (urun/kampanya olabilir)
    if not re.search(r'basvur|apply|kariyer|career|program', nbody):
        return None
    closed, opened = bool(CLOSED_RX.search(nbody)), bool(OPEN_RX.search(nbody))
    status = 'Başvuru kapalı' if closed and not opened else 'Başvuru açık' if opened else 'Durum belirsiz'
    deadline = _deadline(body)
    if deadline and deadline < dt.date.today().isoformat() and status == 'Başvuru açık':
        status = 'Durum belirsiz'  # son basvuru tarihi gecmis ama sayfada "basvur" yaziyor
    return dict(url=clean_url(final), title=title, kind=_kind(title + ' ' + path, body[:2000]), status=status,
                deadline=deadline, location=_location(final, title, nbody, company), text=body[:6000], hash=hashlib.sha1(nbody[:20000].encode()).hexdigest()[:16], hits=hits, links=links)


def job_hosts(company):
    """Firmanin ilanlarinin bulundugu, firmaya ait alan adlari (or. kariyerim.turkcell.com.tr): kariyer adresi kayitli olmayan
    ozel okuyuculu firmalar icin baslangic noktasi"""
    from . import db
    if not company.get('id'):
        return []
    rows = db.tl().execute('SELECT url FROM jobs WHERE company_id=? AND active=1 AND url LIKE "http%" LIMIT 200', (company['id'],)).fetchall()
    count = {}
    for r in rows:
        p = urllib.parse.urlparse(r['url'])
        if _same_company(r['url'], company):
            root = f'{p.scheme}://{p.netloc}/'
            count[root] = count.get(root, 0) + 1
    return sorted(count, key=lambda k: -count[k])[:2]


def _probe_ok(root):
    """Yaygin adres denemesine deger mi? Olmayan bir adrese 404 donmeli (her adrese 200 donen ya da engelleyen siteler atlanir)."""
    try:
        st, final, _ = fetch(root + '/ilan-radari-olmayan-sayfa-7d3f', timeout=5, tries=1, max_bytes=200_000, robots=True)
        return False  # 200: her adres acilir, deneme anlamsiz
    except HttpError as e:
        return e.status in (404, 410)


def discover(company, max_programs=4):
    """Firmanin program sayfalarini bul. Dogrulanmis programlarin listesi."""
    starts = [(u, True) for u in [company.get('career_url')] + job_hosts(company) if u]
    if company.get('website'):
        starts.append((company['website'], False))
    seen_start, cands = set(), {}
    for su, career_ctx in starts:
        if su.rstrip('/') in seen_start:
            continue
        seen_start.add(su.rstrip('/'))
        try:
            final, html, links = _fetch_page(su)
        except Exception:  # noqa: BLE001
            continue
        if STRONG.search(norm(urllib.parse.unquote(urllib.parse.urlparse(final).path))):
            cands[final.split('#')[0].rstrip('/')] = 4  # kayitli kariyer adresi zaten bir program sayfasi
        for item in links:
            score = _candidate(item[0], item[1], company, career_ctx)
            if score:
                key = item[0].split('#')[0].rstrip('/')
                cands[key] = max(cands.get(key, 0), score)
    if not cands:  # baglanti yoksa yaygin adresleri dene (kariyer alt alan adi ve ana site)
        hosts = []
        for su, _ in starts:
            p = urllib.parse.urlparse(su)
            root = f'{p.scheme or "https"}://{p.netloc}'
            if root not in hosts:
                hosts.append(root)
        for root in hosts[:2]:
            if not _probe_ok(root):
                continue
            errors = 0
            for path in COMMON_PATHS:
                try:
                    st, f2, h2 = fetch(root + path, timeout=5, tries=1, max_bytes=500_000, robots=True)
                except HttpError as e:
                    if e.status not in (404, 410):
                        errors += 1
                        if errors >= 2 or not isinstance(e.status, int):
                            break  # baglanti sorunu / bot korumasi: bu sitede diger yollari deneme
                    continue
                if st == 200 and urllib.parse.urlparse(f2).path.rstrip('/') == path.rstrip('/'):
                    cands[f2.split('#')[0].rstrip('/')] = 1
    found, seen_hash = [], set()
    queue = sorted(cands, key=lambda u: (bool(re.search(r'/en(-[a-z]{2})?/', u.lower())), -cands[u], len(u)))[:10]
    checked = set()
    while queue and len(checked) < 14 and len(found) < max_programs:
        url = queue.pop(0)
        if url in checked:
            continue
        checked.add(url)
        try:
            p = read(url, company)
        except HttpError:
            continue  # robots.txt izin vermiyor
        if not p:
            continue
        sub = p.pop('links')
        if p['hash'] in seen_hash or p['url'].rstrip('/') in {f['url'].rstrip('/') for f in found}:
            continue
        seen_hash.add(p['hash'])
        found.append(p)
        for item in sub:  # program sayfasindan bagli alt programlar (or. genc-yetenek -> gncytnkstaj)
            key = item[0].split('#')[0].rstrip('/')
            if key not in checked and key not in queue and _candidate(item[0], item[1], company, True) >= 3:
                queue.append(key)
    tr = [f for f in found if not _english_copy(f, found)]
    return tr

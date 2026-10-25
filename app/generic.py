"""ATS'i olmayan (ya da okuyucusu olmayan) kariyer sayfalarindan ilan cikarma.
Once sayfadaki yapilandirilmis veri (schema.org JobPosting, application/ld+json), sonra kural tabanli: ilan adresi kaliplari
+ is unvani kelimeleri. LLM kullanilmaz."""
import datetime as dt
import html as html_lib
import json
import re
import urllib.parse

from .util import host_of, norm, text

JOB_PATH = re.compile(r'/(job|jobs|ilan|ilanlar|is-ilani|is-ilanlari|position|positions|pozisyon|pozisyonlar|acik-pozisyon(lar)?|'
                      r'vacanc(y|ies)|opening|openings|career|careers|kariyer|kariyer-firsatlari|o|j|posting|postings|requisition|'
                      r'job-detail|jobdetail|is-ilan|isilani|'
                      # ekli klasor adlari: pozisyon-detayi, ilan-detay, job-details, staj-detayi, kariyer-detay, position-detail ...
                      r'[a-z]*-?(?:job|ilan|pozisyon|position|vacancy|staj|internship|kariyer|career)-?(?:detay[a-z]*|detail[s]?|ilani|view)'
                      r')/[^/?#]{4,}', re.I)
# Firmanin KENDI kariyer sayfasinda listelenen, LinkedIn / Kariyer.net'teki ilan sayfasina giden baglantilar.
# Bu siteleri taramiyoruz; yalnizca firmanin kendi sayfasinda gorunen ilan basligini ve baglantisini aliyoruz.
BOARD_JOB_LINK = re.compile(r'linkedin\.com/jobs/view/\d+|kariyer\.net/is-ilani/[a-z0-9-]+|youthall\.com/[a-z]{2}/[^/]+/[^/?#]+_\d+', re.I)
JOB_FILE = re.compile(r'\.job$|jobid=|job_id=|ilanid=|ilan_id=|positionid=|reqid=|jobreq', re.I)
ATS_HOST = re.compile(r'lever\.co|greenhouse\.io|ashbyhq|workable|smartrecruiters|recruitee|personio|bamboohr|breezy\.hr|pinpointhq|'
                      r'teamtailor|myworkdayjobs|successfactors|comeet|icims|jobvite|join\.com|homerun|careers-page|zohorecruit|'
                      r'freshteam|applytojob|oraclecloud|kolayik|peoplise', re.I)
# Ingilizce unvanlar tam kelime; Turkce unvanlar ek alabilir ama "Sorumluluk", "Liderlik" gibi kavramlar haric
TITLE_WORDS = re.compile(
    r'\b(engineer|developer|specialist|analyst|designer|manager|lead|intern|internship|trainee|assistant|consultant|'
    r'technician|architect|scientist|administrator|representative|coordinator|director|head of|expert|associate|officer|'
    r'programmer|tester|devops|sre|full.?stack|back.?end|front.?end|product owner|scrum master|operator|accountant|recruiter|'
    r'editor|writer|executive|agent|partner manager|researcher|tech lead|team lead)s?\b|'
    r'mühendis(i|leri)?\b|muhendis(i|leri)?\b|geliştirici(si|leri)?\b|gelistirici(si|leri)?\b|uzman(ı|i|lari|ları)?\b|'
    r'uzman yardımcısı|analist(i|leri)?\b|tasarımcı(sı)?\b|tasarimci(si)?\b|yönetici(si)?\b|yonetici(si)?\b|müdür(ü)?\b|mudur(u)?\b|'
    r'sorumlusu\b|stajyer\b|staj programı|asistan(ı|i)?\b|danışman(ı|i)?\b|danisman(i)?\b|teknisyen(i)?\b|tekniker(i)?\b|'
    r'mimar(ı|i)?\b|yetkili(si)?\b|temsilci(si)?\b|koordinatör(ü)?\b|koordinator(u)?\b|direktör(ü)?\b|direktor(u)?\b|'
    r'programcı(sı)?\b|programci(si)?\b|operatör(ü)?\b|operator(u)?\b|muhasebe (uzmanı|elemanı|sorumlusu)|editör(ü)?\b|'
    r'şefi?\b|sefi?\b|yazılımcı|araştırmacı|araştırma görevlisi|yeni mezun|management trainee|\bmt\b', re.I)
NAV = re.compile(r'^(ana ?sayfa|home|hakkımızda|about|iletişim|contact|blog|haberler|news|kvkk|gizlilik|privacy|çerez|cookie|giriş|'
                 r'login|sign in|kayıt|register|üye ol|tümü|all|daha fazla|more|devamı|read more|ürünler|products|çözümler|solutions|'
                 r'kariyer|careers?|jobs?|iş ilanları|açık pozisyonlar|open positions|tüm ilanlar|all jobs|see all.*|view all.*|'
                 r'bize katıl|join us|insan kaynakları|genel başvuru|general application|başvuru formu|faq|sss|english|türkçe|en|tr)$', re.I)
LISTING_TITLE = re.compile(r'ilanlar|ilanları|ilanlari|pozisyonlar|positions$|jobs$|kariyer fırsat|career opportunit|tüm |all |'
                           r'^video\b|\d{1,2}:\d{2}$|internships$|programs$|programlar|^apply now|^learn more|^read more|^watch', re.I)
GENERIC_LINK = re.compile(r'^(detay(lar)?|incele|başvur|basvur|hemen başvur|apply( now)?|view( job)?|see details|details|devam|'
                          r'more|daha fazla|ilanı gör|ilani gor|görüntüle|goruntule|>|→|»)$', re.I)
SKIP_HREF = re.compile(r'^(mailto:|tel:|javascript:|#)|facebook|twitter|instagram|linkedin|youtube|x\.com/|wa\.me|kariyer\.net|'
                       r'\.(pdf|jpg|png|docx?)$', re.I)


def _clean_title(t):
    t = re.sub(r'\s+\d+\s*(gün|saat|dakika|hafta|ay|day|hour|minute|week|month)s?\s*(önce|ago).*$', '', t, flags=re.I)
    t = re.sub(r'\s*(başvur|basvur|apply( now)?|detay(lar)?|incele|yeni|new)\s*$', '', t, flags=re.I)
    t = re.sub(r'\s*\d{1,2}[./]\d{1,2}[./]\d{2,4}.*$', '', t)  # sondaki tarih
    return t.strip(' -|·•:')


_LD = re.compile(r'<script\b[^>]*type=["\']?application/ld\+json["\']?[^>]*>(.*?)</script>', re.S | re.I)


def _ld_nodes(d):
    """JSON-LD agacindaki tum nesneler (@graph, ItemList > ListItem > item, ic ice listeler)."""
    if isinstance(d, list):
        for x in d:
            yield from _ld_nodes(x)
    elif isinstance(d, dict):
        yield d
        for k in ('@graph', 'itemListElement', 'item', 'mainEntity'):
            if k in d:
                yield from _ld_nodes(d[k])


def _ld_str(v):
    if isinstance(v, dict):
        v = v.get('name') or v.get('value') or v.get('@id') or ''
    if isinstance(v, list):
        return ', '.join(filter(None, (_ld_str(x) for x in v)))
    return text(str(v)) if v is not None else ''


def _ld_location(p):
    """jobLocation (Place / PostalAddress, tek ya da liste) -> 'Sehir, Ulke' ; uzaktan ilanlarda basvuru ulkesi."""
    places = p.get('jobLocation') or []
    out = []
    for pl in places if isinstance(places, list) else [places]:
        addr = pl.get('address', pl) if isinstance(pl, dict) else pl
        if isinstance(addr, dict):
            parts = [_ld_str(addr.get(k)) for k in ('addressLocality', 'addressRegion', 'addressCountry')]
            s = ', '.join(dict.fromkeys(x for x in parts if x))
        else:
            s = _ld_str(addr)
        if s and s not in out:
            out.append(s)
    if not out and p.get('applicantLocationRequirements'):
        out.append(_ld_str(p['applicantLocationRequirements']))
    return '; '.join(out)[:200]


def jsonld_jobs(page_url, html):
    """Sayfadaki schema.org JobPosting kayitlari. Google'da ilan olarak gorunmek isteyen siteler koyar: baslik, konum,
    yayin tarihi ve aciklama yapilandirilmis gelir. Son basvuru tarihi gecmis ilanlar alinmaz.
    Dondurur: [{id,title,location,team,url,posted,remote,desc}]"""
    out, seen, today = [], set(), dt.date.today().isoformat()
    for m in _LD.finditer(html or ''):
        raw = re.sub(r'^\s*(<!--|<!\[CDATA\[)|(-->|\]\]>)\s*$', '', m.group(1).strip())
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for p in _ld_nodes(data):
            types = p.get('@type')
            if 'JobPosting' not in (types if isinstance(types, list) else [types]):
                continue
            title = _ld_str(p.get('title') or p.get('name'))[:140]
            valid = str(p.get('validThrough') or '')[:10]
            if not title or (re.match(r'\d{4}-\d{2}-\d{2}$', valid) and valid < today):
                continue
            url = urllib.parse.urljoin(page_url, str(p.get('url') or p.get('sameAs') or '')) if (p.get('url') or p.get('sameAs')) else ''
            key = (url or f'{page_url.split("#")[0]}#{_ld_str(p.get("identifier")) or title}').rstrip('/')
            if key in seen:
                continue
            seen.add(key)
            posted = str(p.get('datePosted') or '')[:10]
            out.append(dict(id=key, title=title, location=_ld_location(p), team=_ld_str(p.get('occupationalCategory'))[:100],
                            url=url or page_url, posted=posted if re.match(r'\d{4}-\d{2}-\d{2}$', posted) else None,
                            remote=str(p.get('jobLocationType') or '').upper() == 'TELECOMMUTE',
                            desc=text(html_lib.unescape(str(p.get('description') or ''))),
                            detail=None if url else (None, None)))  # kendi adresi yoksa liste sayfasi detay diye cekilmesin
    return out


def extract(page_url, links, html=''):
    """links: [(href, link_text, nearby_heading[, container_sig])] -> [{id,title,location,team,url,posted,remote}]
    Once sayfadaki JobPosting kayitlari (html verildiyse; konum/tarih/aciklama ile). Sonra iki yol: (1) ilan adresi kalibi +
    unvan kelimesi; (2) "liste kumesi": ayni kapsayicida yan yana duran, cogu unvan kelimesi tasiyan >=2 baglanti (adresleri
    ilan kalibina uymasa da). Tek basina duran urun/haber baglantilari elenir. Ayni adres iki yoldan gelirse JobPosting kalir."""
    ld = jsonld_jobs(page_url, html)
    ld_keys = {j['id'].rstrip('/') for j in ld} | {j['url'].rstrip('/') for j in ld if j['url'] != page_url}
    return ld + [j for j in _extract_links(page_url, links) if j['id'].rstrip('/') not in ld_keys]


def _extract_links(page_url, links):
    base = host_of(page_url)
    page_path = urllib.parse.urlparse(page_url).path.rstrip('/')
    seen, out = set(), []
    groups = {}  # kapsayici imzasi -> [(key, title, href, word_hit)]
    for item in links:
        href, t, ctx = item[0], item[1], item[2]
        sig = item[3] if len(item) > 3 else ''
        if not href:
            continue
        board_link = bool(BOARD_JOB_LINK.search(href))
        if not board_link and SKIP_HREF.search(href):
            continue
        href = href.split('#')[0]
        u = urllib.parse.urlparse(href)
        h = host_of(href)
        if not (board_link or h == base or h.endswith('.' + base) or base.endswith('.' + h) or ATS_HOST.search(h)):
            continue
        if u.path.rstrip('/') == page_path and not u.query:
            continue
        title = text(t)
        if not title or GENERIC_LINK.match(title) or len(title) < 4:
            title = text(ctx)
        title = _clean_title(title)
        if not title or len(title) < 4 or len(title) > 140 or NAV.match(title):
            continue
        path_hit = bool(board_link or JOB_PATH.search(u.path) or JOB_FILE.search(href) or (ATS_HOST.search(h) and len(u.path) > 3))
        word_hit = bool(TITLE_WORDS.search(title)) and not LISTING_TITLE.search(title)
        if board_link:  # dis ilan sitesi linki: basliktaki sehir/tarih eklerini at, id'yi sorgusuz adres yap
            href = href.split('?')[0]
        key = href.rstrip('/')
        if sig:
            groups.setdefault(sig, []).append((key, title, href, word_hit))
        # (1) ilan adresi kalibi + unvan kelimesi
        if word_hit and path_hit and key not in seen:
            seen.add(key)
            out.append(dict(id=key, title=title, location='', team='', url=href, posted=None, remote=False))
    # (2) liste kumesi
    for sig, items in groups.items():
        uniq = {k: (ti, hr, w) for k, ti, hr, w in items}
        titled = [k for k, (ti, hr, w) in uniq.items() if w]
        if len(titled) >= 2 and len(titled) >= 0.6 * len(uniq) and len(uniq) <= 150:
            for k in titled:
                if k not in seen:
                    ti, hr, _ = uniq[k]
                    seen.add(k)
                    out.append(dict(id=k, title=ti, location='', team='', url=hr, posted=None, remote=False))
    # cok fazla "ilan" cikiyorsa (or. haber listesi) ve ilan adresi az ise guvensiz say
    if len(out) > 8:
        titled = sum(1 for j in out if JOB_PATH.search(urllib.parse.urlparse(j['url']).path))
        if titled < len(out) * 0.3 and len(out) > 40:
            return []
    return out


def links_from_html(page_url, html):
    """Statik HTML'den [(href, text, '')] cikar."""
    out = []
    for m in re.finditer(r'<a\b[^>]{0,2000}?href=["\']?([^"\' >]{1,2000})["\']?[^>]{0,2000}>(.{0,3000}?)</a>', html, flags=re.S | re.I):
        out.append((urllib.parse.urljoin(page_url, html_lib.unescape(m.group(1)).strip()), text(m.group(2))[:200], ''))
    return out


def looks_js_only(html):
    """Sayfa icerigi JS ile mi doluyor? (az metin + SPA kokleri)"""
    body = norm(text(re.sub(r'<script.*?</script>|<style.*?</style>', ' ', html, flags=re.S | re.I)))
    return len(body) < 1500 or bool(re.search(r'id="(root|app|__next|__nuxt)"|ng-version|data-reactroot', html))

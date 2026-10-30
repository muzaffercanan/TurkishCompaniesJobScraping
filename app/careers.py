"""Firma icin kariyer sayfasini bul, ATS'i tespit et.
discover(company) -> dict(career_url, ats, ats_slug, ats_extra, status, status_note, jobs)
Durumlar: ats | genel | sayfa-var-ilan-yok | yonlendirme | kariyer-yok | site-yok | erisilemedi"""
import re
import socket
import urllib.parse

from . import ats as atsmod
from . import browser, generic
from .util import HttpError, fetch, host_of, text

CAREER_RX = re.compile(r'kariyer|career|jobs?\b|/jobs|is-ilan|iş ilan|açık pozisyon|acik-pozisyon|open positions|insan kaynak|'
                       r'insan-kaynak|human resources|join[- ]?us|bize katıl|ekibimize katıl|work[- ]with[- ]us|hiring|vacanc|we.?re hiring',
                       re.I)
BAD_RX = re.compile(r'facebook|twitter|instagram|youtube|x\.com/|wa\.me|mailto:|tel:|\.pdf$|blog|haber|news|kvkk|privacy|cookie|'
                    r'/404\b|checkloading|/(kategori|category|urun|urunler|product|products|cozum|cozumler|cozumlerimiz|solutions|shop|magaza|oyun|duyuru|duyurular|basin|press)(-|$|/)', re.I)
SUB_LIST_RX = re.compile(r'open-?positions|acik-?pozisyon|is-?ilan|tum-?ilan|we-?are-?hiring|kariyer-?firsat|job-?openings|all-?jobs', re.I)
COMMON_PATHS = ('/kariyer', '/careers', '/tr/kariyer', '/insan-kaynaklari', '/acik-pozisyonlar', '/jobs')


def _resolves(host):
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def _score(href, label):
    """Kariyer baglantisi adayini puanla (yuksek iyi)."""
    s = 0
    if atsmod.detect(href):
        s += 100
    path = urllib.parse.urlparse(href).path.lower()
    host = host_of(href)
    if re.search(r'acik-pozisyon|open-positions|jobs|is-ilan|kariyer-firsat|positions', path):
        s += 40
    if host.startswith(('kariyer.', 'career', 'jobs.', 'ik.')):
        s += 35
    if re.search(r'kariyer|career', path):
        s += 30
    if re.search(r'açık pozisyon|open positions|iş ilan|jobs|ilanlar', label, re.I):
        s += 20
    if re.search(r'insan-kaynak|human', path):
        s += 10
    return s - len(path) / 100


def _page(url, force_browser=False):
    """Sayfayi once duz HTTP ile, gerekirse gercek tarayici ile al. (final, html, links, frames, via)"""
    if not force_browser:
        try:
            st, final, html = fetch(url, timeout=10, tries=1, robots=True)
            links = generic.links_from_html(final, html)
            if not generic.looks_js_only(html) and len(links) > 5:
                return final, html, links, [], 'http'
        except HttpError:
            pass
    final, html, links, frames = browser.render(url)
    return final, html, [tuple(x) for x in links], frames, 'browser'


def _blob(final, html, links, frames):
    return ' '.join([final, html[:400000], ' '.join(l[0] for l in links), ' '.join(frames)])


def discover(c):
    res = dict(career_url=None, ats=None, ats_slug=None, ats_extra=None, status=None, status_note='', jobs=None)
    site = c['website']
    if not site:
        res.update(status='site-yok', status_note='web sitesi bilinmiyor')
        return res
    try:
        final, html, links, frames, via = _page(site)
    except Exception as e:  # noqa: BLE001
        if getattr(e, 'status', None) == 'robots':
            res.update(status='robots', status_note='robots.txt izin vermiyor: site taranmiyor')
        else:
            res.update(status='erisilemedi', status_note=f'ana sayfa acilamadi: {str(e)[:80]}')
        return res
    base = host_of(final)
    det = atsmod.detect(_blob(final, html, links, frames))
    if det and atsmod.has_reader(det[0], det[2]):
        res.update(ats=det[0], ats_slug=det[1], ats_extra=det[2], status='ats', status_note='ana sayfada ATS baglantisi')
        return res
    # kariyer baglantisi adaylari
    cands, redirect_det = {}, None
    for href, label, *_ in links:
        if not href.startswith('http') or BAD_RX.search(href):
            continue
        if CAREER_RX.search(href) or CAREER_RX.search(label or ''):
            h = host_of(href)
            dl = atsmod.detect(href)
            if dl and dl[0] in atsmod.REDIRECT_ONLY and not (h == base or h.endswith('.' + base) or base.endswith('.' + h)):
                redirect_det = redirect_det or dl
                continue
            if h == base or h.endswith('.' + base) or base.endswith('.' + h) or dl:
                cands[href.split('#')[0]] = max(cands.get(href.split('#')[0], -1e9), _score(href, label or ''))
    order = sorted(cands, key=lambda u: -cands[u])[:2]
    if not order:  # yaygin adresleri dene
        root = f'{urllib.parse.urlparse(final).scheme}://{urllib.parse.urlparse(final).netloc}'
        for p in COMMON_PATHS:
            try:
                st, f2, h2 = fetch(root + p, timeout=6, tries=1, max_bytes=300_000, robots=True)
                if st == 200 and CAREER_RX.search(text(h2[:50000])) and host_of(f2) == base and urllib.parse.urlparse(f2).path.strip('/'):
                    order = [f2]
                    break
            except HttpError as e:
                if not isinstance(e.status, int):  # zaman asimi / baglanti hatasi: diger yollari denemenin anlami yok
                    break
        if not order and via == 'browser':  # site duz istekleri engelliyor: en yaygin iki adresi tarayiciyla dene
            for p in ('/kariyer', '/careers'):
                try:
                    f2, h2, l2, fr2 = browser.render(root + p)
                    if host_of(f2) == base and urllib.parse.urlparse(f2).path.strip('/') and CAREER_RX.search(text(h2[:80000]))                             and not re.search(r'404|bulunamad|not found', text(h2[:3000]), re.I):
                        order = [f2]
                        break
                except Exception:  # noqa: BLE001
                    continue
        if not order:
            for sub in ('kariyer', 'careers', 'jobs'):
                if not _resolves(f'{sub}.{base}'):
                    continue
                try:
                    st, f2, h2 = fetch(f'https://{sub}.{base}', timeout=8, tries=1, max_bytes=300_000, robots=True)
                    if st == 200:
                        order = [f2]
                        break
                except HttpError:
                    continue
    if not order:
        if redirect_det:
            res.update(career_url=final, ats='generic', ats_extra=redirect_det[0], status='yonlendirme',
                       status_note=f'ilanlari {redirect_det[0]} uzerinde yayinliyor ({redirect_det[1]})')
            return res
        mail = re.search(r'mailto:([A-Za-z0-9._%+-]*(?:ik|hr|kariyer|career|insan|cv|jobs|basvuru)[A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+)', html, re.I)
        res.update(status='kariyer-yok', status_note=('yalnizca e-posta: ' + mail.group(1)) if mail else 'kariyer sayfasi bulunamadi')
        return res
    redirect_note = f'ilanlari {redirect_det[0]} uzerinde yayinliyor ({redirect_det[1]})' if redirect_det else None
    robots_blocked, opened = False, False
    for cu in order:
        try:
            f2, h2, l2, fr2, via2 = _page(cu)
            opened = True
        except Exception as e:  # noqa: BLE001
            robots_blocked = robots_blocked or getattr(e, 'status', None) == 'robots'
            res.update(career_url=cu, status='erisilemedi', status_note=f'kariyer sayfasi acilamadi: {str(e)[:60]}')
            continue
        det = atsmod.detect(_blob(f2, h2, l2, fr2))
        if det and atsmod.has_reader(det[0], det[2]):
            res.update(career_url=f2, ats=det[0], ats_slug=det[1], ats_extra=det[2], status='ats', status_note=f'{det[0]} tespit edildi')
            return res
        jobs = generic.extract(f2, l2, h2)
        if via2 == 'http':  # ATS baglantilari ve ilan listeleri cogu zaman JS ile yuklenir: gercek tarayicida da bak
            try:
                f2, h2, l2, fr2, via2 = _page(cu, force_browser=True)
                det = atsmod.detect(_blob(f2, h2, l2, fr2))
                if det and atsmod.has_reader(det[0], det[2]):
                    res.update(career_url=f2, ats=det[0], ats_slug=det[1], ats_extra=det[2], status='ats', status_note=f'{det[0]} tespit edildi')
                    return res
                jobs2 = generic.extract(f2, l2, h2)
                if len(jobs2) >= len(jobs):
                    jobs = jobs2
            except Exception:  # noqa: BLE001
                pass
        if jobs:
            note = f'genel ayristirici: {len(jobs)} ilan'
            if det:
                note += f' ({det[0]} kullaniyor, okuyucusu yok)'
            res.update(career_url=f2, ats='generic', ats_extra=det[0] if det else None, status='genel', status_note=note, jobs=jobs)
            return res
        if len(order) < 4:  # kariyer tanitim sayfasindan asil ilan listesi alt sayfasina gecis (or. /jobs -> /open-positions)
            subs = {}
            for shref, slabel, *_ in l2:
                sh = shref.split('#')[0]
                if not sh.startswith('http') or sh in order or sh == f2.split('#')[0] or BAD_RX.search(sh):
                    continue
                shost = host_of(sh)
                if not (shost == base or shost.endswith('.' + base) or base.endswith('.' + shost)):
                    continue
                if SUB_LIST_RX.search(sh) or SUB_LIST_RX.search(slabel or '') or (shost != host_of(f2) and shost.startswith(('kariyer.', 'career.', 'jobs.'))):
                    subs[sh] = max(subs.get(sh, -1e9), _score(sh, slabel or ''))
            if subs:
                order.append(max(subs, key=subs.get))
        if det and det[0] in atsmod.REDIRECT_ONLY:
            redirect_note = f'ilanlari {det[0]} uzerinde yayinliyor ({det[1]})'
        res.update(career_url=f2, ats='generic', ats_extra=det[0] if det else (redirect_det[0] if redirect_det else None))
    if redirect_note:
        res.update(status='yonlendirme', status_note=redirect_note)
    elif robots_blocked and not opened:
        res.update(status='robots', status_note='robots.txt izin vermiyor: kariyer sayfasi taranmiyor')
    else:
        res.update(status='sayfa-var-ilan-yok', status_note='kariyer sayfasi var, ilan listesi bulunamadi')
    return res

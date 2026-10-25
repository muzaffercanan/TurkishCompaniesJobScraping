"""Gercek tarayici (Playwright/Chromium) ile sayfa acma. Her is parcacigi kendi tarayicisini kullanir
(Playwright sync API is parcaciklari arasinda paylasilamaz)."""
import re
import threading

from . import util
from .util import BROWSER_UA, HttpError, host_of

_local = threading.local()
_CERT_RX = re.compile(r'ERR_CERT_')  # Chromium sertifika hatalari (ERR_CERT_AUTHORITY_INVALID, ERR_CERT_DATE_INVALID ...)

# Sayfadaki her baglanti icin: [href, baglanti metni, yakindaki baslik metni]
LINKS_JS = """() => {
  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const t = (a.innerText || a.textContent || '').trim().replace(/\\s+/g, ' ');
    let ctx = '', p = a;
    for (let i = 0; i < 4 && p; i++) {
      p = p.parentElement;
      if (!p) break;
      const h = p.querySelector('h1,h2,h3,h4,h5,[class*=title],[class*=Title],[class*=name],[class*=position]');
      if (h && h !== a) { ctx = (h.innerText || '').trim().replace(/\\s+/g, ' '); break; }
    }
    const sig = (e) => e ? (e.tagName + '.' + (e.className && e.className.baseVal === undefined ? String(e.className) : '').trim().split(/\\s+/)[0]) : '';
    const p1 = a.parentElement, p2 = p1 && p1.parentElement, p3 = p2 && p2.parentElement;
    out.push([a.href, t.slice(0, 200), ctx.slice(0, 200), [sig(p1), sig(p2), sig(p3)].join('>')]);
  }
  return out;
}"""


def _browser(insecure=False):
    """Bu is parcaciginin tarayici baglami. Sertifika dogrulanir; dogrulanamayan siteler icin ayri bir baglam acilir."""
    if getattr(_local, 'browser', None) is None:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        _local.pw, _local.browser, _local.ctx, _local.ictx = pw, pw.chromium.launch(headless=True), None, None
    attr = 'ictx' if insecure else 'ctx'
    ctx = getattr(_local, attr)
    if ctx is None:
        ctx = _local.browser.new_context(user_agent=BROWSER_UA, locale='tr-TR', ignore_https_errors=insecure)
        ctx.route('**/*', lambda r: r.abort() if r.request.resource_type in ('image', 'media', 'font') else r.continue_())
        setattr(_local, attr, ctx)
    return ctx


def render(url, wait_ms=1200, timeout_ms=20000):
    """Sayfayi gercek tarayicida ac. (final_url, html, links, frame_urls) dondurur.
    robots.txt izin vermezse HttpError('robots'). Sertifika hatasinda site dogrulamasiz listeye alinip yeniden denenir;
    zaman asiminda bir kez daha, iki kat sureyle denenir (yavas kurumsal siteler)."""
    if not util.robots_ok(url):
        raise HttpError('robots', url, 'robots.txt izin vermiyor')
    host = host_of(url)
    insecure = host in util.INSECURE_HOSTS
    try:
        return _render(url, wait_ms, timeout_ms, insecure)
    except Exception as e:  # noqa: BLE001
        if not insecure and _CERT_RX.search(str(e)):
            util.mark_insecure(host)
            return _render(url, wait_ms, timeout_ms, True)
        if 'Timeout' not in str(e):
            raise
        return _render(url, wait_ms * 2, timeout_ms * 2, insecure)


def _render(url, wait_ms, timeout_ms, insecure=False):
    ctx = _browser(insecure)
    page = ctx.new_page()
    try:
        page.goto(url, timeout=timeout_ms, wait_until='domcontentloaded')
        try:
            page.wait_for_load_state('networkidle', timeout=4000)
        except Exception:  # noqa: BLE001 - surekli istek yapan sayfalarda networkidle hic gelmeyebilir
            pass
        page.wait_for_timeout(wait_ms)
        html = page.content()
        links = page.evaluate(LINKS_JS)
        frames = [f.url for f in page.frames if f.url and f.url != 'about:blank']
        return page.url, html, links, frames
    finally:
        page.close()


def close_local():
    """Bu is parcaciginin tarayicisini kapat (Playwright nesneleri yalnizca olusturuldugu is parcaciginda kapatilabilir)."""
    b = getattr(_local, 'browser', None)
    if b is None:
        return
    try:
        b.close()
        _local.pw.stop()
    except Exception:  # noqa: BLE001
        pass
    _local.browser = _local.pw = _local.ctx = _local.ictx = None

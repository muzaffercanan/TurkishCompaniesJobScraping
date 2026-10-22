"""Gercek tarayici (Playwright/Chromium) ile sayfa acma. Her is parcacigi kendi tarayicisini kullanir
(Playwright sync API is parcaciklari arasinda paylasilamaz)."""
import threading

from .util import BROWSER_UA

_local = threading.local()

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


def _browser():
    b = getattr(_local, 'browser', None)
    if b is None:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=BROWSER_UA, locale='tr-TR', ignore_https_errors=True)
        ctx.route('**/*', lambda r: r.abort() if r.request.resource_type in ('image', 'media', 'font') else r.continue_())
        _local.pw, _local.browser, _local.ctx = pw, b, ctx
    return _local.ctx


def render(url, wait_ms=1200, timeout_ms=20000):
    """Sayfayi gercek tarayicida ac. (final_url, html, links, frame_urls) dondurur.
    Zaman asiminda bir kez daha, iki kat sureyle denenir (yavas kurumsal siteler)."""
    try:
        return _render(url, wait_ms, timeout_ms)
    except Exception as e:  # noqa: BLE001
        if 'Timeout' not in str(e):
            raise
        return _render(url, wait_ms * 2, timeout_ms * 2)


def _render(url, wait_ms, timeout_ms):
    ctx = _browser()
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
    _local.browser = _local.pw = _local.ctx = None

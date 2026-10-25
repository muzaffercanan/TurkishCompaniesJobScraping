"""Kucuk HTML agaci (yalnizca standart kutuphane: html.parser, ek kurulum yok). Okuyucular regex yerine etiket / sinif /
nitelikle arar: site sinif sirasini, bosluklari, nitelik tirnaklarini degistirse ya da etiketleri kapatmasa da bozulmazlar.
    doc = dom.parse(html); for a in doc.find_all('a', cls='PL'): a.get('href'), a.text(), a.closest('tr')"""
import re
from html.parser import HTMLParser

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
_SKIP_TEXT = {'script', 'style', 'noscript', 'template'}


class Node:
    __slots__ = ('tag', 'attrs', 'children', 'parent')

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.children, self.parent = tag, attrs or {}, [], parent

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    @property
    def classes(self):
        return (self.attrs.get('class') or '').split()

    def _match(self, tag, cls, attrs):
        return ((tag is None or self.tag == tag) and (cls is None or cls in self.classes)
                and all(self.attrs.get(k) == v for k, v in attrs.items()))

    def iter(self):
        """Bu dugumun altindaki tum elemanlar (belge sirasiyla, kendisi haric)."""
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.iter()

    def find_all(self, tag=None, cls=None, **attrs):
        return [n for n in self.iter() if n._match(tag, cls, attrs)]

    def find(self, tag=None, cls=None, **attrs):
        return next((n for n in self.iter() if n._match(tag, cls, attrs)), None)

    def closest(self, tag=None, cls=None, **attrs):
        """Kendisi ya da en yakin ust eleman."""
        n = self
        while n is not None and n.tag != '#root':
            if n._match(tag, cls, attrs):
                return n
            n = n.parent
        return None

    def text(self):
        """Duz metin (betik/stil haric), bosluklar sadelestirilmis."""
        out = []

        def walk(n):
            for c in n.children:
                if isinstance(c, str):
                    out.append(c)
                elif c.tag not in _SKIP_TEXT:
                    walk(c)
        walk(self)
        return re.sub(r'\s+', ' ', ' '.join(out)).strip()


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = Node('#root')

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: v or '' for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: v or '' for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:  # eslesmeyen kapanis etiketi yok sayilir; kapatilmamis ic etiketler (<p>, <li>) burada kapanir
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(html):
    b = _Builder()
    b.feed(html or '')
    b.close()
    return b.root

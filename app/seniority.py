"""Ilan aciklamasindan deneyim yili ve seviye cikarimi (kural tabanli, LLM yok).
Basliktan seviye belliyse ona dokunulmaz; yalnizca 'Belirtilmemiş' ilanlar aciklamaya gore etiketlenir."""
import re

from .util import norm

LEVELS = ['Junior / Yeni mezun', 'Staj', 'Orta (2-4 yıl)', 'Kıdemli+', 'Belirtilmemiş']

# Acik yeni mezun ifadeleri ("mentor junior engineers" gibi kidemli ilanlarda gecen 'junior' kelimesi bilerek yok)
NEWGRAD = re.compile(r'yeni mezun|new grad|recent graduate|recently graduated|fresh graduate|entry.level|'
                     r'deneyim sarti aranma|tecrube sarti aranma|deneyimsiz|tecrubesiz|no (prior |previous )?experience (is )?required|'
                     r'0\s*[-–]\s*[12]\s*(yil|years?)|(20\d\d) (yilinda )?mezun|graduating in 20\d\d|graduated in 20\d\d')
UNIT = r'(?:yil|years?|yrs)'
YEARS = [
    re.compile(rf'(\d{{1,2}})\s*(?:-|–|—|ile|to)\s*\d{{1,2}}\s*\+?\s*{UNIT}'),                       # 2-4 yil, 3 to 5 years
    re.compile(rf'(?:en az|minimum|min\.?|at least|asgari|en az\.)\s*(\d{{1,2}})\s*\+?\s*{UNIT}'),   # en az 3 yil
    re.compile(rf'(\d{{1,2}})\s*\+\s*{UNIT}'),                                                        # 5+ years
    re.compile(rf'(\d{{1,2}})\s*{UNIT}\s*(?:lik|luk|of|\'?lik)?\s*(?:[a-z/&,.-]+\s){{0,4}}?(?:deneyim|tecrube|experience)'),
    re.compile(rf'(?:deneyim|tecrube|experience)[^0-9.]{{0,30}}(\d{{1,2}})\s*\+?\s*{UNIT}'),
]


def experience(desc):
    """(en kucuk istenen deneyim yili | None, yeni mezun ifadesi var mi)"""
    t = norm(desc or '')[:25000]
    if not t:
        return None, False
    mins = []
    for rx in YEARS:
        for m in rx.finditer(t):
            v = int(m.group(1))
            if 0 <= v <= 15:
                mins.append(v)
    return (min(mins) if mins else None), bool(NEWGRAD.search(t))


def level_from(title_level, desc):
    """(seviye, deneyim_yili)"""
    exp, newgrad = experience(desc)
    if title_level != 'Belirtilmemiş':
        return title_level, exp
    if exp is not None:
        if exp <= 1:
            return 'Junior / Yeni mezun', exp
        if exp <= 4:
            return 'Orta (2-4 yıl)', exp
        return 'Kıdemli+', exp
    if newgrad:
        return 'Junior / Yeni mezun', exp
    return 'Belirtilmemiş', exp

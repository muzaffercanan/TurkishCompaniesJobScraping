"""Program sayfasi (genc yetenek / staj) kurallari: internet gerekmez."""
import unittest
from unittest import mock

from app import programs
from app.util import norm

TURKCELL = dict(id=None, name='Turkcell', website='https://turkcell.com.tr/', career_url=None)
BANK = dict(id=None, name='Ornek Bank', website='https://www.ornekbank.com.tr/', career_url='https://kariyer.ornekbank.com.tr/')

FILL = ' '.join(['Programımız hakkında detaylı bilgi.'] * 20)


def page(title, body):
    return f'<html><head><title>{title} | Firma</title></head><body><h1>{title}</h1><p>{body}</p><p>{FILL}</p></body></html>'


class Rules(unittest.TestCase):
    def test_base_domain(self):
        self.assertEqual(programs.base_domain('kariyerim.turkcell.com.tr'), 'turkcell.com.tr')
        self.assertEqual(programs.base_domain('careers.example.com'), 'example.com')
        self.assertEqual(programs.base_domain('peak.com'), 'peak.com')

    def test_candidate(self):
        self.assertTrue(programs._candidate('https://kariyerim.turkcell.com.tr/genc-yetenek', 'GNÇYTNK', TURKCELL, False))
        self.assertTrue(programs._candidate('https://kariyer.ornekbank.com.tr/cms/ogrenciler-icin', 'Öğrenciler için', BANK, True))
        # baska alan adi, urun/kampanya, haber, pdf: aday degil
        self.assertFalse(programs._candidate('https://www.youthall.com/tr/turkcell/genc-yetenek', 'Genç yetenek', TURKCELL, True))
        self.assertFalse(programs._candidate('https://www.ornekbank.com.tr/kampanyalar/ogrenci-karti', 'Öğrenci kartı', BANK, False))
        self.assertFalse(programs._candidate('https://www.ornekbank.com.tr/haberler/staj-programi-basladi', 'Staj', BANK, False))
        self.assertFalse(programs._candidate('https://kariyer.ornekbank.com.tr/docs/staj.pdf', 'Staj', BANK, True))
        # kariyer baglami olmayan ana sayfada 'ogrenci' tek basina yetmez
        self.assertFalse(programs._candidate('https://www.ornekbank.com.tr/ogrenci', 'Öğrenci', BANK, False))
        # firma adindaki 'kredi' kariyer baglaminda engel olmaz
        yk = dict(website='https://www.yapikredi.com.tr/', career_url=None)
        self.assertTrue(programs._candidate('https://www.yapikredi.com.tr/yapi-kredi-hakkinda/insan-kaynaklari/digital-genc-yetenek-programi',
                                            'Digitalent', yk, False))

    def test_noise_pages(self):
        # SSS sayfasi, tek ilan sayfasi: aday degil
        self.assertFalse(programs._candidate('https://bilgem.tubitak.gov.tr/kariyer/stajla-ilgili-sik-sorulan-sorular/', 'SSS',
                                             dict(website='https://bilgem.tubitak.gov.tr/'), True))
        self.assertFalse(programs._candidate('https://careers.ey.com/ey/job/Ankara-Staj-123', 'Stajyer', dict(website='https://ey.com/'), True))
        self.assertEqual(programs.clean_url('https://jobs.boeing.com/internships/?utm_source=x&utm_medium=y#top'), 'https://jobs.boeing.com/internships/')
        found = [{'url': 'https://www.havelsan.com/tr/hit-staj-programi'}, {'url': 'https://www.havelsan.com/en/hit-summer-internship-program'}]
        self.assertTrue(programs._english_copy(found[1], found))
        self.assertFalse(programs._english_copy(found[1], found[1:]))  # yalnizca Ingilizce sayfa varsa kalir

    def test_kind_and_deadline(self):
        self.assertEqual(programs._kind('GNÇYTNK STAJ 2027 Kış Dönemi'), 'Staj')
        self.assertEqual(programs._kind('Yeni Mezunum'), 'Junior / Yeni mezun')
        self.assertEqual(programs._kind('Genç Yetenek', 'yeni mezun ya da en fazla 2 yıl deneyim'), 'Junior / Yeni mezun')
        self.assertEqual(programs._deadline('Son başvuru tarihi: 15.11.2026'), '2026-11-15')
        self.assertEqual(programs._deadline('Başvurular 30 Kasım 2026 tarihine kadar'), '2026-11-30')
        self.assertIsNone(programs._deadline('Programımız 2026 yılında başladı'))


class Read(unittest.TestCase):
    def _read(self, url, html, company=TURKCELL):
        with mock.patch.object(programs, 'fetch', return_value=(200, url, html)), \
                mock.patch.object(programs.generic, 'looks_js_only', return_value=False):
            return programs.read(url, company)

    def test_open_program(self):
        p = self._read('https://kariyerim.turkcell.com.tr/genc-yetenek',
                       page('Genç Yetenek', 'GNÇYTNK başlıyor! Yeni mezun ya da genç yetenek misin? Hemen Başvur. Genç yetenek programı.'))
        self.assertEqual((p['title'], p['status'], p['kind']), ('Genç Yetenek', 'Başvuru açık', 'Junior / Yeni mezun'))
        self.assertEqual(p['location'], 'Türkiye')

    def test_global_company_page_is_not_turkey(self):
        ericsson = dict(id=None, name='Ericsson Türkiye', category='Telekom & Ağ', website='https://ericsson.com/', career_url=None)
        p = self._read('https://www.ericsson.com/en/careers/students-early-careers/internships',
                       page('Internships', 'Our internship program for students. Interns apply now. Internship and early careers. ' * 3),
                       ericsson)
        self.assertEqual(p['location'], 'Küresel program sayfası')

    def test_closed_program(self):
        p = self._read('https://kariyerim.turkcell.com.tr/gncytnkstaj',
                       page('GNÇYTNK Staj', 'Staj programı başvurularımız sona erdi. Stajyer adaylarımıza teşekkürler, staj dönemi.'))
        self.assertEqual((p['status'], p['kind']), ('Başvuru kapalı', 'Staj'))

    def test_rejects(self):
        # 404 sayfasi, genel kariyer sayfasi (baslik/adres program anlatmiyor), baska firma alan adi
        self.assertIsNone(self._read('https://kariyerim.turkcell.com.tr/staj', page('404', 'Sayfa bulunamadı. staj staj staj başvur')))
        self.assertIsNone(self._read('https://kariyerim.turkcell.com.tr/kariyer',
                                     page('Bize Katıl', 'Staj ve yeni mezun programlarımız, genç yetenek, başvur')))
        self.assertIsNone(self._read('https://www.youthall.com/genc-yetenek', page('Genç Yetenek', 'genç yetenek staj başvur yeni mezun')))
        # baska ulkenin programi
        self.assertIsNone(self._read('https://kariyerim.turkcell.com.tr/internships-us-canada',
                                     page('Internships U.S. and Canada', 'internship students intern apply now internship')))


class Location(unittest.TestCase):
    """Program sayfasinin konumu: sabit 'Türkiye' yerine sayfadan."""
    GLOBAL = dict(name='Ericsson Türkiye', category='Telekom & Ağ')
    LOCAL = dict(name='Dream Games', category='Oyun')
    EN = norm('Join our summer internship program and apply now to grow with us. ' * 8)
    TR = norm('Staj programı için başvuru ve değerlendirme süreci bir ay sürer ve ' * 5)

    def loc(self, url, title='Internships', body=EN, company=LOCAL):
        return programs._location(url, title, body, company)

    def test_turkey_signals(self):
        self.assertEqual(self.loc('https://kariyerim.turkcell.com.tr/genc-yetenek'), 'Türkiye')             # .tr alan adi
        self.assertEqual(self.loc('https://evreka.co/tr/kariyer/staj'), 'Türkiye')                           # /tr/ sayfasi
        self.assertEqual(self.loc('https://x.com/internship', body=norm('Our Istanbul office hosts interns.')), 'Türkiye')
        self.assertEqual(self.loc('https://x.com/staj', 'Staj', body=self.TR), 'Türkiye')                   # Turkce metin
        self.assertEqual(self.loc('https://www.ericsson.com/en/careers/internships', body=norm('Internships in Istanbul, Turkey.'),
                                  company=self.GLOBAL), 'Türkiye')

    def test_foreign_country_in_title_or_path(self):
        self.assertEqual(self.loc('https://www.nokia.com/careers/our-locations/finland/students-and-graduates/', 'Student opportunities',
                                  company=self.GLOBAL), 'Finland')

    def test_global_company_page_without_turkey(self):
        self.assertEqual(self.loc('https://www.ericsson.com/en/careers/students-early-careers', company=self.GLOBAL),
                         'Küresel program sayfası')
        google = dict(name='Google', category='Global Şirket Türkiye Ofisi / Ar-Ge')
        self.assertEqual(self.loc('https://www.google.com/about/careers/applications/students', company=google), 'Küresel program sayfası')

    def test_local_company_english_page_is_unspecified(self):
        self.assertEqual(self.loc('https://www.dreamgames.com/summer-internship'), '')


if __name__ == '__main__':
    unittest.main()

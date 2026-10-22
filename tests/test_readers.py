"""Cevrimdisi testler. Calistir: python -m unittest discover -s tests -v
- okuyucular: kaydedilmis gercek yanitlarla ayni sayida, gecerli ilan uretmeli
- genel ayristirici: ornek sayfalarda dogru ilanlari bulmali, urun/haber baglantilarini almamali
- seviye: aciklamadan deneyim yili/seviye dogru cikmali"""
import json
import os
import unittest

from app import generic, seniority
from tests.readers import CASES, FIXTURES, Recorder, run_case


class ReaderTests(unittest.TestCase):
    pass


def _make(name, kind, reader):
    def test(self):
        path = os.path.join(FIXTURES, name + '.json')
        if not os.path.exists(path):
            self.skipTest('kayit yok: once python -m tests.record ' + name)
        with open(path, encoding='utf-8') as f:
            fx = json.load(f)
        with Recorder(path, 'replay'):
            jobs = run_case(kind, reader, tuple(fx['args']))
        self.assertEqual(len(jobs), fx['count'], 'ilan sayisi kayittakinden farkli: ayristirici degismis')
        ids = [j['id'] for j in jobs]
        self.assertEqual(len(ids), len(set(ids)), 'ilan kimlikleri benzersiz degil')
        for j in jobs:
            self.assertTrue(j.get('title'), f'bos baslik: {j}')
            self.assertTrue(j.get('id'), f'bos kimlik: {j}')
            self.assertTrue((j.get('url') or '').startswith('http'), f'gecersiz baglanti: {j.get("url")}')
    return test


for _n, _k, _r, _a in CASES:
    setattr(ReaderTests, f'test_{_n}', _make(_n, _k, _r))


class GenericTests(unittest.TestCase):
    PAGE = 'https://ornek.com.tr/kariyer'

    def test_ilan_adresi_ve_unvan(self):
        links = [('https://ornek.com.tr/kariyer/backend-developer-123', 'Backend Developer', ''),
                 ('https://ornek.com.tr/urunler/akilli-asistan', 'Akıllı Asistan', ''),
                 ('https://ornek.com.tr/hakkimizda', 'Hakkımızda', '')]
        titles = [j['title'] for j in generic.extract(self.PAGE, links)]
        self.assertEqual(titles, ['Backend Developer'])

    def test_liste_kumesi(self):  # Is Bankasi gibi: adres ilan kalibina uymasa da ayni listede >=2 unvan
        sig = 'STRONG.>DIV.item>DIV.list'
        links = [('https://ik.ornek.com.tr/firsat/uzman-yardimcisi-10', 'Uzman Yardımcısı', '', sig),
                 ('https://ik.ornek.com.tr/firsat/sistem-uzmani-50', 'Sistem Uzmanı', '', sig),
                 ('https://ornek.com.tr/blog/yapay-zeka', 'Yapay zeka ile gelecek', '', 'A.>DIV.blog>DIV.')]
        titles = sorted(j['title'] for j in generic.extract(self.PAGE, links))
        self.assertEqual(titles, ['Sistem Uzmanı', 'Uzman Yardımcısı'])

    def test_tek_urun_baglantisi_alinmaz(self):  # Barikat/ETA gibi: unvan kelimesi gecse de tek basina urun sayfasi
        links = [('https://ornek.com.tr/urunler/eta-asistan', 'ETA Asistan', '', 'LI.>UL.menu>NAV.'),
                 ('https://ornek.com.tr/cozumler/yetkili-erisim', 'Yetkili Erişim ve Parola Yönetimi', '', 'LI.>UL.menu2>NAV.')]
        self.assertEqual(generic.extract(self.PAGE, links), [])

    def test_firmanin_sayfasindaki_linkedin_ilani(self):  # Index Grup gibi
        links = [('https://www.linkedin.com/jobs/view/3748159975', 'Presales Uzmanı İstanbul', ''),
                 ('https://www.linkedin.com/company/ornek', 'LinkedIn', '')]
        self.assertEqual([j['title'] for j in generic.extract(self.PAGE, links)], ['Presales Uzmanı İstanbul'])

    def test_video_ve_liste_basligi_alinmaz(self):
        links = [('https://ornek.com.tr/kariyer/video-yeni-mezun', "Video PwC'de Yeni Mezun Olmak 1:01", ''),
                 ('https://ornek.com.tr/kariyer/tum-ilanlar', 'Tüm İlanlar', '')]
        self.assertEqual(generic.extract(self.PAGE, links), [])


class SeniorityTests(unittest.TestCase):
    CASES = [("Minimum 3 years of experience in backend development", 'Orta (2-4 yıl)', 3),
             ("En az 5 yıl yazılım geliştirme deneyimi", 'Kıdemli+', 5),
             ("0-2 yıl deneyimli veya yeni mezun adaylar", 'Junior / Yeni mezun', 0),
             ("You will mentor junior engineers. We are a 20+ years company.", 'Belirtilmemiş', None),
             ("Bilgisayar mühendisliği mezunu, tecrübe şartı aranmamaktadır", 'Junior / Yeni mezun', None),
             ("Yazılım geliştirme konusunda 3-5 yıl tecrübeli", 'Orta (2-4 yıl)', 3)]

    def test_aciklamadan_seviye(self):
        for desc, level, exp in self.CASES:
            with self.subTest(desc=desc):
                self.assertEqual(seniority.level_from('Belirtilmemiş', desc), (level, exp))

    def test_baslik_seviyesi_korunur(self):
        self.assertEqual(seniority.level_from('Staj', 'En az 5 yıl deneyim')[0], 'Staj')


if __name__ == '__main__':
    unittest.main()

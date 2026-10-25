"""Kucuk HTML agaci (app.dom) ve onu kullanan okuyucular: kapatilmamis etiketler, tirnaksiz nitelikler, eksik alanlar.
Internet yok."""
import unittest
from unittest import mock

from app import ats, custom, dom


class Tree(unittest.TestCase):
    def test_find_by_tag_class_and_attrs(self):
        doc = dom.parse('<div class="a b"><a href=/x class=PL>X</a><td align=center> 9.09.2026 </td></div>')
        self.assertEqual(doc.find('a', cls='PL').get('href'), '/x')
        self.assertEqual(doc.find(cls='b').tag, 'div')
        self.assertEqual(doc.find('td', align='center').text(), '9.09.2026')
        self.assertIsNone(doc.find('a', cls='yok'))

    def test_unclosed_tags_are_closed_by_parent(self):
        doc = dom.parse('<div class=card><p class=date>20.10.2026<p>5 gun</div><div class=card><h2>Iki</h2></div>')
        cards = doc.find_all('div', cls='card')
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[1].find('h2').text(), 'Iki')
        self.assertIsNone(cards[1].find('p'))  # ilk kartin kapanmamis <p>'leri ikinci karta tasmaz

    def test_text_skips_scripts_and_decodes_entities(self):
        doc = dom.parse('<p>M&#252;hendis <script>var x=1</script> <b>Ankara</b>\n</p>')
        self.assertEqual(doc.text(), 'Mühendis Ankara')

    def test_closest_and_stray_end_tags(self):
        doc = dom.parse('<table><tr><td><a class=PL>X</a></span></td></tr></table>')
        self.assertEqual(doc.find('a').closest('tr').tag, 'tr')
        self.assertIsNone(doc.find('a').closest('ul'))


ROKETSAN = '''<table><tr class=GR><td><a href="/aaa111.job" class="PL">Teknisyen</a><span class=location>Ankara</span></td>
<td align="center"> 9.09.2026 </td></tr><tr class=GAR><td><a href="/bbb222.job" class="PL">Yangin Gorevlisi</a></td>
<td align="center"> 21.10.2026 </td></tr><tr><td><a href="/ccc333.job" class=PL>Muhendis</a><span class="location">Istanbul</span></td>
<td align=center>13.10.2026</td></tr></table>'''


class Readers(unittest.TestCase):
    def test_roketsan_row_without_location_is_not_merged(self):
        with mock.patch.object(custom, '_open', return_value=ROKETSAN):
            jobs = custom.roketsan()
        self.assertEqual([(j['id'], j['title'], j['location'], j['posted']) for j in jobs],
                         [('aaa111', 'Teknisyen', 'Ankara, Türkiye', '2026-09-09'), ('bbb222', 'Yangin Gorevlisi', 'Türkiye', '2026-10-21'),
                          ('ccc333', 'Muhendis', 'Istanbul, Türkiye', '2026-10-13')])

    def test_successfactors_rows(self):
        row = ('<tr class="data-row"><td><span class="jobTitle hidden-phone"><a class="jobTitle-link" href="/job/Istanbul-Dev-{i}/">'
               'Developer {i}</a></span><span class="jobTitle visible-phone"><a class="jobTitle-link" href="/job/Istanbul-Dev-{i}/">'
               'Developer {i}</a></span></td><td><span class="jobLocation">Istanbul, TR</span></td></tr>')
        page1 = '<table>' + ''.join(row.format(i=i) for i in range(10)) + '</table>'
        page2 = '<table>' + row.format(i=10) + '</table>'
        with mock.patch.object(ats, 'fetch', side_effect=[(200, 'u', page1), (200, 'u', page2)]) as f:
            jobs = ats.successfactors('x', 'career.firma.com')
        self.assertEqual(len(jobs), 11)                  # masaustu + mobil kopyasi tek ilan
        self.assertEqual((jobs[0]['title'], jobs[0]['location'], jobs[0]['url']),
                         ('Developer 0', 'Istanbul, TR', 'https://career.firma.com/job/Istanbul-Dev-0/'))
        self.assertIn('startrow=10', f.call_args_list[1].args[0])


if __name__ == '__main__':
    unittest.main()

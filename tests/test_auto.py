"""Otomatik tarama zamanlayicisi, 'bana uygun' sayimi ve masaustu bildirimi: internet yok, bildirim gosterilmez, gercek veriye dokunulmaz."""
import base64
import datetime as dt
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from app import auto, db, notify, scanner, search
from tests.tempdb import TempDb


def ago(**kw):
    return dt.datetime.now() - dt.timedelta(**kw)


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._cfg, search.CONFIG = search.CONFIG, os.path.join(self.tmp, 'config.json')

    def tearDown(self):
        search.CONFIG = self._cfg
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_when_no_file(self):
        self.assertEqual(auto.settings(), dict(enabled=True, hours=12, notify=True))

    def test_save_validates_and_keeps_other_keys(self):
        search.save_config({'brave_api_key': 'abc'})
        got = auto.save({'enabled': False, 'hours': 24, 'notify': False, 'bogus': 1})
        self.assertEqual(got, dict(enabled=False, hours=24, notify=False))
        self.assertEqual(auto.save({'hours': 7}), got)                     # gecersiz sure yok sayilir
        self.assertEqual(auto.save({'enabled': True})['hours'], 24)         # gonderilmeyen alan degismez
        with open(search.CONFIG, encoding='utf-8') as f:
            self.assertEqual(json.load(f)['brave_api_key'], 'abc')          # Brave anahtari silinmez

    def test_save_is_atomic(self):
        search.save_config({'auto': {'hours': 6}})
        self.assertEqual(sorted(os.listdir(self.tmp)), ['config.json'])      # gecici dosya birakilmaz
        with open(search.CONFIG, encoding='utf-8') as f:
            self.assertEqual(json.load(f), {'auto': {'hours': 6}})

    def test_bad_stored_values_fall_back(self):
        search.save_config({'auto': {'hours': 999, 'enabled': 0}})
        self.assertEqual(auto.settings(), dict(enabled=False, hours=12, notify=True))


class Schedule(TempDb):
    def scan(self, finished, ok=5, mode='hizli'):
        self.con.execute('INSERT INTO scans(started, finished, mode, ok) VALUES(?,?,?,?)',
                         (finished.isoformat(timespec='seconds'), finished.isoformat(timespec='seconds'), mode, ok))
        self.con.commit()

    def cfg(self, **kw):
        return dict(auto.DEFAULTS, **kw)

    def test_next_due_rules(self):
        t = dt.datetime(2026, 10, 20, 9, 0)
        self.assertIsNone(auto.next_due(self.cfg(), None, None))                              # hic tarama yok: ilk tarama elle
        self.assertIsNone(auto.next_due(self.cfg(enabled=False), t, 5))                       # kapali
        self.assertEqual(auto.next_due(self.cfg(hours=6), t, 5), t + dt.timedelta(hours=6))
        self.assertEqual(auto.next_due(self.cfg(), t, 0), t + dt.timedelta(minutes=auto.RETRY_MINUTES))  # hic kaynak okunamadi: erken tekrar

    def test_last_full_scan_ignores_partial_modes(self):
        self.scan(ago(days=3))
        self.scan(ago(minutes=5), mode='firma')       # tek firma yeniden kesfi sayaci sifirlamaz
        self.scan(ago(minutes=3), mode='program')
        last, ok = auto.last_full_scan(self.con)
        self.assertLess(dt.datetime.now() - last, dt.timedelta(days=3, minutes=1))
        self.assertGreater(dt.datetime.now() - last, dt.timedelta(days=2, hours=23))

    def tick(self, running=False, **cfg):
        with mock.patch.object(auto, 'settings', return_value=self.cfg(**cfg)), \
             mock.patch.dict(scanner.STATE, {'running': running}), \
             mock.patch.object(scanner, 'start', return_value=True) as start:
            return auto.tick(), start

    def test_tick_starts_only_when_due(self):
        self.scan(ago(hours=13))
        started, start = self.tick()
        self.assertTrue(started)
        start.assert_called_once_with('hizli', auto=True)

    def test_tick_not_due_running_disabled_or_never_scanned(self):
        self.scan(ago(hours=2))
        self.assertFalse(self.tick()[0])                                  # daha vakit var
        self.assertFalse(self.tick(running=True)[0])                      # baska tarama suruyor
        self.assertFalse(self.tick(enabled=False)[0])                     # kapali

    def test_tick_never_scanned(self):
        started, start = self.tick()
        self.assertFalse(started)
        start.assert_not_called()

    def test_status(self):
        t = ago(hours=1).replace(microsecond=0)
        self.scan(t)
        with mock.patch.object(auto, 'settings', return_value=self.cfg(hours=6)):
            st = auto.status(self.con)
        self.assertEqual(st['last_at'], t.isoformat(timespec='seconds'))
        self.assertEqual(st['next_at'], (t + dt.timedelta(hours=6)).isoformat(timespec='seconds'))
        self.assertEqual((st['enabled'], st['hours'], st['notify']), (True, 6, True))


class Summary(TempDb):
    """_summarize_new: tarama sonunda 'yeni' ve 'bana uygun' sayimi (db.RECENT + db.FIT)."""

    def add(self, jid, level, tech, region, first_seen=None, baseline=0, active=1, hidden=0, posted=None):
        self.con.execute('INSERT INTO jobs(id, company_id, source, ext_id, title, level, is_tech, region, first_seen, is_baseline, active, hidden, posted) '
                         "VALUES(?,1,'lever',?,?,?,?,?,?,?,?,?,?)",
                         (jid, str(jid), f'Job {jid}', level, tech, region, first_seen or dt.date.today().isoformat(), baseline, active, hidden, posted))
        self.con.commit()

    def test_counts(self):
        self.add(1, 'Junior / Yeni mezun', 1, 'Türkiye')                   # uygun
        self.add(2, 'Staj', 1, 'Uzaktan')                                  # uygun
        self.add(3, 'Staj', 1, 'Belirtilmemiş')                            # uygun (konum belirsiz de sayilir)
        self.add(4, 'Junior / Yeni mezun', 1, 'Yurt dışı')                 # yurt disi: uygun degil
        self.add(5, 'Kıdemli+', 1, 'Türkiye')                              # kidemli: uygun degil
        self.add(6, 'Junior / Yeni mezun', 0, 'Türkiye')                   # teknik degil
        self.add(7, 'Staj', 1, 'Türkiye', hidden=1)                        # gizlenmis
        self.add(8, 'Staj', 1, 'Türkiye', active=0)                        # kapanmis
        self.add(9, 'Staj', 1, 'Türkiye', baseline=1)                      # ilk tarama, yayin tarihi yok: yeni degil
        self.add(10, 'Staj', 1, 'Türkiye', baseline=1, posted=dt.date.today().isoformat())   # ilk tarama ama bugun yayinlandi: yeni + uygun
        with mock.patch.object(scanner, '_NEW_IDS', list(range(1, 11))):
            fresh, fit = scanner._summarize_new()
        self.assertEqual(sorted(r['id'] for r in fit), [1, 2, 3, 10])
        self.assertEqual(fresh, 7)   # 1-6 (7 gizli, 8 kapali, 9 yeni degil) ve 10 => 1,2,3,4,5,6,10

    def test_only_ids_from_this_scan(self):
        self.add(1, 'Staj', 1, 'Türkiye')
        self.add(2, 'Staj', 1, 'Türkiye')
        with mock.patch.object(scanner, '_NEW_IDS', [2]):
            self.assertEqual([r['id'] for r in scanner._summarize_new()[1]], [2])
        with mock.patch.object(scanner, '_NEW_IDS', []):
            self.assertEqual(scanner._summarize_new(), (0, []))

    def test_notify_only_when_enabled_and_fit(self):
        fit = [dict(id=i, title=f'Junior Dev {i}', company='Acme') for i in range(5)]
        with mock.patch.object(auto, 'settings', return_value=dict(enabled=True, hours=12, notify=True)), \
             mock.patch('app.notify.toast') as toast, mock.patch.object(scanner.threading, 'Thread') as thread:
            scanner._notify_fit([])
            thread.assert_not_called()
            scanner._notify_fit(fit)
        args = thread.call_args.kwargs['args']
        self.assertEqual(args[0], '5 yeni ilan sana uygun')
        self.assertEqual(args[1][0], 'Acme — Junior Dev 0')
        self.assertEqual(args[1][3], '+2 ilan daha')                    # ilk 3 ilan + "+N daha"
        self.assertTrue(args[2].endswith('#fit'))
        toast.assert_not_called()                                       # Thread sahte: gercek bildirim gonderilmedi
        with mock.patch.object(auto, 'settings', return_value=dict(enabled=True, hours=12, notify=False)), \
             mock.patch.object(scanner.threading, 'Thread') as thread:
            scanner._notify_fit(fit)
            thread.assert_not_called()


class RunFlow(TempDb):
    """scanner.run'in bitis yolu: ozet -> bildirim (yalniz otomatikte) -> scans kaydi. Ag/tarayici yok: _browser_pool sahte."""

    def run_scan(self, auto):
        self.con.execute("INSERT INTO jobs(id, company_id, source, ext_id, title, level, is_tech, region, first_seen, is_baseline, active, hidden) "
                         "VALUES(1, 1, 'lever', '1', 'Junior Dev', 'Junior / Yeni mezun', 1, 'Türkiye', ?, 0, 1, 0)", (dt.date.today().isoformat(),))
        self.con.commit()
        with mock.patch.object(scanner, '_browser_pool', side_effect=lambda *a, **k: scanner._NEW_IDS.append(1)), \
             mock.patch.object(db, 'sync_excel', return_value=0), mock.patch.object(scanner, '_notify_fit') as notify_fit:
            self.assertTrue(scanner.run('yeni', auto=auto))
        return notify_fit

    def test_auto_scan_summarizes_and_notifies(self):
        notify_fit = self.run_scan(auto=True)
        self.assertEqual((scanner.STATE['running'], scanner.STATE['auto'], scanner.STATE['fresh'], scanner.STATE['fit']), (False, True, 1, 1))
        notify_fit.assert_called_once()
        self.assertEqual([r['id'] for r in notify_fit.call_args.args[0]], [1])
        row = db.tl().execute('SELECT mode FROM scans ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual(row['mode'], 'yeni')

    def test_manual_scan_does_not_notify(self):
        notify_fit = self.run_scan(auto=False)
        self.assertEqual((scanner.STATE['auto'], scanner.STATE['fit']), (False, 1))   # sayilir ama bildirim yok (arayuz zaten gosterir)
        notify_fit.assert_not_called()


class Toast(unittest.TestCase):
    def test_script_is_encoded_for_powershell(self):
        self.assertEqual(base64.b64decode(notify._ENCODED).decode('utf-16-le'), notify._PS)

    def test_passes_text_through_environment(self):
        with mock.patch.object(notify.sys, 'platform', 'win32'), mock.patch.object(notify.subprocess, 'run') as run:
            run.return_value = mock.Mock(returncode=0, stderr='', stdout='')
            ok, err = notify.toast('Başlık "tırnaklı"', ['satır 1', 'satır 2'], 'http://127.0.0.1:8765/#fit')
        self.assertEqual((ok, err), (True, ''))
        cmd, kw = run.call_args.args[0], run.call_args.kwargs
        self.assertIn('-EncodedCommand', cmd)
        self.assertNotIn('tırnaklı', ' '.join(cmd))                     # metin komut satirinda degil
        self.assertEqual((kw['env']['IR_TITLE'], kw['env']['IR_LINES'], kw['env']['IR_URL']),
                         ('Başlık "tırnaklı"', 'satır 1\nsatır 2', 'http://127.0.0.1:8765/#fit'))

    def test_failure_is_reported_not_raised(self):
        with mock.patch.object(notify.sys, 'platform', 'win32'), mock.patch.object(notify.subprocess, 'run') as run:
            run.return_value = mock.Mock(returncode=1, stderr='hata var', stdout='')
            self.assertEqual(notify.toast('x'), (False, 'hata var'))
            run.side_effect = OSError('exe yok')
            self.assertEqual(notify.toast('x'), (False, 'exe yok'))

    def test_other_platforms_skip(self):
        with mock.patch.object(notify.sys, 'platform', 'linux'), mock.patch.object(notify.subprocess, 'run') as run:
            self.assertFalse(notify.toast('x')[0])
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()

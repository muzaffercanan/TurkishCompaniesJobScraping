"""Masaustu bildirimi (Windows toast). Windows disindaki sistemlerde sessizce atlanir; uygulama bildirim gonderemese bile calisir.
PowerShell'in kendi uygulama kimligiyle gosterilir (ek kurulum ya da kayit gerekmez); metinler ortam degiskeniyle gecer, komut satirina karismaz."""
import base64
import os
import subprocess
import sys

BASE_URL = 'http://127.0.0.1:8765/'  # server.main gercek adresi yazar; bildirime tiklaninca bu adres acilir

_PS = r'''
$ErrorActionPreference = 'Stop'
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
function E($s) { [System.Security.SecurityElement]::Escape([string]$s) }
$lines = @(($env:IR_LINES -split "`n") | Where-Object { $_ } | Select-Object -First 3)
$texts = '<text>' + (E $env:IR_TITLE) + '</text>' + (($lines | ForEach-Object { '<text>' + (E $_) + '</text>' }) -join '')
$launch = ''
if ($env:IR_URL) { $launch = ' activationType="protocol" launch="' + (E $env:IR_URL) + '"' }
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast' + $launch + '><visual><binding template="ToastGeneric">' + $texts + '</binding></visual></toast>')
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
'''
_ENCODED = base64.b64encode(_PS.encode('utf-16-le')).decode('ascii')


def toast(title, lines=(), url=None):
    """Bildirim gonderir. Dondurur: (basarili_mi, hata_metni). Basarili = PowerShell hatasiz bitti (Odak/Rahatsiz Etme acikken
    Windows bildirimi gostermeyebilir; Eylem Merkezi'ne duser)."""
    if sys.platform != 'win32':
        return False, 'masaustu bildirimi yalnizca Windows\'ta destekleniyor'
    exe = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    env = dict(os.environ, IR_TITLE=title, IR_LINES='\n'.join(lines), IR_URL=url or '')
    try:
        r = subprocess.run([exe, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', _ENCODED],
                           env=env, capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)[:200]
    return (True, '') if r.returncode == 0 else (False, (r.stderr or r.stdout or f'cikis kodu {r.returncode}').strip()[:300])

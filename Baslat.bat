@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Ilan Radari
echo Ilan Radari baslatiliyor... Tarayicinda http://127.0.0.1:8765 acilacak.
echo Kapatmak icin bu pencereyi kapat.
python -m app.server
pause

"""Testler icin gecici veritabani: db.DB_PATH gecici bir dosyaya yonlendirilir, is parcacigi baglantisi sifirlanir.
Gercek data/app.db'ye dokunulmaz."""
import os
import shutil
import tempfile
import threading
import unittest

from app import db


class TempDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._path, db.DB_PATH = db.DB_PATH, os.path.join(self.tmp, 'test.db')
        db._tls = threading.local()
        self.con = db.tl()
        self.con.execute("INSERT INTO companies(id, name) VALUES(1, 'Firma')")
        self.con.commit()

    def tearDown(self):
        self.con.close()
        db._tls = threading.local()
        db.DB_PATH = self._path
        shutil.rmtree(self.tmp, ignore_errors=True)

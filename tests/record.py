"""Okuyucularin canli yanitlarini tests/fixtures/ altina kaydet. Kullanim: python -m tests.record [test_adi ...]"""
import json
import os
import sys

from tests.readers import CASES, FIXTURES, Recorder, resolve_args, run_case


def main(only=None):
    os.makedirs(FIXTURES, exist_ok=True)
    for name, kind, reader, args in CASES:
        if only and name not in only:
            continue
        path = os.path.join(FIXTURES, name + '.json')
        try:
            a = resolve_args(name, args)
            with Recorder(path, 'record') as rec:
                jobs = run_case(kind, reader, a)
            json.dump(dict(args=list(a), count=len(jobs), sample=[{k: j.get(k) for k in ('id', 'title', 'url')} for j in jobs[:3]],
                           calls=rec.calls), open(path, 'w', encoding='utf-8'), ensure_ascii=False)
            print(f'{name:28s} {len(jobs):4d} ilan, {len(rec.calls)} istek kaydedildi')
        except Exception as e:  # noqa: BLE001
            print(f'{name:28s} KAYDEDILEMEDI: {e}')


if __name__ == '__main__':
    main(set(sys.argv[1:]) or None)

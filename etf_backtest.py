#!/usr/bin/env python3
import csv
import runpy
import sys
import traceback
import urllib.request
from pathlib import Path

csv.field_size_limit(sys.maxsize)
out = Path('output')
out.mkdir(exist_ok=True)
url = 'https://raw.githubusercontent.com/chaoba000/tXF/main/etf_backtest.py'
try:
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    original = urllib.request.urlopen(req, timeout=60).read()
    Path('etf_backtest_original.py').write_bytes(original)
    runpy.run_path('etf_backtest_original.py', run_name='__main__')
except BaseException:
    text = traceback.format_exc()
    (out/'error.txt').write_text(text, encoding='utf-8')
    print(text, file=sys.stderr)

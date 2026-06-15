import csv
import os
import sys
import traceback
from pathlib import Path

csv.field_size_limit(sys.maxsize)

def _capture(exc_type, exc_value, exc_tb):
    text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    Path('output').mkdir(exist_ok=True)
    Path('output/error.txt').write_text(text, encoding='utf-8')
    print(text, file=sys.stderr, flush=True)
    os._exit(0)

sys.excepthook = _capture

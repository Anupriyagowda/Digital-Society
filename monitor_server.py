import time
import urllib.request
import urllib.error
from datetime import datetime

ENDPOINTS = [
    'http://127.0.0.1:5000/',
    'http://127.0.0.1:5000/admin/notices',
    'http://127.0.0.1:5000/api/residents',
    'http://127.0.0.1:5000/notices/'
]
LOGFILE = 'app_logs.txt'
INTERVAL = 5

def log(msg):
    ts = datetime.utcnow().isoformat() + 'Z'
    line = f'[{ts}] {msg}\n'
    with open(LOGFILE, 'a', encoding='utf-8') as f:
        f.write(line)
    print(line, end='')

while True:
    for url in ENDPOINTS:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                status = r.getcode()
                log(f'OK {status} {url}')
        except urllib.error.HTTPError as e:
            body = e.read(1000).decode('utf-8', errors='replace')
            log(f'HTTPError {e.code} {url} | {body}')
            if e.code >= 500:
                log(f'ALERT: 500+ at {url}')
        except Exception as ex:
            log(f'ERROR {ex} {url}')
    time.sleep(INTERVAL)

import urllib.request, urllib.error
import socket

ENDPOINTS = [
    '/',
    '/auth/role/owner',
    '/notices',
    '/admin/notices',
    '/owner/residents',
    '/events',
]

BASE = 'http://127.0.0.1:5000'
TIMEOUT = 5

def check_live():
    print('Checking live server at', BASE)
    ok = True
    for path in ENDPOINTS:
        url = BASE + path
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
                code = r.getcode()
                print(f'{path:20} -> {code}')
        except urllib.error.HTTPError as e:
            print(f'{path:20} -> HTTP {e.code}')
            ok = False
        except Exception as ex:
            print(f'{path:20} -> ERROR {ex}')
            ok = False
    return ok

if __name__ == '__main__':
    # Try live server first
    try:
        live_ok = check_live()
        if live_ok:
            print('Live server OK')
        else:
            print('Live server had errors; you may need to start the app or inspect logs.')
    except Exception as e:
        print('Live check failed, falling back to app.test_client()', e)
        # Fallback to internal test client
        try:
            from app import create_app
            app = create_app()
            app.config.update(TESTING=True)
            with app.test_client() as c:
                for path in ENDPOINTS:
                    resp = c.get(path)
                    print(f'{path:20} -> {resp.status_code}')
        except Exception as ex:
            print('Fallback check failed:', ex)

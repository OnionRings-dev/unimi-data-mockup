"""HTTP seriale con archivio riproducibile delle risposte, anche fallite."""
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Sources:
    def __init__(self, root, offline=False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / 'manifest.json'
        self.entries = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
        self.offline = offline

    def get(self, url, params=None):
        method = 'POST' if params is not None else 'GET'
        request = {'url': url, 'method': method, 'parameters': params or {}}
        key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        if key not in self.entries:
            if self.offline:
                raise RuntimeError(f'Fonte non archiviata: {request}')
            time.sleep(0.15)
            req = urllib.request.Request(url, data=urllib.parse.urlencode(params, doseq=True).encode() if params is not None else None,
                                         headers={'User-Agent': 'UniMiMockResearch/1.0 (public academic data snapshot)'})
            error = None
            try:
                with urllib.request.urlopen(req, timeout=40) as response:
                    raw = response.read()
                    status, final_url = response.status, response.url
                    content_type = response.headers.get('Content-Type', '')
            except urllib.error.HTTPError as exc:
                raw, status, final_url = exc.read(), exc.code, exc.url
                content_type = exc.headers.get('Content-Type', '')
                error = str(exc)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raw, status, final_url, content_type = b'', None, url, ''
                error = str(exc)
            path = self.root / (key + '.raw')
            path.write_bytes(raw)
            self.entries[key] = {**request, 'final_url': final_url, 'status': status,
                                 'content_type': content_type, 'fetched_at': utcnow(),
                                 'sha256': hashlib.sha256(raw).hexdigest(), 'path': str(path), 'error': error}
            self.manifest_path.write_text(json.dumps(self.entries, ensure_ascii=False, indent=2) + '\n')
        entry = self.entries[key]
        raw = Path(entry['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError(f'Hash sorgente non valido: {entry["path"]}')
        return key, raw, entry


def assignment(raw, variable):
    """Legge JSON da un assegnamento JS noto; non esegue JavaScript."""
    import re
    text = raw.decode('utf-8-sig')
    match = re.search(r'\b' + re.escape(variable) + r'\s*=\s*', text)
    if not match:
        raise ValueError(f'Assegnamento {variable} assente')
    return json.JSONDecoder().raw_decode(text[match.end():])[0]

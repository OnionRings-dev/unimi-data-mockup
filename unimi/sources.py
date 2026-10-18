"""Cache HTTP verificabile: una risposta compressa e i suoi metadati per richiesta."""
import gzip
import hashlib
import json
import ssl
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import certifi
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass
class Document:
    meta: dict
    _raw: bytes | None = None

    @property
    def raw(self):
        if self._raw is not None:
            return self._raw
        value = gzip.decompress((ROOT / self.meta["path"]).read_bytes())
        if hashlib.sha256(value).hexdigest() != self.meta["sha256"]:
            raise ValueError(f"Hash della fonte non valido: {self.url}")
        return value

    @property
    def key(self):
        return self.meta["key"]

    @property
    def url(self):
        return self.meta["url"]

    @property
    def ok(self):
        return self.meta["status"] == 200 and bool(self.raw)

    def soup(self):
        return BeautifulSoup(self.raw, "lxml")


def read_document(path):
    meta = json.loads(Path(path).read_text())
    raw = gzip.decompress((ROOT / meta["path"]).read_bytes())
    if hashlib.sha256(raw).hexdigest() != meta["sha256"]:
        raise ValueError(f"Hash della fonte non valido: {meta['url']}")
    return Document(meta, raw)


def atomic_write(target, data):
    target = Path(target)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def project_room_metadata(raw):
    """Conserva esclusivamente l'anagrafica, mai eventi o griglie di occupazione."""
    data = json.loads(raw)
    areas = data.get("area_rooms") if isinstance(data, dict) else None
    if not isinstance(areas, dict):
        raise ValueError("Anagrafica area_rooms assente nella risposta")
    return dumps({"area_rooms": areas}).encode()


class Sources:
    def __init__(self, offline=False, retry_failed=False):
        self.offline = offline
        self.retry_failed = retry_failed
        self.lock = threading.Lock()
        self.next_request = 0.0
        self.retried = set()
        self.context = ssl.create_default_context(cafile=certifi.where())
        RAW.mkdir(parents=True, exist_ok=True)

    def get(self, url, parameters=None, projection=None):
        parts = urlsplit(url)
        if parts.scheme != "https" or not (parts.hostname == "unimi.it" or (parts.hostname or "").endswith(".unimi.it")):
            raise ValueError(f"Fonte esterna al perimetro UniMi: {url}")
        if parts.path.endswith(("grid_call.php", "test_call.php")):
            raise ValueError("La raccolta degli eventi è esclusa")
        if parts.path.endswith("rooms_call.php") and not (
                projection == "area_rooms" and parameters and str(parameters.get("all_events")) == "0"):
            raise ValueError("Il servizio aule è ammesso solo per l'anagrafica statica")
        if projection is not None and projection != "area_rooms":
            raise ValueError(f"Proiezione non supportata: {projection}")
        request_metadata = {"method": "POST" if parameters is not None else "GET"}
        if parameters is not None:
            request_metadata["parameters"] = parameters
        if projection:
            request_metadata["projection"] = projection
        fingerprint = dumps({"url": url, **request_metadata}) if parameters is not None or projection else url
        key = hashlib.sha256(fingerprint.encode()).hexdigest()
        meta_path = RAW / (key + ".json")
        if meta_path.exists():
            doc = read_document(meta_path)
            transient = doc.meta["status"] is None or doc.meta["status"] in {408, 429, 500, 502, 503, 504}
            if doc.ok or not transient or not self.retry_failed or self.offline or url in self.retried:
                return doc
            self.retried.add(url)
        if self.offline:
            raise FileNotFoundError(f"Fonte non archiviata: {url}")
        # Al massimo 5 nuovi avvii HTTP al secondo, condivisi fra i worker.
        with self.lock:
            delay = max(0, self.next_request - time.monotonic())
            self.next_request = max(self.next_request, time.monotonic()) + 0.2
        time.sleep(delay)
        request = Request(url, data=urlencode(parameters, doseq=True).encode() if parameters is not None else None,
                          headers={"User-Agent": "UniMiData/0.1 (public academic metadata; no timetable events)"})
        error = None
        truncated = False
        try:
            with urlopen(request, timeout=25, context=self.context) as response:
                raw = response.read(4 * 1024 * 1024 + 1) if projection else response.read()
                truncated = bool(projection and len(raw) > 4 * 1024 * 1024)
                status, final_url = response.status, response.url
                content_type = response.headers.get("Content-Type", "")
        except HTTPError as exc:
            raw, status, final_url = exc.read(), exc.code, exc.url
            content_type, error = exc.headers.get("Content-Type", ""), str(exc)
        except (URLError, TimeoutError, OSError) as exc:
            raw, status, final_url, content_type, error = b"", None, url, "", str(exc)
        if projection:
            request_metadata["response_sha256"] = hashlib.sha256(raw).hexdigest() if raw and not truncated else None
            request_metadata["http_status"] = status
            try:
                if truncated:
                    raise ValueError("Risposta metadati oltre il limite di 4 MiB")
                raw = project_room_metadata(raw)
            except (ValueError, TypeError) as exc:
                raw, error = b"", error or str(exc)
                if status == 200:
                    status = None
        meta = {"key": key, "url": url, "final_url": final_url, "status": status,
                "content_type": content_type, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "sha256": hashlib.sha256(raw).hexdigest(), "path": f"data/raw/{key}.gz", "error": error,
                "request_metadata": request_metadata}
        self.save(meta, raw)
        return Document(meta, raw)

    @staticmethod
    def save(meta, raw):
        key = meta["key"]
        # Il contenuto è immutabile: interrompere un retry non invalida la copia
        # precedente. Solo il puntatore JSON viene sostituito atomicamente.
        meta["path"] = "data/raw/" + meta["sha256"] + ".gz"
        blob = RAW / (meta["sha256"] + ".gz")
        if not blob.exists():
            atomic_write(blob, gzip.compress(raw, mtime=0))
        atomic_write(RAW / (key + ".json"), (dumps(meta) + "\n").encode())


def assignment(raw, variable):
    """Estrae JSON da un assegnamento noto, senza eseguire JavaScript."""
    import re
    value = raw.decode("utf-8-sig")
    match = re.search(r"\b" + re.escape(variable) + r"\s*=\s*", value)
    if not match:
        raise ValueError(f"Assegnamento assente: {variable}")
    return json.JSONDecoder().raw_decode(value[match.end():])[0]

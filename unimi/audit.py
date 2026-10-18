"""Confronto dei percorsi di laurea con cataloghi e associazioni per facoltà."""
import gzip
import hashlib
import json
import re
import sqlite3
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi
from bs4 import BeautifulSoup

from .build import OUTPUT
from .collect import CATALOGUES
from .parse import cards, text
from .sources import ROOT, Sources

DEGREE_LEVELS = {'bachelor_or_single_cycle', 'masters_degree'}


def catalogue_totals(doc):
    return [(int(shown), int(total)) for shown, total in
            re.findall(r"(\d+) cors[oi] su (\d+)", text(doc))]


def compare(db, catalogues, filters):
    """Confronta insiemi di identità; non bastano conteggi uguali."""
    def ids(rows):
        found, missing = set(), []
        for row in rows:
            record = db.execute("SELECT p.id FROM identifier i JOIN programme p ON p.id=i.entity_id WHERE i.value=?", (row['url'],)).fetchone()
            if record:
                found.add(record[0])
            else:
                missing.append(row)
        return found, missing

    expected, missing = set(), []
    for rows in catalogues:
        found, absent = ids(rows)
        expected.update(found)
        missing.extend(absent)
    actual = {r[0] for r in db.execute("SELECT id FROM programme WHERE level IN ('bachelor','single_cycle','masters_degree')")}
    faculty_rows, covered = [], set()
    for name, rows in sorted(filters.items()):
        found, absent = ids(rows)
        candidates = {r[0] for r in db.execute('SELECT id,name FROM faculty') if r[1] in {name, 'Scuola di ' + name}}
        linked = {r[0] for r in db.execute('SELECT DISTINCT programme_id,faculty_id FROM programme_faculty') if r[1] in candidates and r[0] in actual}
        covered.update(found)
        faculty_rows.append({'faculty': name, 'published': len({r['url'] for r in rows}),
                             'present': len(found), 'linked': len(found & linked),
                             'missing_programmes': absent, 'missing_relations': sorted(found - linked),
                             'extra_relations': sorted(linked - found), 'faculty_identity_matches': len(candidates)})
    return {'published_unique': len({r['url'] for rows in catalogues for r in rows}),
            'database_degrees': len(actual), 'missing_programmes': missing,
            'database_only_ids': sorted(actual - expected),
            'without_faculty_in_source': sorted(expected - covered), 'faculties': faculty_rows}


def audit(live=False):
    now = datetime.now(timezone.utc)
    evidence = ROOT / 'data/audits' / now.strftime('%Y%m%dT%H%M%S%fZ')
    evidence.mkdir(parents=True, exist_ok=True)
    archived = Sources(offline=True)
    sources, issues = [], []
    context = ssl.create_default_context(cafile=certifi.where())

    def fetch(target, filtered=False):
        captured = datetime.now(timezone.utc).isoformat(timespec='seconds')
        try:
            if live:
                time.sleep(.2)
                with urlopen(Request(target, headers={'User-Agent': 'UniMiData/0.1 (academic catalogue coverage audit)'}), timeout=25, context=context) as response:
                    raw, status, final = response.read(), response.status, response.url
                digest = hashlib.sha256(raw).hexdigest()
                path = evidence / (digest + '.html.gz')
                path.write_bytes(gzip.compress(raw, mtime=0))
                info = {'url': target, 'final_url': final, 'status': status, 'fetched_at': captured,
                        'sha256': digest, 'path': str(path.relative_to(ROOT))}
            else:
                document = archived.get(target)
                raw, info = document.raw, document.meta
            sources.append(info)
            if info['status'] != 200:
                raise ValueError(f"HTTP {info['status']}")
            doc = BeautifulSoup(raw, 'lxml')
            rows = [r for r in cards(doc, target) if r['academic_year'] is not None]
            totals = catalogue_totals(doc)
            wanted = sum(shown if filtered else total for shown, total in totals)
            if not totals or wanted != len({r['url'] for r in rows}):
                issues.append({'url': target, 'reason': 'Totale pubblicato assente o diverso dalle schede estratte', 'totals': totals, 'parsed': len(rows)})
            return doc, rows
        except Exception as exc:
            issues.append({'url': target, 'reason': str(exc)})
            return None, []

    catalogues, filters, catalogue_counts = [], {}, []
    options_by_catalogue = []
    for target, level in CATALOGUES.items():
        if level not in DEGREE_LEVELS:
            continue
        doc, rows = fetch(target)
        catalogues.append(rows)
        catalogue_counts.append({'url': target, 'courses': len(rows), 'academic_years': sorted({r['academic_year'] for r in rows})})
        options = {o['value']: text(o) for o in doc.select('select[name=facolta] option[value]') if o['value'] != 'All'} if doc else {}
        options_by_catalogue.append(set(options))
        if not options:
            issues.append({'url': target, 'reason': 'Nessun filtro facoltà trovato'})
        for code, name in options.items():
            _, selected = fetch(target + '?' + urlencode({'facolta': code}), filtered=True)
            filters.setdefault(name, []).extend(selected)
    if len(options_by_catalogue) == 2 and options_by_catalogue[0] != options_by_catalogue[1]:
        issues.append({'reason': 'I due cataloghi espongono insiemi diversi di filtri facoltà'})
    with sqlite3.connect(f'file:{OUTPUT}?mode=ro', uri=True) as db:
        report = compare(db, catalogues, filters)
    report.update(checked_at=now.isoformat(timespec='seconds'), mode='live' if live else 'snapshot',
                  catalogues=catalogue_counts, source_issues=issues, sources=sources,
                  scope='Percorsi di laurea, laurea magistrale e ciclo unico; esclusi insegnamenti e post laurea')
    bad = issues or report['missing_programmes'] or report['database_only_ids'] or report['without_faculty_in_source'] or any(
        r['missing_programmes'] or r['missing_relations'] or r['extra_relations'] or r['faculty_identity_matches'] != 1 for r in report['faculties'])
    report['status'] = 'needs_review' if bad else 'passed'
    path = evidence / 'report.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'sources'}, ensure_ascii=False, indent=2))
    print(f'Rapporto: {path.relative_to(ROOT)}')
    return report

"""Acquisizione delle pagine ufficiali e degli orari pubblicati."""
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .sources import Sources, assignment

ROOT = Path(__file__).resolve().parents[1]
RAW = Path('data/raw/2026-09-20')
AGENDA = 'https://orari.unimi.it/PortaleStudenti/'
CATALOGUES = [
    'https://www.unimi.it/index.php/it/corsi/corsi-di-laurea-triennali-e-magistrali-ciclo-unico',
    'https://www.unimi.it/it/corsi/corsi-di-laurea-magistrale',
]
PILOTS = {'informatica': ('FAA', 'F1X'), 'fisica': ('FAN', 'F63')}


def text(node):
    return node.get_text(' ', strip=True).replace('\ufeff', '') if node else ''


def canonical(url):
    return url.replace('/index.php/', '/')


def public_url(url):
    url = urljoin('https://www.unimi.it', url)
    if url.startswith('https://www.unimi.it/it/'):
        url = url.replace('https://www.unimi.it/it/', 'https://www.unimi.it/index.php/it/', 1)
    return url


def soup(raw):
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8')
        except UnicodeDecodeError:
            raw = raw.decode('windows-1252')
    return BeautifulSoup(raw, 'html.parser')


def catalogue_cards(doc):
    out = []
    for card in doc.select('.card-content'):
        link = card.select_one('.bp-title a[href]')
        if not link or '/corsi/laurea-' not in link['href']:
            continue
        label = text(card.select_one('.card_left'))
        centre = card.select_one('.card_center')
        language = centre.select(':scope > .field--label-inline') if centre else []
        out.append({'url': canonical(urljoin('https://www.unimi.it', link['href'])),
                    'name': text(link), 'level': 'single_cycle' if 'ciclo unico' in label else 'master' if 'magistrale' in label else 'bachelor',
                    'location': text(card.select_one('.sede')),
                    'language': text(language[0]) if language else None,
                    'delivery': text(card.parent.select_one('.caratterizzazione'))})
    return out


def collect(offline=False):
    sources = Sources(RAW, offline=offline)
    result = {'catalogues': [], 'units': [], 'programmes': {}, 'faculty_filters': [],
              'pilot_plans': [], 'courses': {}, 'agenda': {}, 'timetables': [], 'errors': []}

    def page(url):
        key, raw, meta = sources.get(url)
        if meta['status'] != 200:
            result['errors'].append({'url': url, 'status': meta['status']})
        return key, soup(raw)

    def save():
        (RAW / 'collection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')

    key, units = page('https://www.unimi.it/index.php/it/ateneo/uffici-e-strutture/facolta-e-scuole-elenco')
    for article in units.select('article'):
        a = article.select_one('.field--name-title a')
        if a and not text(a).startswith('CFI'):
            result['units'].append({'name': text(a), 'url': canonical(urljoin('https://www.unimi.it', a['href'])), 'source': key})

    for url in CATALOGUES:
        key, doc = page(url)
        cards = catalogue_cards(doc)
        if not cards:
            raise RuntimeError(f'Catalogo vuoto: {url}')
        result['catalogues'].append({'source': key, 'url': url, 'count': len(cards), 'text_counts': re.findall(r'\d+ corsi su \d+', text(doc))})
        for card in cards:
            result['programmes'][card['url']] = {**card, 'source': key, 'faculties': []}
        for opt in doc.select('select[name=facolta] option'):
            if opt['value'] == 'All':
                continue
            fk, filtered = page(url + '?facolta=' + opt['value'])
            filtered_cards = catalogue_cards(filtered)
            result['faculty_filters'].append({'source': fk, 'faculty': text(opt), 'count': len(filtered_cards)})
            for card in filtered_cards:
                if card['url'] not in result['programmes']:
                    raise ValueError(f'Corso nel filtro ma non nel catalogo: {card["url"]}')
                result['programmes'][card['url']]['faculties'].append({'name': text(opt), 'source': fk})
        print('Catalogo:', len(cards), url, flush=True)
    save()

    for i, (url, record) in enumerate(sorted(result['programmes'].items()), 1):
        key, doc = page(public_url(url))
        record['detail_source'] = key
        if i % 20 == 0:
            print(f'Schede lauree: {i}/{len(result["programmes"])}', flush=True)
            save()
    save()

    # Le versioni/coorti correnti sono collegate dalla scheda centrale.
    for slug in PILOTS:
        url = f'https://www.unimi.it/it/corsi/laurea-triennale/{slug}'
        record = result['programmes'][url]
        meta = sources.entries[record['detail_source']]
        doc = soup(Path(meta['path']).read_bytes())
        plan_urls = {canonical(urljoin(url, a['href'])) for a in doc.select('a[href]') if '/altre_offerte/aa-2026/2027/' in a['href']}
        if not plan_urls:
            raise ValueError(f'Nessun manifesto corrente per {slug}')
        for plan_url in sorted(plan_urls):
            key, plan = page(public_url(plan_url))
            result['pilot_plans'].append({'programme_url': url, 'url': plan_url, 'source': key})
            for a in plan.select('td.cdl-title a[href]'):
                link = canonical(urljoin(plan_url, a['href']))
                if '/2027/' in link or '/af2027' in link:
                    result['courses'].setdefault(link, {'url': link, 'title': text(a)})
    print('Manifesti pilota:', len(result['pilot_plans']), 'schede insegnamenti:', len(result['courses']), flush=True)
    save()
    for i, (url, record) in enumerate(sorted(result['courses'].items()), 1):
        key, doc = page(public_url(url))
        record['source'] = key
        if i % 30 == 0:
            print(f'Schede insegnamenti: {i}/{len(result["courses"])}', flush=True)
            save()
    save()

    key, raw, _ = sources.get(AGENDA + 'combo.php?sw=ec_&aa=2026&page=corsi')
    courses = assignment(raw, 'elenco_corsi')
    result['agenda']['courses_source'] = key
    # all_events=1 restituisce tutte le date pubblicate per il filtro;
    # la fase build applica la finestra esplicita del primo semestre.
    for slug, codes in PILOTS.items():
        for code in codes:
            key, raw, _ = sources.get(AGENDA + f'call_redis.php?key=UNIMI_2026_ec_elenco_anno2_{code}')
            groups = assignment(raw, 'elenco_anni')
            result['agenda'][code] = {'groups_source': key}
            for group in groups:
                params = {'view': 'easycourse', 'include': 'corso', '_lang': 'it', 'anno': '2026',
                          'scuola': 'ScienzeeTecnologie', 'corso': code, 'anno2[]': group['valore'],
                          'date': '21-09-2026', 'visualizzazione_orario': 'cal', 'all_events': '1'}
                key, raw, meta = sources.get(AGENDA + 'grid_call.php', params)
                payload = json.loads(raw)
                if not isinstance(payload.get('celle'), list):
                    raise ValueError(f'Risposta orari senza celle: {code} {group["valore"]}')
                result['timetables'].append({'source': key, 'code': code, 'programme': slug,
                                             'group': group['valore'], 'label': group['label'], 'count': len(payload['celle'])})
                print('Orari:', code, group['label'], len(payload['celle']), 'eventi', flush=True)
                save()
    save()
    print('Fonti archiviate:', len(sources.entries), 'errori HTTP:', len(result['errors']), flush=True)
    return result


if __name__ == '__main__':
    import argparse
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    collect(offline=args.offline)

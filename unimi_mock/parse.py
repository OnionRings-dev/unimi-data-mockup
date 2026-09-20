"""Parser delle strutture HTML ufficiali; nessuna inferenza per solo titolo."""
import json
import re
import unicodedata
from urllib.parse import urljoin

from .collect import canonical, text


def number(value):
    match = re.search(r'\d+(?:[.,]\d+)?', value or '')
    return float(match[0].replace(',', '.')) if match else None


def normalized_name(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', value.lower()).encode('ascii', 'ignore').decode())


def system_path(doc):
    tag = doc.select_one('[data-drupal-selector=drupal-settings-json]')
    if tag:
        return json.loads(tag.string)['path']['currentPath']
    return ''


def course_code(doc):
    path = system_path(doc)
    match = re.search(r'/af2027(0*[a-z0-9]+-[a-z0-9-]+)$', path, re.I)
    return match[1].lstrip('0').upper() if match else None


def field_value(doc, selector, label=None):
    value = text(doc.select_one(selector))
    if label and value.startswith(label):
        value = value[len(label):].strip()
    return value or None


def section(doc, title):
    for node in doc.select('.bp-title'):
        if text(node) == title:
            return text(node.find_next_sibling()) or None
    return None


def programme_details(doc):
    site = doc.select_one('.views-field-sito-corso a[href]')
    cls = field_value(doc, '.field--name-uof-cdsclass')
    version_ids = []
    for pane in doc.select('[id^=curr-2027]'):
        match = re.match(r'curr-20270*([a-z0-9]+of\d+)-', pane['id'])
        if match:
            version_ids.append(match[1].upper())
    return {'website_url': site['href'] if site else None,
            'ects': number(field_value(doc, '.views-field-cfu')),
            'duration_years': number(field_value(doc, '.views-field-durata-anni')),
            'degree_class': cls.split(' - ')[0] if cls else None,
            'version_keys': sorted(set(version_ids))}


def plan_rows(doc, base_url):
    plans = []
    for container in doc.select('[id^=curr-2027]'):
        match = re.fullmatch(r'curr-20270*([a-z0-9]+of\d+)-(.+)', container['id'], re.I)
        if not match or container['id'].endswith('-p'):
            continue
        panes = container.select('[id^=ugov-of-pd-year-af-]')
        if not panes:
            continue
        link = doc.find('a', href='#' + container['id'])
        label = text(link)
        rules = container.select_one('.ugov-of-pd-rules')
        if not rules:
            # Le regole sono pubblicate dopo i pannelli annuali e prima delle propedeuticità.
            candidates = [e for e in container.select('.titoletto') if 'regole di composizione' in text(e).lower()]
            rule_text = []
            if candidates:
                for sibling in candidates[0].next_siblings:
                    if getattr(sibling, 'get_text', None):
                        rule_text.append(text(sibling))
            rules_text = '\n'.join(rule_text) or None
        else:
            rules_text = text(rules)
        rows = []
        for pane in panes:
            nav = container.find('a', href='#' + pane['id'])
            year_match = re.search(r'Anno:\s*(\d+)', text(nav))
            study_year = int(year_match[1]) if year_match else None
            prefix = text(pane)[:180].lower()
            future = re.search(r'attivat[oa].*?(20\d\d)', prefix)
            state = 'future' if future else 'inactive' if 'non più attiva' in prefix else 'active'
            period = None
            for child in pane.children:
                if not getattr(child, 'name', None):
                    continue
                if 'titoletto' in child.get('class', []):
                    period = text(child)
                if child.name != 'table':
                    continue
                requirement = 'unknown'
                for tr in child.select('tbody > tr'):
                    if 'rowsubtitle' in tr.get('class', []):
                        raw_requirement = text(tr).lower()
                        requirement = 'mandatory' if raw_requirement == 'obbligatorio' else 'elective' if 'facoltativ' in raw_requirement else 'free_choice' if 'scelta' in raw_requirement else 'unknown'
                        continue
                    link = tr.select_one('td.cdl-title a[href]')
                    if not link:
                        continue
                    values = {td.get('data-title'): text(td) for td in tr.select('td[data-title]')}
                    rows.append({'url': canonical(urljoin(base_url, link['href'])), 'title': text(link),
                                 'ects': number(values.get('Crediti massimi')), 'hours': number(values.get('Ore totali')),
                                 'language': values.get('Lingua'), 'sectors': values.get('SSD', '').split(),
                                 'study_year': study_year, 'period': period, 'requirement': requirement,
                                 'state': state, 'activation_year': int(future[1]) if future else None})
        plans.append({'key': container['id'], 'version_key': match[1].upper(),
                      'curriculum_code': match[2], 'label': label or match[2], 'rules': rules_text, 'rows': rows})
    return plans


def course_details(doc):
    code = course_code(doc)
    if not code:
        raise ValueError('Scheda senza codice U-GOV verificabile')
    heading = text(doc.select_one('h1'))
    ssd = field_value(doc, '.views-field-ssd', 'SSD')
    common = {'code': code, 'title': heading,
              'ects': number(field_value(doc, '.views-label-cfu')),
              'total_hours': number(field_value(doc, '.views-label-ore-totali')),
              'language_label': field_value(doc, '.views-field-uof-lingua', 'Lingua'),
              'objectives': section(doc, 'Obiettivi formativi'), 'sectors': (ssd or '').split()}
    editions = []
    for h in doc.select('h3.js-views-accordion-group-header'):
        block = h.parent
        programs = {}
        for field, cls in [('syllabus', 'program'), ('prerequisites', 'prerequisite-text'),
                           ('assessment', 'exam'), ('teaching_methods', 'methods'), ('materials', 'material')]:
            node = block.select_one('.af-program-yes-' + cls)
            programs[field] = text(node.select_one('div')) if node else None
        teacher_links = block.select('.field--name-uof-person a[href], .af-edition-nomination a[href]')
        teachers = [{'name': text(a), 'url': canonical(urljoin('https://www.unimi.it', a['href'])),
                     'role': 'responsible' if a.find_parent(class_='field--name-uof-person') else 'lecturer'} for a in teacher_links]
        editions.append({'label': text(h), 'status': 'inactive' if 'Edizione non attiva' in text(block) else 'active',
                         'period_label': field_value(block, '.field--name-ugov-erogazione .field--item'),
                         'teachers': teachers, 'block': block, **programs})
    return common, editions

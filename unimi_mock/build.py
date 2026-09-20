"""Import offline, deterministico e atomico dalle fonti archiviate."""
import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from .collect import RAW, ROOT, PILOTS, canonical, soup, text
from .parse import (course_details, field_value, normalized_name, number,
                    plan_rows, programme_details)
from .sources import assignment

RELEASE = Path('data/releases/2026-09-20')
START = '2026-09-21'
END = '2027-01-15'


def utc(date, hour):
    local = datetime.strptime(date + ' ' + hour, '%d-%m-%Y %H:%M').replace(tzinfo=ZoneInfo('Europe/Rome'))
    return local.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%SZ')


def build(output=None):
    collection = json.loads((RAW / 'collection.json').read_text())
    manifest = json.loads((RAW / 'manifest.json').read_text())
    output = Path(output or RELEASE / 'unimi.sqlite')
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix('.building.sqlite')
    if temp.exists():
        temp.unlink()
    db = sqlite3.connect(temp)
    db.row_factory = sqlite3.Row
    db.executescript((ROOT / 'schema.sql').read_text())
    report = {'catalogue': collection['catalogues'], 'issues': [], 'unmatched_timetable_courses': [],
              'agenda_only_editions': [], 'auxiliary_activities': [], 'code_aliases': {},
              'outside_window_events': 0, 'timetable_requests': collection['timetables']}
    ids = defaultdict(dict)

    def insert(table, **data):
        columns = ','.join(data)
        return db.execute(f'INSERT INTO {table} ({columns}) VALUES ({",".join("?" for _ in data)})', list(data.values())).lastrowid

    def entity(table, key, **data):
        if key not in ids[table]:
            ids[table][key] = insert(table, source_key=key, **data)
        return ids[table][key]

    def bridge(table, **data):
        # Solo duplicati esatti sulle chiavi delle tabelle ponte.
        db.execute(f'INSERT INTO {table} ({",".join(data)}) VALUES ({",".join("?" for _ in data)}) ON CONFLICT DO NOTHING', list(data.values()))

    source_ids = {}
    for key, entry in sorted(manifest.items()):
        raw = Path(entry['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError(f'Hash non corrispondente: {entry["path"]}')
        source_ids[key] = insert('source_document', url=entry['url'], request_method=entry['method'],
                                request_parameters_json=json.dumps(entry['parameters'], sort_keys=True), fetched_at=entry['fetched_at'],
                                http_status=entry['status'], sha256=entry['sha256'], raw_path=entry['path'], parser_version='1.0',
                                notes=entry.get('error'))
    times = sorted(e['fetched_at'] for e in manifest.values())
    insert('snapshot', id=1, name='unimi-2026-2027-2026-09-20', academic_year=2026,
           acquisition_started_at=times[0], acquisition_finished_at=times[-1], simulation_date=START,
           notes='Fonti reali congelate; orari pubblicati nella finestra 21/09/2026–15/01/2027. Vedere coverage e manifest.json.')

    @lru_cache(maxsize=16)
    def document(key):
        return soup(Path(manifest[key]['path']).read_bytes())

    def unit_name(name):
        return normalized_name(name.removeprefix('Scuola di '))

    units = {}
    for record in collection['units']:
        uid = entity('academic_unit', record['url'], name=record['name'],
                     kind='school' if record['name'].startswith('Scuola') else 'faculty', url=record['url'], source_id=source_ids[record['source']])
        units[unit_name(record['name'])] = uid
    programmes = {}
    version_ids = {}
    for url, record in sorted(collection['programmes'].items()):
        key = record.get('detail_source', record['source'])
        doc = document(key)
        details = programme_details(doc)
        sid = source_ids[key]
        pid = entity('degree_programme', url, name=record['name'], level=record['level'],
                     website_url=details['website_url'] or url, source_id=source_ids[record['source']])
        programmes[url] = pid
        for affiliation in record['faculties']:
            name = unit_name(affiliation['name'])
            if name not in units:
                raise ValueError(f'Facoltà non riconosciuta: {name}')
            bridge('programme_unit', programme_id=pid, unit_id=units[name], role='coordinator', source_id=source_ids[affiliation['source']])
        # Codice/versione ricavati dall'identificativo del piano, non dal titolo.
        keys = details['version_keys'] or [url]
        for vk in keys:
            code = vk.split('OF')[0] if re.fullmatch(r'[A-Z0-9]+OF\d+', vk) else None
            vid = entity('programme_version', 'unimi:2026:' + vk, programme_id=pid, university_code=code,
                         degree_class=details['degree_class'], duration_years=details['duration_years'], ects=details['ects'],
                         language_label=record['language'], location_label=record['location'], delivery_mode=record['delivery'],
                         status='unknown', source_id=sid)
            version_ids[vk] = vid
        if manifest[key]['status'] != 200:
            report['issues'].append({'kind': 'programme_detail_unavailable', 'url': url})
    if len(units) != 10 or len(programmes) != sum(c['count'] for c in collection['catalogues']):
        raise ValueError('Conteggio catalogo non riconciliato')

    course_by_url, course_by_code, course_info, offerings = {}, {}, {}, defaultdict(list)
    catalogue_turns = defaultdict(list)
    teachers_by_name = defaultdict(set)
    teachers_by_code = {}

    def teacher_from_profile(name, url, sid):
        tid = entity('teacher', url, display_name=name, profile_url=url, source_id=sid)
        teachers_by_name[normalized_name(name)].add(tid)
        return tid

    for url, record in sorted(collection['courses'].items()):
        sid = source_ids[record['source']]
        doc = document(record['source'])
        try:
            common, editions = course_details(doc)
        except ValueError as exc:
            report['issues'].append({'kind': 'course_detail_unavailable', 'url': url, 'error': str(exc)})
            continue
        code = common['code']
        title = common['title']
        kind = 'final_exam' if 'prova finale' in title.lower() else 'internship' if any(t in title.lower() for t in ['tirocinio', 'stage']) else 'language' if any(t in title.lower() for t in ['lingua inglese', 'accertamento di lingua']) else 'teaching'
        cid = entity('course', 'unimi:' + code, university_code=code, title=title, kind=kind, source_id=sid)
        course_by_url[url] = cid
        course_by_url[canonical(manifest[record['source']]['final_url'])] = cid
        course_by_code[code] = cid
        course_info[cid] = common
        for sector in common['sectors']:
            bridge('course_sector', course_id=cid, sector_code=sector, source_id=sid)
        for edition in editions:
            okey = 'unimi:2026:' + code + ':' + edition['label']
            if okey in ids['course_offering']:
                continue
            oid = entity('course_offering', okey, course_id=cid, academic_year=2026, edition_label=edition['label'],
                         status=edition['status'], ects=common['ects'], total_hours=common['total_hours'],
                         language_label=common['language_label'], objectives=common['objectives'], website_url=url,
                         source_id=sid, **{f:edition[f] for f in ['period_label', 'syllabus', 'prerequisites', 'assessment', 'teaching_methods', 'materials']})
            offerings[cid].append((edition['label'], oid))
            aid = entity('teaching_activity', okey + ':general', offering_id=oid, title=title, kind='general',
                         group_label=edition['label'], source_id=sid)
            for teacher in edition['teachers']:
                tid = teacher_from_profile(teacher['name'], teacher['url'], sid)
                bridge('activity_teacher', activity_id=aid, teacher_id=tid, role=teacher['role'], source_id=sid)
            for idx, turn in enumerate(edition['block'].select('.af-edition-nomination-turn'), 1):
                label = text(turn.select_one('.af-edition-nomination-turn-label'))
                if not label:
                    continue
                kind = 'lab' if 'lab' in label.lower() else 'exercise' if 'esercit' in label.lower() else 'general'
                taid = entity('teaching_activity', okey + ':turn:' + str(idx), offering_id=oid,
                              title=title + ' — ' + label, kind=kind, group_label=label, source_id=sid)
                catalogue_turns[cid].append((label, taid, oid))
                for link in turn.select('a[href]'):
                    tid = teacher_from_profile(text(link), canonical(urljoin('https://www.unimi.it', link['href'])), sid)
                    bridge('activity_teacher', activity_id=taid, teacher_id=tid, role='lecturer', source_id=sid)
            # I dettagli dei moduli sono fratelli dell'intestazione nell'HTML ufficiale.
            for idx, module in enumerate(edition['block'].select('.af-edition-module'), 1):
                heading = module.select_one('h4, h5, strong, .af-edition-module-title')
                name = text(heading) or text(module).split(' CFU:')[0][:200]
                if name:
                    fragments = []
                    for sibling in module.next_siblings:
                        if getattr(sibling, 'name', None) == 'hr' or (getattr(sibling, 'get', None) and 'af-edition-module' in sibling.get('class', [])):
                            break
                        if getattr(sibling, 'get_text', None):
                            fragments.append(text(sibling))
                    detail = ' '.join(fragments)
                    credits = [float(v.replace(',', '.')) for v in re.findall(r'CFU:\s*(\d+(?:[.,]\d+)?)', detail)]
                    hours = [float(v.replace(',', '.')) for v in re.findall(r'(\d+(?:[.,]\d+)?)\s+ore', detail)]
                    mid = entity('course_module', okey + ':module:' + str(idx), offering_id=oid, title=name,
                                 ects=sum(credits) if credits else None, total_hours=sum(hours) if hours else None,
                                 source_id=sid)
                    entity('teaching_activity', okey + ':module:' + str(idx) + ':general', offering_id=oid,
                           module_id=mid, title=name, kind='general', source_id=sid)

    plan_ids, plan_course_ids = {}, defaultdict(list)
    plan_counts = defaultdict(int)
    for record in collection['pilot_plans']:
        doc = document(record['source'])
        sid = source_ids[record['source']]
        pid = programmes[record['programme_url']]
        heading = text(doc.select_one('h1'))
        cohort_label = re.split('immatricolati', heading, flags=re.I)[-1] if 'immatricolati' in heading.lower() else record['url'].split('immatricolati')[-1]
        cohort_years = re.findall(r'(20\d\d)(?=/)', cohort_label)
        cls = re.search(r'Classe\s+([^)]*)', heading)
        plans = plan_rows(doc, record['url'])
        if not plans:
            report['issues'].append({'kind': 'plan_missing', 'url': record['url']})
        for plan in plans:
            vk = plan['version_key']
            vid = version_ids.get(vk)
            values = {'cohort_from': int(cohort_years[0]) if cohort_years else None,
                      'cohort_to': int(cohort_years[-1]) if cohort_years else None}
            if vid:
                db.execute('UPDATE programme_version SET cohort_from=?, cohort_to=? WHERE id=?', (*values.values(), vid))
            else:
                vid = entity('programme_version', 'unimi:2026:' + vk, programme_id=pid, university_code=vk.split('OF')[0],
                             degree_class=cls[1] if cls else None, source_id=sid, **values)
                version_ids[vk] = vid
            spid = entity('study_plan', 'unimi:' + plan['key'], programme_version_id=vid, academic_year=2026,
                          curriculum_label=plan['label'], choice_rules=plan['rules'], source_id=sid)
            plan_ids[plan['key']] = spid
            for idx, row in enumerate(plan['rows']):
                cid = course_by_url.get(row['url'])
                if cid is None:
                    # La voce del piano rimane disponibile anche con scheda non acquisibile.
                    cid = entity('course', row['url'], title=row['title'], source_id=sid)
                    course_by_url[row['url']] = cid
                pcid = entity('plan_course', 'unimi:' + plan['key'] + ':row:' + str(idx), study_plan_id=spid,
                              course_id=cid, study_year=row['study_year'], period_label=row['period'], requirement=row['requirement'],
                              ects=row['ects'], activation_status=row['state'], expected_activation_year=row['activation_year'], source_id=sid)
                plan_course_ids[cid].append(pcid)
                plan_counts[pid] += 1
                for sector in row['sectors']:
                    bridge('course_sector', course_id=cid, sector_code=sector, source_id=sid)
                # Nessuna edizione corrente associata a un'annualità futura o disattivata.
                if row['state'] == 'active':
                    for _, oid in offerings[cid]:
                        bridge('plan_course_offering', plan_course_id=pcid, offering_id=oid, course_id=cid, source_id=sid)

    def link_offering(cid, oid, sid):
        for pcid in plan_course_ids[cid]:
            active = db.execute('SELECT activation_status FROM plan_course WHERE id=?', (pcid,)).fetchone()[0]
            if active == 'active':
                bridge('plan_course_offering', plan_course_id=pcid, offering_id=oid, course_id=cid, source_id=sid)

    def agenda_teachers(cell, sid):
        result = set()
        html = soup(cell.get('link_docente', '').encode())
        for a in html.select('a[href]'):
            params = parse_qs(urlsplit(a['href']).query)
            code = (params.get('docente') or [None])[0]
            name = text(a)
            if not code or not name:
                continue
            tid = teachers_by_code.get(code)
            if tid is None:
                candidates = teachers_by_name.get(normalized_name(name), set())
                if len(candidates) == 1:
                    tid = next(iter(candidates))
                    db.execute('UPDATE teacher SET university_code=? WHERE id=?', (code, tid))
                else:
                    tid = entity('teacher', 'agenda:teacher:' + code, university_code=code, display_name=name,
                                 profile_url=f'https://www.unimi.it/chiedove/schedaPersonaXML.jsp?matricola={code}', source_id=sid)
                    teachers_by_name[normalized_name(name)].add(tid)
                teachers_by_code[code] = tid
            result.add(tid)
        emails = {a['href'][7:].strip() for a in html.select('a[href^="mailto:"]') if a['href'][7:].strip().endswith('@unimi.it')}
        if len(result) == 1 and len(emails) == 1:
            db.execute('UPDATE teacher SET institutional_email=? WHERE id=?', (next(iter(emails)), next(iter(result))))
        return result

    seen_event_signatures = {}
    agenda_activities = {}
    for request in collection['timetables']:
        sid = source_ids[request['source']]
        payload = json.loads(Path(manifest[request['source']]['path']).read_bytes())
        for cell in payload['celle']:
            day = datetime.strptime(cell['data'], '%d-%m-%Y').strftime('%Y-%m-%d')
            if not START <= day <= END:
                report['outside_window_events'] += 1
                continue
            if cell.get('tipo') == 'chiusura_type':
                pid = programmes['https://www.unimi.it/it/corsi/laurea-triennale/' + request['programme']]
                bridge('calendar_closure', programme_id=pid, day=day, label=cell['nome'], source_id=sid)
                continue
            code = str(cell.get('CodiceGenerale', '')).upper()
            original_code = code
            # I suffissi del gestionale identificano turni: accettiamo la base
            # solo se esiste realmente nel catalogo U-GOV acquisito.
            base = code.split('_')[0]
            if code not in course_by_code and base in course_by_code:
                code = base
                report['code_aliases'][original_code] = code
            if not code:
                code = 'aux:' + str(cell['codice_insegnamento'])
            cid = course_by_code.get(code)
            if cid is None:
                auxiliary = code.startswith('aux:')
                cid = entity('course', 'agenda:course:' + code, university_code=None if auxiliary else code,
                             title=cell['nome_insegnamento'], kind='other' if auxiliary else 'teaching', source_id=sid)
                course_by_code[code] = cid
                report['auxiliary_activities' if auxiliary else 'unmatched_timetable_courses'].append({'code': code, 'title': cell['nome_insegnamento'], 'programme': request['programme']})
            activity_key = 'agenda:2026:' + str(cell['codice_insegnamento'])
            name = cell['nome_insegnamento']
            kind_label = (cell.get('tipo', '') + ' ' + name).lower()
            kind = 'lab' if 'lab' in kind_label else 'exercise' if 'esercit' in kind_label else 'lecture'
            if activity_key not in agenda_activities:
                candidates = offerings[cid]
                group = re.search(r'(?:gruppo|edizione)\s*(\d+)', name, re.I)
                matches = [(label, oid) for label, oid in candidates if group and re.search(r'\b' + group[1] + r'\b', label)]
                turn = re.search(r'(?:lab\.?\s*(?:turno\s*)?|turno\s+)([A-Z])\b', name, re.I)
                turn_matches = [(aid, oid) for label, aid, oid in catalogue_turns[cid]
                                if turn and re.search(r'\b' + turn[1] + r'\b', label, re.I) and 'lab' in label.lower()]
                if kind == 'lab' and turn_matches:
                    agenda_activities[activity_key] = sorted({aid for aid, _ in turn_matches})
                    for _, oid in turn_matches:
                        link_offering(cid, oid, sid)
                elif len(matches) == 1:
                    oid = matches[0][1]
                elif len(candidates) == 1:
                    oid = candidates[0][1]
                else:
                    oid = entity('course_offering', activity_key + ':offering', course_id=cid, academic_year=2026,
                                 edition_label=name, status='active', source_id=sid)
                    report['agenda_only_editions'].append({'code': code, 'activity': name})
                if activity_key not in agenda_activities:
                    aid = entity('teaching_activity', activity_key, offering_id=oid, title=name, kind=kind,
                                 group_label=name, source_id=sid)
                    agenda_activities[activity_key] = [aid]
                    link_offering(cid, oid, sid)
            aids = agenda_activities[activity_key]
            pid = programmes['https://www.unimi.it/it/corsi/laurea-triennale/' + request['programme']]
            year = request['group'].rsplit('|', 1)[-1]
            for aid in aids:
                bridge('activity_audience', activity_id=aid, programme_id=pid, programme_code=request['code'],
                       study_year=int(year) if year.isdigit() and int(year) > 0 else None,
                       group_code=request['group'], group_label=request['label'], source_id=sid)
            begin, end = utc(cell['data'], cell['ora_inizio']), utc(cell['data'], cell['ora_fine'])
            original_id = str(cell['id'])
            event_key = 'agenda:2026:event:' + original_id
            signature = (begin, end, str(cell.get('Annullato')))
            if event_key in seen_event_signatures and seen_event_signatures[event_key] != signature:
                raise ValueError(f'Evento con identificativo ambiguo: {event_key}')
            seen_event_signatures[event_key] = signature
            room_codes = cell.get('codice_aula')
            online = cell.get('link_lezione_online')
            urls = re.findall(r'https?://[^\s"<>]+', online) if isinstance(online, str) else []
            lid = entity('lesson', event_key, source_event_id=original_id, starts_at=begin, ends_at=end,
                         status='cancelled' if str(cell.get('Annullato')) == '1' else 'scheduled',
                         delivery_mode='hybrid' if room_codes and urls else 'in_person' if room_codes else 'online' if urls else 'unknown',
                         online_url=urls[0] if urls else None,
                         notes=text(soup((cell.get('notes') or '').encode())) or None, source_id=sid)
            for aid in aids:
                bridge('lesson_activity', lesson_id=lid, activity_id=aid, source_id=sid)
            for tid in agenda_teachers(cell, sid):
                bridge('lesson_teacher', lesson_id=lid, teacher_id=tid, source_id=sid)
                for aid in aids:
                    bridge('activity_teacher', activity_id=aid, teacher_id=tid, role='lecturer', source_id=sid)
            # La fonte può elencare più aule: non memorizzarle come un'unica aula.
            rooms = str(room_codes or '').split(',')
            labels = cell.get('aula', '')
            labels = labels if isinstance(labels, list) else re.split(r'<br\s*/?>|\s*;\s*', labels)
            if len(rooms) > 1 and len(labels) != len(rooms):
                report['issues'].append({'kind': 'room_labels_ambiguous', 'event_id': original_id, 'codes': room_codes})
            for idx, room_code in enumerate(rooms):
                room_code = room_code.strip()
                if not room_code:
                    continue
                label = text(soup(labels[idx].encode())) if idx < len(labels) else room_code
                site_code = room_code.split('#')[0] if '#' in room_code else str(cell.get('codice_sede', ''))
                site_name = re.search(r'\[([^]]+)\]', label)
                bid = None
                if site_code:
                    bid = entity('building', 'agenda:site:' + site_code, university_code=site_code,
                                 name=site_name[1] if site_name else 'Sede ' + site_code, source_id=sid)
                rid = entity('room', 'agenda:room:' + room_code, building_id=bid, university_code=room_code, name=label, source_id=sid)
                bridge('lesson_room', lesson_id=lid, room_id=rid, source_id=sid)

    # Copertura esplicita: il catalogo è completo rispetto ai due elenchi ufficiali;
    # la disponibilità delle schede e dei calendari è un ambito distinto.
    insert('coverage', domain='catalogue', academic_year=2026, status='complete', expected_count=len(programmes),
           collected_count=len(programmes), counting_unit='lauree negli elenchi ufficiali',
           notes='99 triennali/ciclo unico + 82 magistrali; 10 strutture; filtri di facoltà riconciliati. Versioni storiche approfondite solo per i due corsi pilota.')
    for url, pid in programmes.items():
        pilot = next((slug for slug in PILOTS if url.endswith('/laurea-triennale/' + slug)), None)
        pilot_plans = [p for p in collection['pilot_plans'] if p['programme_url'] == url]
        expected_rows = sum(len(plan['rows']) for p in pilot_plans for plan in plan_rows(document(p['source']), p['url'])) if pilot else None
        missing_details = db.execute('''SELECT count(DISTINCT c.id) FROM course c
            JOIN plan_course pc ON pc.course_id=c.id JOIN study_plan sp ON sp.id=pc.study_plan_id
            JOIN programme_version pv ON pv.id=sp.programme_version_id
            WHERE pv.programme_id=? AND c.university_code IS NULL''', (pid,)).fetchone()[0]
        teaching_complete = pilot and len(pilot_plans) == 3 and expected_rows == plan_counts[pid] and not missing_details
        insert('coverage', programme_id=pid, domain='teaching', academic_year=2026,
               status='complete' if teaching_complete else 'partial' if pilot else 'not_collected',
               expected_count=expected_rows, collected_count=plan_counts[pid] if pilot else 0,
               counting_unit='voci dei piani didattici',
               notes='Tre manifesti/coorti, tutte le voci e le schede collegate. Completezza rispetto alle fonti pubblicate; programmi e docenti non pubblicati restano NULL. Annualità future/inattive conservate come tali.' if pilot else 'Catalogo soltanto: dettaglio insegnamenti fuori dal perimetro pilota.')
        reqs = [r for r in collection['timetables'] if r['programme'] == pilot] if pilot else []
        expected_filters = 0
        if pilot:
            for code in PILOTS[pilot]:
                gkey = collection['agenda'][code]['groups_source']
                expected_filters += len(assignment(Path(manifest[gkey]['path']).read_bytes(), 'elenco_anni'))
        timetable_complete = pilot and len(reqs) == expected_filters and all(manifest[r['source']]['status'] == 200 for r in reqs)
        insert('coverage', programme_id=pid, domain='timetable', academic_year=2026, starts_on=START, ends_on=END,
               status='complete' if timetable_complete else 'partial' if pilot else 'not_collected', expected_count=expected_filters if pilot else None,
               collected_count=len(reqs) if pilot else 0, counting_unit='filtri anno/curriculum/gruppo dell’Agenda',
               notes='Tutte le occorrenze restituite da all_events=1 entro la finestra. Fotografia del pubblicato: nessuna garanzia sulle lezioni non ancora pubblicate.' if pilot else 'Orari non raccolti per questa laurea.')

    db.commit()
    if db.execute('PRAGMA integrity_check').fetchall()[0][0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Integrità SQLite non superata')
    orphan = db.execute('SELECT count(*) FROM lesson l WHERE NOT EXISTS (SELECT 1 FROM lesson_activity la WHERE la.lesson_id=l.id)').fetchone()[0]
    if orphan:
        raise ValueError('Lezioni senza attività')
    report['counts'] = {row[0]: db.execute('SELECT count(*) FROM ' + row[0]).fetchone()[0]
                        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()}
    report['checks'] = {'integrity_check': 'ok', 'foreign_key_check': [], 'lessons_without_activity': orphan}
    report['coverage'] = [dict(row) for row in db.execute('''SELECT p.name AS programme, c.* FROM coverage c
        LEFT JOIN degree_programme p ON p.id=c.programme_id WHERE c.status <> 'not_collected' ORDER BY c.id''')]
    report['quality'] = {
        'lessons_without_room': db.execute('SELECT count(*) FROM lesson l WHERE NOT EXISTS (SELECT 1 FROM lesson_room r WHERE r.lesson_id=l.id)').fetchone()[0],
        'lessons_without_teacher': db.execute('SELECT count(*) FROM lesson l WHERE NOT EXISTS (SELECT 1 FROM lesson_teacher t WHERE t.lesson_id=l.id)').fetchone()[0],
        'active_offerings_without_syllabus': db.execute("SELECT count(*) FROM course_offering WHERE status='active' AND syllabus IS NULL").fetchone()[0],
        'programme_versions_without_duration': db.execute('SELECT count(*) FROM programme_version WHERE duration_years IS NULL').fetchone()[0],
    }
    db.close()
    temp.replace(output)
    report['database'] = str(output)
    report['database_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
    report['schema_sha256'] = hashlib.sha256((ROOT / 'schema.sql').read_bytes()).hexdigest()
    report['parser_version'] = '1.0'
    report['acquisition_started_at'], report['acquisition_finished_at'] = times[0], times[-1]
    report['academic_year'] = '2026/2027'
    report['timetable_window'] = {'starts_on': START, 'ends_on': END, 'timezone': 'Europe/Rome'}
    output.with_name('manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['counts'], ensure_ascii=False, indent=2))
    print('Problemi da verificare:', len(report['issues']), 'codici orari senza piano:', len(report['unmatched_timetable_courses']))
    return report


if __name__ == '__main__':
    import argparse
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    os.chdir(ROOT)
    build(args.output)

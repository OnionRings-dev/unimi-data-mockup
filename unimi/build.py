"""Costruisce un SQLite atomico dalle fonti locali, con identità e provenienza."""
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path
from html import unescape

from .collect import CATALOGUES, COLLECTION, DIRECTORY_CATEGORIES, directory_page_number
from .parse import (BASE, academic_year, cards, course_code, department_teaching, editions,
                    directory_rows, field, identity, links, number, pager, path, person_extras, plan_cells, plan_rows, properties, text, url)
from .sources import RAW, ROOT, Document, Sources, assignment, dumps, read_document

OUTPUT = ROOT / "data/unimi.sqlite"


class Store:
    def __init__(self, db, aliases=None):
        self.db = db
        self.aliases = aliases or {}
        self.plan_audit = {"published": 0, "parsed": 0}

    def canonical(self, target):
        return self.aliases.get(target, target)

    def id(self, kind, key):
        value = kind + ":" + self.canonical(key)
        return kind + ":" + hashlib.sha256(value.encode()).hexdigest()[:32]

    def entity(self, kind, key, name, source, *, code=None, year=None, target=None, props=None, detail=False):
        key = self.canonical(key)
        entity_id = self.id(kind, key)
        if kind == "person" and code is None:
            match = re.search(r"/person(\d+)$", key)
            code = match[1] if match else None
        name = name.strip() or code or key.rsplit("/", 1)[-1]
        normalised = {k: v for k, v in (props or {}).items() if k not in {"fields", "raw"}}
        self.db.execute("""INSERT INTO entity(id,kind,name,code,academic_year,url,properties,source_id)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING""",
                        (entity_id, kind, name, code, year, target, dumps(normalised), source))
        if detail:
            previous = json.loads(self.db.execute("SELECT properties FROM entity WHERE id=?", (entity_id,)).fetchone()[0])
            previous.update({k: v for k, v in normalised.items() if v is not None})
            self.db.execute("""UPDATE entity SET name=?,code=coalesce(?,code),academic_year=coalesce(?,academic_year),
                url=coalesce(?,url),properties=?,source_id=? WHERE id=?""",
                            (name, code, year, target, dumps(previous), source, entity_id))
        self.db.execute("INSERT OR IGNORE INTO identifier VALUES(?,?)", (key, entity_id))
        if target:
            self.db.execute("INSERT OR IGNORE INTO identifier VALUES(?,?)", (target, entity_id))
        if props:
            self.db.execute("INSERT OR REPLACE INTO observation VALUES(?,?,?)", (entity_id, source, dumps(props)))
        return entity_id

    def relate(self, subject, predicate, obj, source, props=None):
        if subject != obj:
            payload = dumps([subject, predicate, obj, source, props or {}])
            relation_id = hashlib.sha256(payload.encode()).hexdigest()[:32]
            self.db.execute("INSERT OR IGNORE INTO relation VALUES(?,?,?,?,?,?)",
                            (relation_id, subject, predicate, obj, source, dumps(props or {})))

    def ref(self, kind, target, name, source):
        return self.entity(kind, target, name, source, target=target, year=academic_year(target))


def unit_kind(name):
    if name.startswith("Dipartimento"):
        return "department"
    if name.startswith("Scuola") and "specializzazione" not in name.lower():
        return "school"
    if name.startswith("CFI") or "formazione insegnanti" in name.lower():
        return "organisation"
    return "faculty"


def make_course(store, target, name, source, *, code=None, year=None, props=None, detail=False):
    if "/catalogo-degli-insegnamenti-la-formazione-dottorale/" in target:
        return store.entity("doctoral_course", target, name, source, year=year or academic_year(target), target=target, props=props, detail=detail)
    canonical = store.canonical(target)
    match = re.search(r"/af(20\d\d)0*([a-z][a-z0-9]*-[a-z0-9-]+)$", canonical, re.I)
    if match:
        code, year = match[2].upper(), int(match[1]) - 1
    if not code:
        return store.entity("course_offering", target, name, source, target=target,
                            year=year or academic_year(canonical), props=props, detail=detail)
    core = store.entity("course", "ugov:" + code, name, source, code=code, detail=detail)
    offering = store.entity("course_offering", target, name, source, code=code, year=year,
                           target=target, props=props, detail=detail)
    store.relate(offering, "edition_of", core, source)
    return offering


def import_agenda(store, documents):
    def get(name):
        return next((d for u, j, d in documents if j["kind"] == name), None)
    doc = get("agenda_rooms")
    if doc:
        groups = assignment(doc.raw, "elenco_aule")
        for site_code, rooms in groups.items():
            for row in rooms:
                site = store.entity("site", "agenda:" + str(site_code), row["sede_name"], doc.key,
                                    code=str(site_code), props={"namespace": "agenda"})
                room = store.entity("room", "agenda:" + row["valore"], row["label"], doc.key,
                                    code=row["valore"], props={"capacity": row.get("capacity"), "raw": row}, detail=True)
                store.relate(room, "located_in", site, doc.key)
    doc = get("agenda_corsi")
    if doc:
        for row in assignment(doc.raw, "elenco_corsi"):
            store.entity("agenda_programme", "agenda:" + row["valore"], row["label"], doc.key,
                         code=row["valore"], year=2026, props=row, detail=True)
    doc = get("agenda_docenti")
    if doc:
        for row in assignment(doc.raw, "elenco_docenti"):
            teacher = store.entity("agenda_teacher", "agenda:" + str(row["valore"]), row["label"], doc.key,
                                   code=str(row["valore"]), year=2026, props=row, detail=True)
            for p in row.get("teacher_cdl", []):
                programme = store.entity("agenda_programme", "agenda:" + p["CorsoLaureaCodice"], p["CorsoLaureaNome"], doc.key,
                                        code=p["CorsoLaureaCodice"], year=2026)
                store.relate(teacher, "listed_in", programme, doc.key, {"groups": p.get("elencoCurriculum", [])})
    doc = get("agenda_attivita")
    if doc:
        for row in assignment(doc.raw, "elenco_attivita"):
            store.entity("agenda_activity", "agenda:" + row["valore"], row.get("nome_insegnamento") or row["label"], doc.key,
                         code=row["valore"], year=2026, props=row, detail=True)
    for target, job, doc in documents:
        if job["kind"] != "agenda_groups":
            continue
        programme = store.entity("agenda_programme", "agenda:" + job["programme_code"], job["programme_code"], doc.key,
                                code=job["programme_code"], year=2026)
        for group in assignment(doc.raw, "elenco_anni"):
            for row in group.get("elenco_insegnamenti", []):
                activity = store.entity("agenda_activity", "agenda:" + row["valore"], row["label"], doc.key,
                                       code=row["valore"], year=2026, props=row)
                store.relate(programme, "includes", activity, doc.key,
                             {"group_code": group["valore"], "group_label": group["label"]})
    doc = get("room_metadata")
    if doc:
        for site_code, by_room in json.loads(doc.raw)["area_rooms"].items():
            for code, row in by_room.items():
                code = str(row.get("room_code") or code)
                site = store.entity("site", "agenda:" + str(row.get("area_code") or site_code),
                                    row.get("area") or str(site_code), doc.key,
                                    code=str(row.get("area_code") or site_code), props={"namespace": "agenda"})
                capacity = number(str(row.get("capacity", "")))
                props = {"fields": row, "address": row.get("address") or None,
                         "metadata_collected": True, "capacity": int(capacity) if capacity is not None and capacity.is_integer() else None,
                         "site_map_url": map_url(row.get("google_map_link")),
                         "room_map_url": map_url(row.get("aula_google_map_link")),
                         "room_page_url": row.get("aula_link") or None,
                         "plan_image_reference": row.get("map_image") or None}
                point = published_room_point(row)
                if point:
                    props.update(latitude=point[0], longitude=point[1], coordinate_source_id=doc.key,
                                 coordinate_precision="not_specified_by_source")
                room = store.entity("room", "agenda:" + code, row.get("room_name") or code, doc.key,
                                    code=code, props=props, detail=True)
                store.relate(room, "located_in", site, doc.key)


def map_url(value):
    if not isinstance(value, str) or not value.strip():
        return None
    match = re.search(r'''<iframe\b[^>]*\bsrc=["']([^"']+)["']''', value, re.I)
    return unescape(match[1]) if match else value if value.startswith(("https://", "http://")) else None


def published_room_point(row):
    try:
        latitude = float(str(row.get("latitude")).replace(",", "."))
        longitude = float(str(row.get("longitude")).replace(",", "."))
        if (math.isfinite(latitude) and math.isfinite(longitude)
                and -90 <= latitude <= 90 and -180 <= longitude <= 180 and (latitude, longitude) != (0, 0)):
            return latitude, longitude
    except (TypeError, ValueError):
        pass
    return None


def import_catalogues(store, documents):
    for target, job, document in documents:
        if job["kind"] not in {"catalogue", "faculty_filter", "unit_index"}:
            continue
        doc = document.soup()
        if job["kind"] == "unit_index":
            for a in doc.select("article .field--name-title a[href]"):
                name = text(a)
                kind = "department" if job["unit_kind"] == "department" else unit_kind(name)
                store.ref(kind, url(a["href"]), name, document.key)
        elif job["kind"] == "catalogue":
            for card in cards(doc, target):
                if card["academic_year"] is None:
                    continue
                level = job["level"]
                if level == "bachelor_or_single_cycle":
                    level = "single_cycle" if "ciclo unico" in card["level_label"].lower() else "bachelor"
                store.entity("programme", card["url"], card["name"], document.key,
                             year=card["academic_year"], target=card["url"], props={"level": level, "summary": card["summary"]}, detail=True)
    # Nomi delle facoltà confrontati solo all'interno dell'elenco ufficiale.
    faculties = {}
    for entity_id, name in store.db.execute("SELECT id,name FROM entity WHERE kind IN ('faculty','school')"):
        faculties[name] = entity_id
        if name.startswith("Scuola di "):
            faculties[name.removeprefix("Scuola di ")] = entity_id
    for target, job, document in documents:
        if job["kind"] != "faculty_filter":
            continue
        faculty = faculties.get(job["faculty_name"])
        if faculty:
            for card in cards(document.soup(), target):
                entity = store.id("programme", card["url"])
                if store.db.execute("SELECT 1 FROM entity WHERE id=?", (entity,)).fetchone():
                    store.relate(entity, "belongs_to", faculty, document.key)


def import_structure(store, target, job, document, doc):
    name = text(doc.select_one("h1")) or job.get("name", target)
    key = identity(doc, target)
    kind = "department" if job.get("unit_kind") == "department" else unit_kind(name)
    parent = store.entity(kind, key, name, document.key, target=target,
                          props={"fields": properties(doc), "detail_collected": True}, detail=True)
    for link, label in links(doc, "/ugov/ou-structure/").items():
        # Solo collegamenti nel contenuto della scheda, non la navigazione.
        if link == target or "/dipartimento-" not in link:
            continue
        child = store.ref("department", link, label, document.key)
        store.relate(child, "belongs_to", parent, document.key)


def import_programme(store, target, job, document, doc):
    name = text(doc.select_one("h1")) or job.get("name", target)
    main = doc.select_one(".region-content") or doc
    props = {"fields": properties(main), "detail_collected": True,
             "credits": number(field(doc, ".views-field-cfu")),
             "duration_years": number(field(doc, ".views-field-durata-anni")),
             "website_urls": [a["href"] for a in doc.select(".views-field-sito-corso a[href]")]}
    kind = "programme_offering" if job["kind"] == "offering" else "programme"
    key = identity(doc, target)
    match = re.search(r"/cdsi(20\d\d)0*([a-z0-9]+of\d+)$", key, re.I)
    programme = store.entity(kind, key, name, document.key, year=academic_year(key) or job.get("academic_year"),
                             code=match[2].upper() if match else None, target=target, props=props, detail=True)
    for link, label in links(main, "/ugov/of/cdsi").items():
        if store.canonical(link) == key:
            continue
        offering = store.ref("programme_offering", link, label, document.key)
        if kind == "programme":
            store.relate(offering, "version_of", programme, document.key)
    if kind == "programme":
        for link, label in links(main, "/altre_offerte/aa-").items():
            if link in store.aliases:
                offering = store.ref("programme_offering", link, label, document.key)
                store.relate(offering, "version_of", programme, document.key)
    for link, label in links(main, "/ugov/ou-structure/dipartimento").items():
        department = store.ref("department", link, label, document.key)
        store.relate(programme, "belongs_to", department, document.key)
    for a in main.select(".views-field-uof-person a[href], .field--name-uof-person a[href]"):
        person = store.ref("person", url(a["href"]), text(a), document.key)
        store.relate(person, "responsible_for", programme, document.key, {"source_field": "uof-person"})
    plans = plan_rows(doc)
    store.plan_audit["published"] += len(plan_cells(doc))
    store.plan_audit["parsed"] += sum(len(plan["rows"]) for plan in plans)
    for plan in plans:
        plan_id = store.entity("study_plan", key + "#" + plan["key"], plan["name"], document.key,
                               code=plan["curriculum_code"], year=plan["year"], props={k: v for k, v in plan.items() if k != "rows"})
        store.relate(plan_id, "part_of", programme, document.key)
        for row in plan["rows"]:
            if row["url"]:
                course = make_course(store, row["url"], row["name"], document.key)
            else:
                entry_key = "plan-entry:" + key + "#" + row["source_key"]
                entry_props = {"identity_scope": "published_plan_entry", "source_entry_collected": True,
                               "detail_collected": False, "fields": row["fields"],
                               "credits": number(row["fields"].get("Crediti") or row["fields"].get("Crediti massimi")),
                               "hours": number(row["fields"].get("Ore totali")), "language": row["fields"].get("Lingua")}
                core = store.entity("course", entry_key, row["name"], document.key, props={"identity_scope": "published_plan_entry"})
                course = store.entity("course_offering", entry_key, row["name"], document.key,
                                      year=plan["year"], props=entry_props)
                store.relate(course, "edition_of", core, document.key)
            store.relate(plan_id, "includes", course, document.key, {k: v for k, v in row.items() if k not in {"url", "name"}})
            for teacher in row["teachers"]:
                person = store.ref("person", teacher["url"], teacher["name"], document.key)
                store.relate(course, "taught_by", person, document.key, {"scope": "published_plan_row"})


def import_department_index(store, target, job, document, doc):
    department = store.ref("department", job["department_url"], job["department_url"].rsplit("/", 1)[-1], document.key)
    for item in department_teaching(doc):
        course = make_course(store, item["url"], item["name"], document.key)
        store.relate(course, "listed_in", department, document.key)
        # L'indice può elencare più edizioni nello stesso riquadro. La relazione
        # qui è al livello attività annuale; le edizioni si leggono nella scheda.
        for link, label in item["teachers"].items():
            person = store.ref("person", link, label, document.key)
            store.relate(course, "taught_by", person, document.key, {"scope": "annual_activity"})
        for link, label in item["offerings"].items():
            offering = store.ref("programme_offering", link, label, document.key)
            store.relate(offering, "includes", course, document.key)


def import_phd_index(store, target, job, document, doc):
    for row in doc.select("tbody tr"):
        a = row.select_one("td.views-field-title a[href]")
        if not a:
            continue
        link = url(a["href"])
        activity = store.entity("doctoral_course", link, text(a), document.key, year=academic_year(link), target=link)
        for p in row.select("td.views-field-title-1 a[href]"):
            programme = store.ref("programme", url(p["href"]), text(p), document.key)
            store.relate(programme, "includes", activity, document.key)
        for p in row.select("a[href*='/ugov/person/'],a[href*='/ugov/rubrica/']"):
            person = store.ref("person", url(p["href"]), text(p), document.key)
            store.relate(activity, "taught_by", person, document.key, {"role": "responsible"})


def import_course(store, target, job, document, doc):
    code, year = course_code(doc)
    year = year or academic_year(identity(doc, target))
    name = text(doc.select_one("h1")) or job.get("name", target)
    kind = job["kind"]
    if not code and kind == "course":
        name = job.get("name") or name
    props = {"fields": properties(doc.select_one(".region-content") or doc),
             "detail_collected": bool(code) or kind == "doctoral_course",
             "credits": number(field(doc, ".views-field-cfu")),
             "hours": number(field(doc, ".views-field-ore-totali")),
             "language": field(doc, ".views-field-uof-lingua")}
    if kind == "doctoral_course":
        course = store.entity("doctoral_course", identity(doc, target), name, document.key,
                              target=target, year=academic_year(target), props=props, detail=True)
    else:
        course = make_course(store, target, name, document.key, code=code, year=year, props=props, detail=bool(code))
    for edition in editions(doc):
        edition_id = store.entity("edition", store.canonical(target) + "#edition-" + str(edition["index"]),
                                  edition["name"], document.key, year=year,
                                  props={k: v for k, v in edition.items() if k != "teachers"}, detail=True)
        store.relate(edition_id, "part_of", course, document.key)
        for teacher in edition["teachers"]:
            person = store.ref("person", teacher["url"], teacher["name"], document.key)
            store.relate(edition_id, "taught_by", person, document.key, {"role": teacher["role"]})


def directory_valid(doc, job):
    chosen = doc.select_one('select[name="ur_tipi_ruoli_target_id"] option[selected]')
    current = doc.select_one('.view-chi-e-dove a[aria-current="page"]')
    page_label = re.findall(r'\d+', text(current))
    current_page = int(page_label[-1]) - 1 if page_label else 0
    return (chosen is not None and chosen.get('value') == job['category_code']
            and current_page == job['page'] and doc.select_one('.view-chi-e-dove') is not None
            and all(DIRECTORY_CATEGORIES[job['category_code']] in row['categories']
                    for row in directory_rows(doc)))


def import_directory(store, target, job, document, doc):
    if not directory_valid(doc, job):
        return
    for row in directory_rows(doc):
        key = store.id('person', row['url'])
        previous = store.db.execute('SELECT properties FROM entity WHERE id=?', (key,)).fetchone()
        categories = set(json.loads(previous[0]).get('directory_categories', [])) if previous else set()
        categories.update(row['categories'])
        store.entity('person', row['url'], row['name'], document.key, target=row['url'], detail=True,
                     props={'directory_categories': sorted(categories)})


def import_person(store, target, job, document, doc):
    if not path(doc).startswith(("ugov/rubrica/person", "ugov/person/")):
        # Una pagina di errore HTTP 200 non deve diventare un profilo personale.
        return
    name = text(doc.select_one("h1")) or job.get("name", target)
    key = identity(doc, target)
    email_label = doc.select_one(".icon.mail")
    email_scope = email_label.find_next_sibling() if email_label else None
    email_node = email_scope.select_one("[data-cfemail]") if email_scope else None
    email = None
    if email_node:
        try:
            data = bytes.fromhex(email_node["data-cfemail"])
            email = bytes(b ^ data[0] for b in data[1:]).decode("utf-8") if len(data) > 1 else None
        except (ValueError, UnicodeError):
            email = None
    else:
        a = email_scope.select_one('a[href^="mailto:"]') if email_scope else None
        email = a["href"][7:].split("?")[0] if a else None
    phone = doc.select_one(".icon.phone")
    website = doc.select_one(".icon.globe a[href]")
    photo = doc.select_one(".foto-persona img[src]")
    reception = next((text(card) for card in doc.select(".card-content") if text(card.select_one(".bp-title")) == "Ricevimento"), None)
    extras, teachings = person_extras(doc)
    person = store.entity("person", key, name, document.key, target=target,
                          code=key.rsplit("/person", 1)[-1] if re.search(r"/person\d+$", key) else None,
                          props={**extras, "fields": properties(doc.select_one(".ugov-rubrica") or doc),
                                 "role": field(doc, ".field--name-ur-ruolo"),
                                 "email": email, "address": text(doc.select_one(".ugov-indirizzo")) or None,
                                 "phone": (text(phone.find_next_sibling()) or None) if phone else None,
                                 "website_url": website["href"] if website else None,
                                 "photo_url": photo["src"] if photo else None,
                                 "sector": field(doc, ".field--name-ur-ssd"), "reception": reception,
                                 "detail_collected": True}, detail=True)
    for teaching in teachings:
        activity = make_course(store, teaching["url"], teaching["name"], document.key,
                               year=teaching["academic_year"])
        store.relate(activity, "taught_by", person, document.key,
                     {"scope": "profile_teaching_list", "academic_year": teaching["academic_year"]})
    for a in doc.select(".field--name-ur-ou-afferenza a[href]"):
        target_unit = url(a["href"])
        existing = store.db.execute("SELECT entity_id FROM identifier WHERE value=?", (store.canonical(target_unit),)).fetchone()
        kind = "department" if text(a).startswith("Dipartimento") else "organisation"
        unit = existing[0] if existing else store.ref(kind, target_unit, text(a), document.key)
        store.relate(person, "member_of", unit, document.key)


def import_site(store, target, job, document, doc):
    name = text(doc.select_one("h1")) or job.get("name", target)
    main = doc.select_one(".region-content") or doc
    postal = main.find(string=re.compile(r"^\s*\d{5}\s+[^\d\s]"))
    postal_label = str(postal).strip() if postal else None
    address = text(doc.select_one(".ugov-indirizzo"))
    if not address and postal:
        address = text(postal.parent.parent)
    site = store.entity("site", identity(doc, target), name, document.key, target=target,
                        props={"fields": properties(main),
                               "address": address or name,
                               "postal_code": postal_label[:5] if postal_label else None,
                               "city": postal_label[5:].strip(" ,-") if postal_label else None,
                               "detail_collected": True}, detail=True)
    for link, label in links(main, "/ugov/ou-structure/").items():
        existing = store.db.execute("SELECT entity_id FROM identifier WHERE value=?", (store.canonical(link),)).fetchone()
        kind = "department" if label.startswith("Dipartimento") else "organisation"
        structure = existing[0] if existing else store.ref(kind, link, label, document.key)
        store.relate(structure, "located_in", site, document.key)


def reconcile(store):
    """Corrispondenze conservative; le entità originali restano sempre separate."""
    import unicodedata
    def name_tokens(value):
        return sorted(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode()))
    people = {}
    for key, name, source, code in store.db.execute("SELECT id,name,source_id,code FROM entity WHERE kind='person'"):
        if code and code.isdigit():
            people.setdefault(int(code), []).append((key, name, source))
    for key, name, code, source in store.db.execute("SELECT id,name,code,source_id FROM entity WHERE kind='agenda_teacher'").fetchall():
        if not code or not code.isdigit():
            continue
        matches = people.get(int(code), [])
        if len(matches) == 1 and name_tokens(name) == name_tokens(matches[0][1]):
            store.relate(key, "references", matches[0][0], source,
                         {"method": "numeric_code_and_full_name", "profile_source_id": matches[0][2]})
    courses = {}
    for key, code, year, source in store.db.execute("SELECT id,code,academic_year,source_id FROM entity WHERE kind='course_offering' AND code IS NOT NULL"):
        courses.setdefault((code, year), []).append((key, source))
    for key, year, props, source in store.db.execute("SELECT id,academic_year,properties,source_id FROM entity WHERE kind='agenda_activity'").fetchall():
        combined = json.loads(props).get("codice_combinato", "")
        if not isinstance(combined, str) or "^" not in combined:
            continue
        code = combined.split("^")[-1].upper()
        matches = courses.get((code, year), [])
        if len(matches) == 1:
            store.relate(key, "references", matches[0][0], source,
                         {"method": "explicit_activity_code_and_year", "course_source_id": matches[0][1]})


def build(output=OUTPUT, people_only=False):
    output = Path(output)
    state = json.loads(COLLECTION.read_text())
    sources = Sources(offline=True)
    documents = []
    for target, job in sorted(state["jobs"].items()):
        if "source_key" not in job:
            continue
        document = sources.get(target, job.get("parameters"), job.get("projection"))
        if document.ok:
            # Conserva solo i metadati: migliaia di schede HTML non devono
            # occupare contemporaneamente diversi gigabyte di RAM.
            documents.append((target, job, Document(document.meta)))
    aliases = {}
    for target, job, document in documents:
        if job["kind"] in {"course", "person", "programme", "offering", "unit", "site", "doctoral_course"}:
            # Il JSON delle impostazioni Drupal evita un secondo parsing HTML.
            match = re.search(rb'<script[^>]*data-drupal-selector="drupal-settings-json"[^>]*>(.*?)</script>', document.raw, re.S)
            if match:
                current = json.loads(match[1]).get("path", {}).get("currentPath", "")
                if current.startswith("ugov/"):
                    aliases[target] = BASE + "/it/" + current
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".building.sqlite")
    temporary.unlink(missing_ok=True)
    db = sqlite3.connect(temporary)
    try:
        schema = (ROOT / "schema.sql").read_text()
        if people_only:
            if not output.exists():
                raise FileNotFoundError("Il primo rilascio richiede build senza --people-only")
            with sqlite3.connect(f"file:{output}?mode=ro", uri=True) as previous:
                check(previous)
                previous.backup(db)
            # Le viste sono additive; le sei tabelle e gli ID rimangono invariati.
            for match in re.finditer(r"CREATE VIEW (\w+)\b.*?;", schema, re.S):
                db.execute("DROP VIEW IF EXISTS " + match[1])
                db.execute(match[0])
            db.execute("CREATE INDEX IF NOT EXISTS relation_source ON relation(source_id)")
            db.execute("PRAGMA foreign_keys=ON")
        else:
            db.executescript(schema)
        store = Store(db, aliases)
        for meta_path in sorted(RAW.glob("*.json")):
            document = read_document(meta_path)
            m = document.meta
            db.execute("""INSERT INTO source VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                       url=excluded.url,final_url=excluded.final_url,fetched_at=excluded.fetched_at,
                       status=excluded.status,content_type=excluded.content_type,sha256=excluded.sha256,
                       path=excluded.path,error=excluded.error,request_metadata=excluded.request_metadata""", tuple(m.get(k) for k in
                       ["key", "url", "final_url", "fetched_at", "status", "content_type", "sha256", "path", "error"])
                       + (dumps(m.get("request_metadata") or {"method": "GET"}),))
        if not people_only:
            import_agenda(store, documents)
            import_catalogues(store, documents)
        else:
            # Sostituisce solo le relazioni estratte dai profili e dalla rubrica.
            for _, job, document in documents:
                if job["kind"] in {"person", "directory"}:
                    db.execute("DELETE FROM relation WHERE source_id=? AND predicate IN ('member_of','taught_by')", (document.key,))
        handlers = {"unit": import_structure, "programme": import_programme, "offering": import_programme,
                    "department_index": import_department_index, "course": import_course,
                    "doctoral_course": import_course, "person": import_person, "site": import_site,
                    "phd_index": import_phd_index, "directory": import_directory}
        kinds = ["directory", "person"] if people_only else ["unit", "programme", "offering", "department_index", "phd_index", "course", "doctoral_course", "directory", "person", "site"]
        for kind in kinds:
            count = 0
            for target, job, document in documents:
                if job["kind"] == kind:
                    handlers[kind](store, target, job, document, document.soup())
                    count += 1
                    if count % 500 == 0:
                        print(f"Import {kind}: {count} fonti elaborate…", flush=True)
            print(f"Import {kind}: {count} fonti", flush=True)
        # Gli alias pubblici rimangono interrogabili anche dopo la normalizzazione.
        for alias, canonical in sorted(aliases.items()):
            for row in db.execute("SELECT entity_id FROM identifier WHERE value=?", (canonical,)).fetchall():
                db.execute("INSERT OR IGNORE INTO identifier VALUES(?,?)", (alias, row[0]))
        reconcile(store)
        if people_only:
            old = db.execute("SELECT expected_count,collected_count FROM coverage WHERE scope='study_plan_source_rows'").fetchone()
            if old:
                store.plan_audit = {"published": old[0], "parsed": old[1]}
        db.execute("DELETE FROM coverage")
        record_coverage(db, state, documents, aliases, store.plan_audit)
        db.commit()
        check(db)
        db.execute("VACUUM")
        counts = dict(db.execute("SELECT kind,count(*) FROM entity GROUP BY kind"))
        report = {"schema_version": 1, "entities": counts,
                  "relations": db.execute("SELECT count(*) FROM relation").fetchone()[0],
                  "coverage": [dict(zip(["scope", "status", "expected_count", "collected_count", "notes"], row)) for row in db.execute("SELECT * FROM coverage ORDER BY scope")]}
        db.close()
        temporary.replace(output)
        report["database_bytes"] = output.stat().st_size
        with output.open("rb") as handle:
            report["database_sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
        output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(counts, ensure_ascii=False, indent=2), flush=True)
        return report
    except BaseException:
        db.close()
        temporary.unlink(missing_ok=True)
        raise


def record_directory_coverage(db, state, documents, aliases):
    lookup = Store(db, aliases)
    all_people = set()
    all_pages_complete = True
    for category, label in DIRECTORY_CATEGORIES.items():
        pages, people, last_page = set(), set(), 0
        roots_seen = False
        for target, job, document in documents:
            if job['kind'] != 'directory' or job['category_code'] != category:
                continue
            doc = document.soup()
            if not directory_valid(doc, job):
                continue
            pages.add(job['page'])
            roots_seen |= job['page'] == 0
            last_page = max(last_page, job['page'], *(directory_page_number(u) for u in pager(doc, target)))
            people.update(lookup.id('person', row['url']) for row in directory_rows(doc))
        pages_complete = roots_seen and pages == set(range(last_page + 1))
        all_pages_complete &= pages_complete
        all_people.update(people)
        found = sum(bool(db.execute("SELECT 1 FROM person WHERE id=? AND json_extract(properties,'$.detail_collected')=1", (p,)).fetchone()) for p in people)
        db.execute('INSERT INTO coverage VALUES(?,?,?,?,?)', ('directory_pages:' + category,
                   'complete' if pages_complete else 'partial' if pages else 'not_collected',
                   last_page + 1 if roots_seen else None, len(pages),
                   label + ': pagine verificate per filtro, indice corrente e ultima pagina pubblicata.'))
        db.execute('INSERT INTO coverage VALUES(?,?,?,?,?)', ('directory_profiles:' + category,
                   'complete' if pages_complete and found == len(people) else 'partial' if people else 'not_collected',
                   len(people) if pages_complete else None, found,
                   label + ': identità U-GOV della rubrica con profilo acquisito. Le categorie possono sovrapporsi.'))
    found = sum(bool(db.execute("SELECT 1 FROM person WHERE id=? AND json_extract(properties,'$.detail_collected')=1", (p,)).fetchone()) for p in all_people)
    db.execute('INSERT INTO coverage VALUES(?,?,?,?,?)', ('directory_academic_people',
               'complete' if all_pages_complete and found == len(all_people) else 'partial' if all_people else 'not_collected',
               len(all_people) if all_pages_complete else None, found,
               'Unione delle sette categorie accademiche della rubrica, deduplicata per identità; non include la categoria esclusiva Personale TAB.'))


def record_coverage(db, state, documents, aliases, plan_audit):
    record_directory_coverage(db, state, documents, aliases)
    by_kind = Counter(job["kind"] for _, job, _ in documents)
    expected = Counter(job["kind"] for job in state["jobs"].values())
    for kind in sorted(expected):
        attempted = any(j.get("source_key") for j in state["jobs"].values() if j["kind"] == kind)
        status = "complete" if by_kind[kind] == expected[kind] else "partial" if by_kind[kind] else "unavailable" if attempted else "not_collected"
        db.execute("INSERT INTO coverage VALUES(?,?,?,?,?)", ("requests:" + kind, status, expected[kind], by_kind[kind],
                   "Copertura delle richieste censite, non prova di completezza del dominio UniMi."))
    for target, job, document in documents:
        if job["kind"] != "catalogue" or target not in CATALOGUES:
            continue
        doc = document.soup()
        rows = [c for c in cards(doc, target) if c["academic_year"] is not None]
        parsed = len({c["url"] for c in rows})
        published = [int(x) for x in re.findall(r"\d+ corsi su (\d+)", text(doc))]
        wanted = sum(published) if published else parsed
        db.execute("INSERT INTO coverage VALUES(?,?,?,?,?)", ("catalogue:" + target,
                   "complete" if parsed == wanted else "partial", wanted, parsed,
                   "Schede dell'elenco ufficiale per tutti gli anni presenti nella risposta; non sommare annualità come identità uniche."))
    doctoral_pages = [d for _, j, d in documents if j["kind"] == "phd_index"]
    if doctoral_pages:
        published = re.search(r"(\d+) risultati", text(doctoral_pages[0].soup()))
        wanted = int(published[1]) if published else None
        catalogue_urls = {url(a["href"]) for d in doctoral_pages for a in d.soup().select("tbody tr td.views-field-title a[href]")}
        lookup = Store(db, aliases)
        found = sum(bool(db.execute("SELECT 1 FROM entity WHERE id=?", (lookup.id("doctoral_course", target),)).fetchone()) for target in catalogue_urls)
        db.execute("INSERT INTO coverage VALUES(?,?,?,?,?)", ("doctoral_teaching_catalogue",
                   "complete" if wanted == found else "partial", wanted, found,
                   "Attività del catalogo dottorale: attraversamento delle pagine e confronto con il totale pubblicato."))
    db.execute("INSERT INTO coverage VALUES(?,?,?,?,?)", ("study_plan_source_rows",
               "complete" if plan_audit["published"] == plan_audit["parsed"] else "partial",
               plan_audit["published"], plan_audit["parsed"],
               "Righe nelle schede di piani acquisite, comprese alternative, gruppi e attività senza scheda individuale. Include ripetizioni fra URL della stessa offerta; non è un conteggio di insegnamenti unici."))
    for name, kind, variable in [("rooms", "agenda_rooms", "elenco_aule"), ("teachers", "agenda_docenti", "elenco_docenti"),
                                 ("activities", "agenda_attivita", "elenco_attivita")]:
        doc = next((d for _, j, d in documents if j["kind"] == kind), None)
        n = len(assignment(doc.raw, variable)) if doc else 0
        if doc and name == "rooms":
            n = sum(len(v) for v in assignment(doc.raw, variable).values())
        db.execute("INSERT INTO coverage VALUES(?,?,?,?,?)", ("agenda:" + name, "complete" if doc else "unavailable", n, n,
                   "Intera selezione pubblicata dall'Agenda per il perimetro acquisito; non censimento di tutto l'ateneo."))
    room_count = db.execute("SELECT count(*) FROM room").fetchone()[0]
    geolocated = db.execute("SELECT count(*) FROM room WHERE latitude IS NOT NULL AND longitude IS NOT NULL").fetchone()[0]
    db.execute("INSERT INTO coverage VALUES(?,?,?,?,?)", ("geographic_coordinates",
               "complete" if geolocated == room_count else "partial" if geolocated else "not_collected",
               room_count, geolocated, "Coordinate pubblicate nell'anagrafica del gestionale. La fonte non ne specifica precisione o accuratezza fisica; nessuna geocodifica da indirizzi."))
    plans = db.execute("SELECT count(*) FROM room WHERE json_extract(properties,'$.plan_image_reference') IS NOT NULL").fetchone()[0]
    db.execute("INSERT INTO coverage VALUES(?,?,?,?,?)", ("indoor_plan_references", "partial" if plans else "not_collected",
               room_count, plans, "Riferimenti a immagini di planimetrie pubblicati nell'anagrafica; nessun documento cartografico scaricato."))
    for scope, note in [("timetable_events", "Eventi e occupazione delle aule esclusi dal database; conservata solo la proiezione anagrafica area_rooms della risposta del servizio aule."),
                        ("university_completeness", "Fonti note in espansione; non certificata la completezza di tutto l'ateneo.")]:
        db.execute("INSERT INTO coverage VALUES(?,?,?,?,?)", (scope, "not_collected", None, 0, note))
    for job_kind, entity_kind in [("course", "course_offering"), ("person", "person")]:
        wanted = len({aliases.get(target, target) for target, job in state["jobs"].items() if job["kind"] == job_kind})
        parsed = db.execute("SELECT count(*) FROM entity WHERE kind=? AND json_extract(properties,'$.detail_collected')=1", (entity_kind,)).fetchone()[0]
        db.execute("INSERT INTO coverage VALUES(?,?,?,?,?)", ("normalised_" + job_kind + "_details",
                   "complete" if parsed == wanted and wanted else "partial" if parsed else "not_collected",
                   wanted, parsed, "Schede con identità U-GOV verificata, deduplicate mediante gli alias dichiarati dalle pagine."))
    for kind in ["agenda_teacher", "agenda_activity"]:
        expected_matches = db.execute("SELECT count(*) FROM entity WHERE kind=?", (kind,)).fetchone()[0]
        matched = db.execute("SELECT count(DISTINCT r.subject_id) FROM relation r JOIN entity e ON e.id=r.subject_id WHERE r.predicate='references' AND e.kind=?", (kind,)).fetchone()[0]
        db.execute("INSERT INTO coverage VALUES(?,?,?,?,?)", ("crosswalk:" + kind,
                   "complete" if matched == expected_matches else "partial" if matched else "not_collected", expected_matches, matched,
                   "Associazioni con codici espliciti e anno; per persone richiede anche nome completo concordante. Entità non fuse."))


def check(db):
    result = db.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise ValueError(result)
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Relazioni con chiavi esterne mancanti")
    invalid = db.execute("""SELECT r.predicate,a.kind,b.kind FROM relation r
        JOIN entity a ON a.id=r.subject_id JOIN entity b ON b.id=r.object_id
        WHERE (r.predicate='taught_by' AND b.kind NOT IN ('person','agenda_teacher'))
           OR (r.predicate='located_in' AND b.kind<>'site')
           OR (r.predicate='edition_of' AND (a.kind<>'course_offering' OR b.kind<>'course'))
           OR (r.predicate='version_of' AND (a.kind<>'programme_offering' OR b.kind<>'programme'))
           OR (r.predicate='member_of' AND a.kind<>'person') LIMIT 1""").fetchone()
    if invalid:
        raise ValueError(f"Tipi incompatibili nella relazione: {invalid}")
    # Nessun punto dell'edificio viene inventato come posizione esatta dell'aula.
    for (value,) in db.execute("SELECT properties FROM room"):
        data = json.loads(value)
        if ("latitude" in data) != ("longitude" in data):
            raise ValueError("Coordinate geografiche incomplete")
        if "latitude" in data and (not data.get("coordinate_source_id") or data.get("coordinate_precision") != "not_specified_by_source"):
            raise ValueError("Coordinate prive di fonte o di indicazione della precisione")

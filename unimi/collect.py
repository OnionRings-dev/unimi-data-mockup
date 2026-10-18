"""Raccolta incrementale e riprendibile dei soli metadati pubblici."""
import concurrent.futures
import json
from urllib.parse import urlsplit

from .parse import BASE, cards, links, pager, plan_links, plan_rows, text, url
from .sources import ROOT, Sources, assignment, dumps

AGENDA = "https://orari.unimi.it/PortaleStudenti/"
POST = BASE + "/it/corsi/corsi-post-laurea-e-formazione-continua/"
CATALOGUES = {
    BASE + "/it/corsi/corsi-di-laurea-triennali-e-magistrali-ciclo-unico": "bachelor_or_single_cycle",
    BASE + "/it/corsi/corsi-di-laurea-magistrale": "masters_degree",
    POST + "master-e-perfezionamento/catalogo-master": "university_master",
    POST + "corsi-di-dottorato-phd": "phd",
    POST + "master-e-perfezionamento/catalogo-corsi-di-perfezionamento": "advanced_course",
    POST + "scuole-di-specializzazione-catalogo-corsi/catalogo-scuole-di-specializzazione-di-area-medica-e-sanitaria": "specialisation",
    POST + "scuole-di-specializzazione-catalogo-corsi/catalogo-scuole-di-specializzazione-altre-aree": "specialisation",
    POST + "scuole-di-specializzazione-catalogo-corsi/scuole-di-specializzazione-di-area-odontoiatrica": "specialisation",
}
PHD_COURSES = POST + "corsi-di-dottorato-phd/catalogo-degli-insegnamenti-la-formazione-dottorale"
UNITS = {
    BASE + "/it/ateneo/uffici-e-strutture/dipartimenti": "department",
    BASE + "/it/ateneo/uffici-e-strutture/facolta-e-scuole-elenco": "faculty_or_school",
}
SITES = BASE + "/it/ateneo/uffici-e-strutture/sedi"
COLLECTION = ROOT / "data/collection.json"


class Collector:
    def __init__(self, workers=4, retry_failed=False):
        self.sources = Sources(retry_failed=retry_failed)
        self.workers = workers
        self.state = json.loads(COLLECTION.read_text()) if COLLECTION.exists() else {"academic_year": 2026, "jobs": {}}
        self.jobs = self.state["jobs"]
        for target, job in self.jobs.items():
            if "/catalogo-degli-insegnamenti-la-formazione-dottorale/" in target:
                job["kind"] = "doctoral_course"

    def add(self, target, kind, **context):
        target = url(target)
        host = urlsplit(target).hostname or ""
        if not host.endswith(".unimi.it"):
            return
        if "/catalogo-degli-insegnamenti-la-formazione-dottorale/" in target:
            kind = "doctoral_course"
        if target not in self.jobs:
            self.jobs[target] = {"kind": kind, **context}
        else:
            for key, value in context.items():
                self.jobs[target].setdefault(key, value)

    def save(self):
        tmp = COLLECTION.with_suffix(".tmp")
        tmp.write_text(dumps(self.state) + "\n")
        tmp.replace(COLLECTION)

    def fetch(self, kinds):
        targets = sorted(u for u, job in self.jobs.items() if job["kind"] in kinds)
        self.save()
        print(f"Acquisizione {', '.join(sorted(kinds))}: {len(targets)} pagine", flush=True)
        def get(target):
            job = self.jobs[target]
            doc = self.sources.get(target, job.get("parameters"), job.get("projection"))
            return target, doc.key, doc.meta["status"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            for i, (target, key, status) in enumerate(pool.map(get, targets), 1):
                self.jobs[target].update(source_key=key, status=status)
                if i % 25 == 0 or i == len(targets):
                    self.save()
                    print(f"  {i}/{len(targets)}; ultima risposta {status}", flush=True)
        self.save()

    def docs(self, kinds):
        for target, job in sorted(list(self.jobs.items())):
            if job["kind"] in kinds and job.get("status") == 200:
                doc = self.sources.get(target, job.get("parameters"), job.get("projection"))
                yield target, job, doc.soup()

    def collect_rooms(self):
        doc = self.sources.get(AGENDA + "combo.php?sw=rooms_")
        groups = assignment(doc.raw, "elenco_aule")
        site_code, rooms = next((key, rows) for key, rows in groups.items() if rows)
        parameters = {"form-type": "rooms", "view": "rooms", "include": "rooms",
                      "sede[]": [site_code], "aula[]": [rooms[0]["valore"]],
                      "date": "18-10-2026", "_lang": "it", "all_events": "0",
                      "week_grid_type": "-1", "col_cells": "0", "empty_box": "0",
                      "only_grid": "0", "highlighted_date": "0"}
        self.add(AGENDA + "rooms_call.php", "room_metadata", parameters=parameters, projection="area_rooms")
        self.fetch({"room_metadata"})

    def paginate(self, kinds):
        visited = set()
        while True:
            self.fetch(kinds)
            new = 0
            for target, job in sorted(list(self.jobs.items())):
                if target in visited or job["kind"] not in kinds or job.get("status") != 200:
                    continue
                doc = self.sources.get(target).soup()
                visited.add(target)
                for next_url in pager(doc, target):
                    if next_url not in self.jobs:
                        self.add(next_url, job["kind"], **{k: v for k, v in job.items() if k not in {"kind", "status", "source_key"}})
                        new += 1
            if not new:
                return

    def collect(self, details=True):
        for target, level in CATALOGUES.items():
            self.add(target, "catalogue", level=level)
        for target, kind in UNITS.items():
            self.add(target, "unit_index", unit_kind=kind)
        self.add(SITES, "site_index")
        self.add(PHD_COURSES, "phd_index")
        for name in ["corsi", "docenti", "attivita"]:
            self.add(AGENDA + f"combo.php?sw=ec_&aa=2026&page={name}", "agenda_" + name)
        self.add(AGENDA + "combo.php?sw=rooms_", "agenda_rooms")
        self.paginate({"catalogue", "phd_index"})
        self.fetch({"unit_index", "site_index", "agenda_corsi", "agenda_docenti", "agenda_attivita", "agenda_rooms"})
        self.collect_rooms()

        for target, job, doc in self.docs({"catalogue"}):
            for card in cards(doc, target):
                if card["academic_year"] is not None:
                    self.add(card["url"], "programme", level=job["level"], **{k: v for k, v in card.items() if k != "url"})
            # I filtri istituzionali rendono esplicita l'appartenenza alla facoltà.
            for option in doc.select("select[name=facolta] option[value]"):
                if option["value"] != "All":
                    self.add(target.split("?")[0] + "?facolta=" + option["value"], "faculty_filter", faculty_name=text(option))
        for target, job, doc in self.docs({"unit_index"}):
            for a in doc.select("article .field--name-title a[href]"):
                self.add(url(a["href"]), "unit", name=text(a), unit_kind=job["unit_kind"])
        for target, job, doc in self.docs({"site_index"}):
            for link, name in links(doc, "/ugov/place/").items():
                self.add(link, "site", name=name)
        self.fetch({"programme", "unit", "site", "faculty_filter"})

        # Le pagine ufficiali delle strutture forniscono il sito dipartimentale.
        for target, job, doc in self.docs({"unit"}):
            if job.get("unit_kind") != "department":
                continue
            for a in doc.select("a[href]"):
                link = url(a["href"])
                host = urlsplit(link).hostname or ""
                if host.endswith(".unimi.it") and host not in {"www.unimi.it", "apps.unimi.it", "work.unimi.it", "lastatalenews.unimi.it"} and "sito" in text(a).lower():
                    domain = "https://" + host
                    self.add(domain + "/it", "department_home", department_url=target)
                    self.add(domain + "/it/didattica/offerta-formativa/insegnamenti-del-dipartimento", "department_index", department_url=target)
                    self.add(domain + "/it/dipartimento/contatti/persone", "people_index", department_url=target)
        # DEMM è un percorso verificato anche se l'etichetta del sito cambia.
        self.add("https://demm.unimi.it/it/didattica/offerta-formativa/insegnamenti-del-dipartimento", "department_index",
                 department_url=BASE + "/it/ugov/ou-structure/dipartimento-di-economia-management-e-metodi-quantitativi")
        self.add("https://demm.unimi.it/it/dipartimento/contatti/persone", "people_index",
                 department_url=BASE + "/it/ugov/ou-structure/dipartimento-di-economia-management-e-metodi-quantitativi")
        self.fetch({"department_home"})
        for target, job, doc in self.docs({"department_home"}):
            for a in doc.select("a[href]"):
                link = url(a["href"], target)
                if urlsplit(link).hostname != urlsplit(target).hostname:
                    continue
                if "insegnamenti-del-dipartimento" in link:
                    self.add(link, "department_index", department_url=job["department_url"])
                elif "/contatti/persone" in link:
                    self.add(link, "people_index", department_url=job["department_url"])
        self.paginate({"department_index", "people_index"})

        for target, job, doc in self.docs({"programme", "department_index"}):
            for link, name in links(doc, "/ugov/of/cdsi").items():
                if "/cdsi2027" in link or "/cdsi2026" in link:
                    self.add(link, "offering", name=name)
            # Le schede centrali possono usare URL leggibili anziché U-GOV.
            for a in doc.select("a[href]"):
                if "/altre_offerte/aa-2026/2027/" in a["href"]:
                    self.add(url(a["href"]), "offering", name=text(a))
        self.fetch({"offering"})

        for target, job, doc in self.docs({"offering", "programme", "department_index", "phd_index", "people_index"}):
            for fragment in ["/ugov/rubrica/", "/ugov/person/"]:
                for link, name in links(doc, fragment).items():
                    self.add(link, "person", name=name)
            for plan in plan_rows(doc):
                for row in plan["rows"]:
                    if row["url"]:
                        self.add(row["url"], "course", name=row["name"])
            for a in plan_links(doc):
                self.add(url(a["href"]), "course", name=text(a))
            for link, name in links(doc, "/ugov/of/af").items():
                self.add(link, "course", name=name)
            if job["kind"] == "phd_index":
                for a in doc.select("tbody tr a[href]"):
                    link = url(a["href"])
                    if "catalogo-degli-insegnamenti" in link:
                        self.add(link, "doctoral_course", name=text(a))

        # Le attività per corso espongono i destinatari, senza scaricare lezioni.
        doc = self.sources.get(AGENDA + "combo.php?sw=ec_&aa=2026&page=corsi")
        for programme in assignment(doc.raw, "elenco_corsi"):
            self.add(AGENDA + "call_redis.php?key=UNIMI_2026_ec_elenco_anno2_" + programme["valore"], "agenda_groups", programme_code=programme["valore"])
        self.fetch({"agenda_groups", "doctoral_course"})
        if details:
            self.fetch({"course"})
            for target, job, doc in self.docs({"course", "doctoral_course"}):
                for fragment in ["/ugov/rubrica/", "/ugov/person/"]:
                    for link, name in links(doc, fragment).items():
                        self.add(link, "person", name=name)
            self.fetch({"person"})
        self.save()
        print(f"Raccolta salvata: {len(self.jobs)} fonti censite", flush=True)

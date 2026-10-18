import json
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from unimi.build import OUTPUT, Store, check, import_agenda, import_course, import_person, import_programme, make_course, reconcile
from unimi.parse import academic_year, pager, plan_rows
from unimi.sources import ROOT, Document, Sources, assignment, project_room_metadata, read_document


class ParserTests(unittest.TestCase):
    def test_agenda_json_is_read_without_executing_javascript(self):
        raw = b'var data = [{"valore":"A#1","label":"Aula"}]; throw new Error("never execute");'
        self.assertEqual(assignment(raw, "data")[0]["valore"], "A#1")
        with self.assertRaises(ValueError):
            assignment(b'var data = alert("not JSON")', "data")

    def test_ugov_uses_end_year_and_agenda_uses_start_year(self):
        self.assertEqual(academic_year("/af202800000abc-12"), 2027)
        self.assertEqual(academic_year("/aa-2027/2028-corso"), 2027)
        self.assertEqual(academic_year("/it/corsi/insegnamenti-dei-corsi-di-laurea/2028/corso"), 2027)

    def test_drupal_pagination_preserves_existing_filters(self):
        doc = BeautifulSoup('<nav class="pager-nav"><a href="?page=8&amp;anno=2027">Ultima</a></nav>', "html.parser")
        self.assertEqual(pager(doc, "https://www.unimi.it/list"), {"https://www.unimi.it/list?page=8&anno=2027"})

    def test_plans_are_not_hardcoded_to_2027_and_preserve_year_and_choice(self):
        doc = BeautifulSoup('''<div id="curr-20280000abcof1-ABC-0">
          <a href="#ugov-of-pd-year-af-a">Anno: 2</a>
          <div id="ugov-of-pd-year-af-a"><table><tbody>
          <tr class="rowsubtitle"><td>Facoltativo</td></tr>
          <tr><td class="cdl-title"><a href="/it/ugov/of/af20280000abc-12">Test</a></td>
          <td data-title="Crediti massimi">6</td></tr></tbody></table></div></div>''', "html.parser")
        plan = plan_rows(doc)[0]
        self.assertEqual(plan["year"], 2027)
        self.assertEqual(plan["rows"][0]["study_year"], 2)
        self.assertEqual(plan["rows"][0]["requirement"], "Facoltativo")

    def test_yearless_plan_preserves_mandatory_rows_choice_groups_and_components(self):
        doc = BeautifulSoup('''<div id="curr-20270000cbcof2-CBC-A">
          <div class="ugov-of-pd-special-i"><div class="special-i">Insegnamenti obbligatori</div>
          <table><tbody><tr><td data-title="Attività formative"><a href="/required">Obbligatorio</a></td></tr></tbody></table></div>
          <div class="ugov-of-pd-rules"><div class="yyy">A1: un esame a scelta</div>
          <div class="ugov-of-pd-rules-af"><table><tbody>
          <tr><td class="cdl-title"><a href="/choice">Opzione</a></td></tr>
          <tr><td> - Parte A</td><td>6</td><td>40</td></tr></tbody></table></div></div></div>''', "html.parser")
        rows = plan_rows(doc)[0]["rows"]
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]["study_year"])
        self.assertEqual(rows[0]["requirement"], "Insegnamenti obbligatori")
        self.assertEqual(rows[1]["choice_group"], "A1: un esame a scelta")
        self.assertEqual(rows[1]["components"], [["- Parte A", "6", "40"]])

    def test_optional_courses_nested_in_year_rules_are_included(self):
        doc = BeautifulSoup('''<div id="curr-20270000gadof2-GAD-0">
          <a href="#ugov-of-pd-year-af-year2">Anno: 2</a><div id="ugov-of-pd-year-af-year2">
          <div class="ugov-of-pd-rules"><div class="ugov-of-pd-year-rules-2">Percorso agroambientale: due esami</div>
          <div class="ugov-of-pd-year-rules-af-2"><table><tbody><tr>
          <td data-title="Attività formative"><a href="/option">Opzione di percorso</a></td>
          </tr></tbody></table></div></div></div></div>''', "html.parser")
        row = plan_rows(doc)[0]["rows"][0]
        self.assertEqual(row["study_year"], 2)
        self.assertEqual(row["choice_group"], "Percorso agroambientale: due esami")

    def test_master_plan_without_curriculum_codes_preserves_uncoded_rows(self):
        doc = BeautifulSoup('''<script data-drupal-selector="drupal-settings-json">{"path":{"currentPath":"ugov/pl/cdsi20260000md4of1"}}</script>
          <div id="curr--"><div id="ugov-of-pd-year-af---0"><table><tbody><tr>
          <td class="cdl-title" data-title="Attività formative">Bioemergenze</td>
          <td data-title="Crediti">3</td></tr></tbody></table></div></div>''', "html.parser")
        plan = plan_rows(doc)[0]
        self.assertEqual(plan["year"], 2025)
        self.assertIsNone(plan["curriculum_code"])
        self.assertIsNone(plan["rows"][0]["url"])
        self.assertEqual(plan["rows"][0]["fields"]["Crediti"], "3")


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript((ROOT / "schema.sql").read_text())
        self.db.execute("INSERT INTO source(id,url,fetched_at,sha256,path) VALUES('s','https://www.unimi.it','2026-10-18',?,'x')", ("0"*64,))

    def tearDown(self):
        self.db.close()

    def test_same_name_does_not_merge_different_people(self):
        store = Store(self.db)
        a = store.entity("person", "ugov:one", "Mario Rossi", "s")
        b = store.entity("person", "ugov:two", "Mario Rossi", "s")
        self.assertNotEqual(a, b)
        self.assertEqual(self.db.execute("SELECT count(*) FROM entity").fetchone()[0], 2)

    def test_verified_url_aliases_share_an_identity(self):
        store = Store(self.db, {"public-url": "canonical-id"})
        a = store.entity("person", "public-url", "Rossi Mario", "s")
        b = store.entity("person", "canonical-id", "Mario Rossi", "s")
        self.assertEqual(a, b)

    def test_source_fields_are_preserved_without_duplicating_them_in_entity(self):
        store = Store(self.db)
        key = store.entity("course", "x", "Corso", "s", props={"credits": 6, "fields": {"syllabus": "Programma"}})
        self.assertEqual(json.loads(self.db.execute("SELECT properties FROM entity WHERE id=?", (key,)).fetchone()[0]), {"credits": 6})
        observation = json.loads(self.db.execute("SELECT properties FROM observation WHERE entity_id=?", (key,)).fetchone()[0])
        self.assertEqual(observation["fields"]["syllabus"], "Programma")

    def test_doctoral_activities_keep_their_type_when_linked_from_a_plan(self):
        store = Store(self.db)
        target = 'https://www.unimi.it/it/corsi/corsi-post-laurea-e-formazione-continua/corsi-di-dottorato-phd/catalogo-degli-insegnamenti-la-formazione-dottorale/aa-2026/2027-test'
        result = make_course(store, target, "Attività dottorale", "s")
        self.assertTrue(result.startswith("doctoral_course:"))
        self.assertEqual(self.db.execute("SELECT count(*) FROM course_offering").fetchone()[0], 0)

    def test_footer_email_is_not_assigned_to_a_person_without_contact_email(self):
        doc = BeautifulSoup('''<script data-drupal-selector="drupal-settings-json">
          {"path":{"currentPath":"ugov/rubrica/person0000042"}}</script>
          <h1>Mario Rossi</h1><footer><a href="mailto:servizio@unimi.it">Contatti</a></footer>''', "html.parser")
        import_person(Store(self.db), "https://www.unimi.it/it/ugov/rubrica/person0000042", {}, Document({"key":"s"}), doc)
        props = json.loads(self.db.execute("SELECT properties FROM person").fetchone()[0])
        self.assertIsNone(props.get("email"))

    def test_error_page_does_not_replace_a_known_course_title(self):
        store = Store(self.db)
        target = "https://www.unimi.it/it/corsi/insegnamenti-dei-corsi-di-laurea/2027/analisi"
        key = store.ref("course_offering", target, "Analisi matematica", "s")
        doc = BeautifulSoup('<h1>Access denied</h1>', "html.parser")
        import_course(store, target, {"kind":"course", "name":"Analisi matematica"}, Document({"key":"s"}), doc)
        name, props = self.db.execute("SELECT name,properties FROM entity WHERE id=?", (key,)).fetchone()
        self.assertEqual(name, "Analisi matematica")
        self.assertFalse(json.loads(props).get("detail_collected", False))

    def test_uncoded_specialisation_activity_preserves_teacher_and_credits(self):
        doc = BeautifulSoup('''<h1>Scuola di specializzazione</h1>
          <div id="curr-2026000033hof3-33H-0"><a href="#ugov-of-pd-year-af-y1">Anno: 1</a>
          <div id="ugov-of-pd-year-af-y1"><table><tbody><tr>
          <td class="cdl-title" data-title="Attività formative">Alimentazione del cavallo</td>
          <td data-title="Docente/i"><a href="/it/ugov/person/alessandro-agazzi">Agazzi Alessandro</a></td>
          <td data-title="Crediti">1</td><td data-title="Ore totali">8</td>
          </tr></tbody></table></div></div>''', "html.parser")
        target = "https://www.unimi.it/it/scuola"
        import_programme(Store(self.db), target, {"kind":"programme"}, Document({"key":"s"}), doc)
        row = self.db.execute("SELECT name,code,academic_year,properties FROM course_offering").fetchone()
        self.assertEqual(row[:3], ("Alimentazione del cavallo", None, 2025))
        self.assertEqual(json.loads(row[3])["credits"], 1)
        self.assertEqual(self.db.execute("SELECT teacher_name FROM teaching_assignment").fetchone()[0], "Agazzi Alessandro")
        self.assertEqual(self.db.execute("SELECT count(*) FROM course").fetchone()[0], 1)

    def test_room_coordinates_come_from_published_fields_not_the_map_center(self):
        row = {"room_code":"A#1", "room_name":"Aula 1", "area_code":"A", "area":"Sede A",
               "capacity":30, "address":"Via A 1", "latitude":"45.4", "longitude":"9.2",
               "google_map_link":'<iframe src="https://www.google.com/maps?center=45.0,9.0"></iframe>'}
        document = Document({"key":"s"}, json.dumps({"area_rooms":{"A":{"A#1":row}}}).encode())
        import_agenda(Store(self.db), [("https://orari.unimi.it/PortaleStudenti/rooms_call.php", {"kind":"room_metadata"}, document)])
        props = json.loads(self.db.execute("SELECT properties FROM room").fetchone()[0])
        self.assertEqual((props["latitude"],props["longitude"]), (45.4,9.2))
        self.assertEqual(props["coordinate_source_id"], "s")
        self.assertEqual(props["coordinate_precision"], "not_specified_by_source")

    def test_foreign_keys_and_multiple_audiences(self):
        store = Store(self.db)
        a = store.entity("course", "one", "Corso", "s")
        b = store.entity("programme", "two", "Percorso", "s")
        store.relate(b, "includes", a, "s", {"group": "A"})
        store.relate(b, "includes", a, "s", {"group": "B"})
        self.assertEqual(self.db.execute("SELECT count(*) FROM relation").fetchone()[0], 2)
        with self.assertRaises(sqlite3.IntegrityError):
            store.relate(a, "includes", "missing", "s")

    def test_teacher_crosswalk_requires_both_numeric_code_and_full_name(self):
        store = Store(self.db)
        person = store.entity("person", "https://www.unimi.it/it/ugov/rubrica/person0000042", "Rossi Mario", "s")
        agenda = store.entity("agenda_teacher", "agenda:42", "MARIO ROSSI", "s", code="42")
        store.entity("agenda_teacher", "agenda:43", "MARIO ROSSI", "s", code="43")
        reconcile(store)
        self.assertEqual(self.db.execute("SELECT subject_id,object_id FROM relation WHERE predicate='references'").fetchall(), [(agenda,person)])
        self.assertEqual(self.db.execute("SELECT count(*) FROM entity").fetchone()[0], 3)


class ArchiveTests(unittest.TestCase):
    def test_room_projection_discards_all_calendar_content(self):
        areas = {"A":{"A#1":{"room_name":"Aula 1", "latitude":"45.4", "longitude":"9.2"}}}
        raw = json.dumps({"area_rooms":areas,"events":[{"date":"2026-10-18"}],"table":"calendar"}).encode()
        self.assertEqual(json.loads(project_room_metadata(raw)), {"area_rooms":areas})

    def test_interrupted_retry_keeps_the_previous_response_readable(self):
        from unimi import sources
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_dir = root / "data/raw"
            raw_dir.mkdir(parents=True)
            with patch.object(sources, "ROOT", root), patch.object(sources, "RAW", raw_dir):
                old = {"key": "request", "sha256": hashlib.sha256(b"old").hexdigest()}
                Sources.save(old, b"old")
                new = {"key": "request", "sha256": hashlib.sha256(b"new").hexdigest()}
                original = sources.atomic_write
                def interrupted(target, data):
                    if str(target).endswith(".json"):
                        raise OSError("interruzione simulata")
                    original(target, data)
                with patch.object(sources, "atomic_write", side_effect=interrupted):
                    with self.assertRaises(OSError):
                        Sources.save(new, b"new")
                self.assertEqual(read_document(raw_dir / "request.json").raw, b"old")


@unittest.skipUnless(OUTPUT.exists(), "Database non ancora costruito")
class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = sqlite3.connect(f"file:{OUTPUT}?mode=ro", uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_database_integrity(self):
        check(self.db)

    def test_all_published_agenda_rooms_are_present_and_linked(self):
        expected, actual = self.db.execute("SELECT expected_count,collected_count FROM coverage WHERE scope='agenda:rooms'").fetchone()
        self.assertEqual(self.db.execute("SELECT count(*) FROM room_site").fetchone()[0], expected)
        self.assertEqual(actual, expected)

    def test_every_entity_and_relation_has_a_source(self):
        for table in ["entity", "relation"]:
            self.assertEqual(self.db.execute(f"SELECT count(*) FROM {table} r LEFT JOIN source s ON s.id=r.source_id WHERE s.id IS NULL").fetchone()[0], 0)

    def test_geographic_precision_and_global_completeness_are_not_invented(self):
        status = self.db.execute("SELECT status FROM coverage WHERE scope='university_completeness'").fetchone()[0]
        self.assertNotEqual(status, "complete")
        for (props,) in self.db.execute("SELECT properties FROM room"):
            data = json.loads(props)
            if "latitude" in data:
                self.assertEqual(data["coordinate_precision"], "not_specified_by_source")
                source = self.db.execute("SELECT request_metadata FROM source WHERE id=?", (data["coordinate_source_id"],)).fetchone()
                self.assertIsNotNone(source)
                self.assertEqual(json.loads(source[0])["projection"], "area_rooms")


if __name__ == "__main__":
    unittest.main()

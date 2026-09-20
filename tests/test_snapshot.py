"""Verifiche offline sul dataset reale congelato, senza richieste di rete."""
import hashlib
import json
import sqlite3
import unittest
from pathlib import Path

from unimi_mock.build import utc
from unimi_mock.collect import soup
from unimi_mock.parse import plan_rows
from unimi_mock.sources import assignment

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/releases/2026-09-20/unimi.sqlite'


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
        cls.db.row_factory = sqlite3.Row
        cls.manifest = json.loads(DB.with_name('manifest.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def scalar(self, query, args=()):
        return self.db.execute(query, args).fetchone()[0]

    def test_database_integrity_and_release_checksum(self):
        self.assertEqual(self.scalar('PRAGMA integrity_check'), 'ok')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(hashlib.sha256(DB.read_bytes()).hexdigest(), self.manifest['database_sha256'])
        self.assertEqual(hashlib.sha256((ROOT / 'schema.sql').read_bytes()).hexdigest(), self.manifest['schema_sha256'])

    def test_all_raw_sources_match_hashes(self):
        for row in self.db.execute('SELECT raw_path,sha256 FROM source_document'):
            self.assertEqual(hashlib.sha256((ROOT / row['raw_path']).read_bytes()).hexdigest(), row['sha256'])

    def test_catalogue_complete_and_every_programme_associated(self):
        self.assertEqual(self.scalar("SELECT count(*) FROM academic_unit WHERE kind IN ('faculty','school')"), 10)
        self.assertEqual(self.scalar('SELECT count(*) FROM degree_programme'), 181)
        self.assertEqual(self.scalar('SELECT count(*) FROM degree_programme p WHERE NOT EXISTS (SELECT 1 FROM programme_unit u WHERE u.programme_id=p.id)'), 0)

    def test_six_cohorts_and_all_plan_entries(self):
        rows = self.db.execute('''SELECT p.name,count(*) n FROM plan_course pc
            JOIN study_plan sp ON sp.id=pc.study_plan_id JOIN programme_version v ON v.id=sp.programme_version_id
            JOIN degree_programme p ON p.id=v.programme_id GROUP BY p.id''').fetchall()
        self.assertEqual({r['name']:r['n'] for r in rows}, {'Informatica':111, 'Fisica':115})
        self.assertEqual(self.scalar('SELECT count(*) FROM study_plan'), 6)
        self.assertEqual(self.scalar("SELECT cohort_to FROM programme_version WHERE university_code='F63'"), 2024)
        self.assertEqual(self.scalar('''SELECT count(*) FROM plan_course_offering o JOIN plan_course p ON p.id=o.plan_course_id
            WHERE p.activation_status IN ('future','inactive')'''), 0)

    def test_known_real_event_teacher_and_room(self):
        row = self.db.execute('''SELECT l.starts_at,l.ends_at,r.name,t.display_name FROM lesson l
            JOIN lesson_room lr ON lr.lesson_id=l.id JOIN room r ON r.id=lr.room_id
            JOIN lesson_teacher lt ON lt.lesson_id=l.id JOIN teacher t ON t.id=lt.teacher_id
            WHERE l.source_event_id='6394586' ''').fetchone()
        self.assertEqual(row['starts_at'], '2026-09-22T06:30:00Z')
        self.assertEqual(row['ends_at'], '2026-09-22T08:30:00Z')
        self.assertIn('G12', row['name'])
        self.assertIn('boldi', row['display_name'].lower())

    def test_shared_events_are_single_events_with_multiple_activities(self):
        self.assertEqual(self.scalar('SELECT count(*) FROM lesson'), 2189)
        self.assertEqual(self.scalar('SELECT count(*) FROM (SELECT source_key FROM lesson GROUP BY source_key HAVING count(*)>1)'), 0)
        self.assertGreater(self.scalar('SELECT count(*) FROM (SELECT lesson_id FROM lesson_activity GROUP BY lesson_id HAVING count(*)>1)'), 0)
        self.assertEqual(self.scalar('''SELECT count(*) FROM lesson l WHERE NOT EXISTS
            (SELECT 1 FROM lesson_activity a JOIN activity_audience aa ON aa.activity_id=a.activity_id WHERE a.lesson_id=l.id)'''), 0)

    def test_source_closures_and_unknown_rooms_preserved(self):
        self.assertEqual(self.scalar('SELECT count(*) FROM calendar_closure'), 26)
        self.assertEqual(self.scalar('SELECT count(*) FROM lesson l WHERE NOT EXISTS(SELECT 1 FROM lesson_room r WHERE r.lesson_id=l.id)'), 15)
        self.assertEqual(self.scalar('SELECT count(*) FROM lesson l WHERE NOT EXISTS(SELECT 1 FROM lesson_teacher t WHERE t.lesson_id=l.id)'), 0)

    def test_timezone_changes_with_daylight_saving(self):
        self.assertEqual(utc('22-09-2026', '08:30'), '2026-09-22T06:30:00Z')
        self.assertEqual(utc('02-11-2026', '08:30'), '2026-11-02T07:30:00Z')

    def test_supplementary_tutoring_is_not_merged(self):
        rows = self.db.execute("SELECT title FROM course WHERE source_key LIKE 'agenda:course:aux:%' ORDER BY title").fetchall()
        self.assertEqual([r['title'] for r in rows], ['Tutorato Analisi Matematica 1', 'Tutorato Analisi Matematica 3'])
        self.assertEqual(self.manifest['unmatched_timetable_courses'], [])

    def test_foreign_keys_reject_wrong_course_offering(self):
        memory = sqlite3.connect(':memory:')
        self.db.backup(memory)
        memory.execute('PRAGMA foreign_keys=ON')
        pcid, cid = memory.execute('SELECT id,course_id FROM plan_course LIMIT 1').fetchone()
        oid = memory.execute('SELECT id FROM course_offering WHERE course_id<>? LIMIT 1', (cid,)).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            memory.execute('INSERT INTO plan_course_offering VALUES (?,?,?,1)', (pcid,oid,cid))
        memory.close()

    def test_javascript_payload_is_parsed_without_execution(self):
        self.assertEqual(assignment(b'var elenco_anni = [{"valore":"FAN-0|1"}];', 'elenco_anni'), [{'valore':'FAN-0|1'}])
        with self.assertRaises(ValueError):
            assignment(b'var elenco_anni = evil();', 'elenco_anni')

    def test_example_queries_execute(self):
        params = {'programme_id':1, 'study_plan_id':1, 'lesson_id':1, 'room_id':1,
                  'from_utc':'2026-09-20T22:00:00Z', 'to_utc':'2026-09-27T22:00:00Z'}
        buf = ''
        count = 0
        for line in (ROOT / 'examples/queries.sql').read_text().splitlines(keepends=True):
            buf += line
            if sqlite3.complete_statement(buf):
                self.db.execute(buf, params).fetchall()
                count += 1
                buf = ''
        self.assertEqual(count, 7)


if __name__ == '__main__':
    unittest.main()

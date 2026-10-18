import sqlite3
import unittest

from bs4 import BeautifulSoup

from unimi.audit import catalogue_totals, compare
from unimi.build import Store
from unimi.sources import ROOT


class ProgrammeAuditTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript((ROOT / 'schema.sql').read_text())
        self.db.execute("INSERT INTO source(id,url,fetched_at,sha256,path) VALUES('s','https://www.unimi.it','2026-10-18',?,'x')", ('0' * 64,))
        store = Store(self.db)
        self.programme = store.entity('programme', 'course-one', 'Corso Uno', 's', props={'level': 'bachelor'})
        self.faculty = store.entity('faculty', 'faculty-one', 'Facoltà Uno', 's')
        self.rows = [{'url': 'course-one', 'name': 'Corso Uno'}]
        self.store = store

    def tearDown(self):
        self.db.close()

    def test_equal_totals_do_not_hide_a_different_course(self):
        different = [{'url': 'course-two', 'name': 'Corso Due'}]
        report = compare(self.db, [different], {'Facoltà Uno': different})
        self.assertEqual(report['published_unique'], report['database_degrees'])
        self.assertEqual(report['missing_programmes'], different)
        self.assertEqual(report['database_only_ids'], [self.programme])

    def test_present_course_with_missing_faculty_relation_is_reported(self):
        report = compare(self.db, [self.rows], {'Facoltà Uno': self.rows})
        self.assertEqual(report['missing_programmes'], [])
        self.assertEqual(report['faculties'][0]['missing_relations'], [self.programme])

    def test_complete_course_and_faculty_association_pass(self):
        self.store.relate(self.programme, 'belongs_to', self.faculty, 's')
        report = compare(self.db, [self.rows], {'Facoltà Uno': self.rows})
        row = report['faculties'][0]
        self.assertEqual((row['published'], row['present'], row['linked']), (1, 1, 1))
        self.assertEqual(row['missing_relations'], [])
        self.assertEqual(report['without_faculty_in_source'], [])


class CatalogueHeaderTests(unittest.TestCase):
    def test_filtered_total_is_distinct_from_global_total(self):
        doc = BeautifulSoup('<p>2 corsi su 99</p>', 'html.parser')
        self.assertEqual(catalogue_totals(doc), [(2, 99)])

    def test_single_course_uses_singular_header(self):
        doc = BeautifulSoup('<p>1 corso su 82</p>', 'html.parser')
        self.assertEqual(catalogue_totals(doc), [(1, 82)])

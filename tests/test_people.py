import json
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
import sqlite3
import unittest
from bs4 import BeautifulSoup

from unimi.build import Store, directory_valid, import_directory, import_person, record_directory_coverage
from unimi.collect import directory_page_number, directory_url
from unimi.parse import directory_rows, person_extras
from unimi.sources import ROOT, Document


def directory_html(category='395', page=0, last=0):
    return f'''<select name="ur_tipi_ruoli_target_id"><option selected value="{category}">Docenti</option></select>
      <div class="view-chi-e-dove"><div class="views-row"><article>
      <div class="field--name-title"><a href="/it/ugov/person/test">Persona Test</a></div>
      <div class="field--name-ur-tipi-ruoli"><div class="field--item">Docenti</div>
      <div class="field--item">Professori a Contratto</div></div></article></div>
      <nav class="pager-nav"><a aria-current="page">{page+1}</a>
      <a href="?ur_tipi_ruoli_target_id={category}&amp;page=%2C{last}">Ultima</a></nav></div>
      <footer><article><a href="/it/ugov/person/footer">Footer</a></article></footer>'''


class PeopleTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript((ROOT / 'schema.sql').read_text())
        for key in ['s','d0','d2']:
            self.db.execute('INSERT INTO source(id,url,fetched_at,sha256,path) VALUES(?,?,?, ?,?)',
                            (key,'https://www.unimi.it','2026-10-18','0'*64,'x'))

    def tearDown(self):
        self.db.close()

    def test_directory_uses_only_results_and_keeps_multiple_categories(self):
        doc = BeautifulSoup(directory_html(), 'html.parser')
        rows = directory_rows(doc)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['categories'], ['Docenti','Professori a Contratto'])
        wrong = BeautifulSoup(directory_html().replace('<div class="field--item">Docenti</div>', ''), 'html.parser')
        self.assertFalse(directory_valid(wrong, {'category_code':'395','page':0}))
        self.assertFalse(directory_valid(doc, {'category_code':'396','page':0}))
        self.assertFalse(directory_valid(doc, {'category_code':'395','page':2}))
        self.assertTrue(directory_valid(doc, {'category_code':'395','page':0}))
        second = BeautifulSoup(directory_html(page=1).replace('>2</a>', '><span>Pagina attuale</span>2</a>'), 'html.parser')
        self.assertTrue(directory_valid(second, {'category_code':'395','page':1}))

    def test_comma_pagination_preserves_filters(self):
        self.assertEqual(directory_page_number(directory_url('399', 88)), 88)
        self.assertIn('ur_tipi_ruoli_target_id=399', directory_url('399', 88))
        self.assertNotIn('page=', directory_url('399', 0))

    def test_missing_middle_page_is_not_complete(self):
        documents = []
        for page in [0,2]:
            raw = directory_html(page=page,last=2).encode()
            documents.append((directory_url('395',page),{'kind':'directory','category_code':'395','page':page},
                              Document({'key':f'd{page}'},raw)))
        record_directory_coverage(self.db, {}, documents, {})
        self.assertEqual(self.db.execute("SELECT status,expected_count,collected_count FROM coverage WHERE scope='directory_pages:395'").fetchone(), ('partial',3,2))
        self.assertIsNone(self.db.execute("SELECT expected_count FROM coverage WHERE scope='directory_profiles:395'").fetchone()[0])

    def test_directory_alias_does_not_duplicate_profile_and_enables_teacher_view(self):
        canonical = 'https://www.unimi.it/it/ugov/rubrica/person0000042'
        store = Store(self.db, {'https://www.unimi.it/it/ugov/person/test':canonical})
        key = store.entity('person',canonical,'Persona Test','s',props={'email':'test@unimi.it','detail_collected':True})
        import_directory(store,directory_url('395'),{'category_code':'395','page':0},Document({'key':'d0'}),
                         BeautifulSoup(directory_html(),'html.parser'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM person').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM teacher').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM directory_membership').fetchone()[0],2)
        props = json.loads(self.db.execute('SELECT properties FROM person WHERE id=?',(key,)).fetchone()[0])
        self.assertEqual(props['email'],'test@unimi.it')

    def test_enrichment_keeps_years_cv_and_selected_publications_separate(self):
        raw = '''<script data-drupal-selector="drupal-settings-json">{"path":{"currentPath":"ugov/rubrica/person0000042"}}</script>
          <h1>Persona Test</h1><div class="ugov-rubrica">
          <div class="icon doc"><a href="https://work.unimi.it/cv.pdf">CV</a></div>
          <a href="https://expertise.unimi.it/get/person/test">Ricerca</a>
          <div class="item-list"><h3>A.A. 2026/2027</h3>
          <a href="/it/corsi/insegnamenti-dei-corsi-di-laurea/2027/test">Insegnamento</a></div>
          <div class="item-list"><h3>A.A. 2025/2026</h3>
          <a href="/it/corsi/insegnamenti-dei-corsi-di-laurea/2026/test">Insegnamento</a></div>
          <div class="field--name-ur-body"><ul><li><div class="iris-titolo">Citazione</div>
          <a href="https://air.unimi.it/handle/2434/1">Dettaglio</a></li></ul></div></div>'''
        doc = BeautifulSoup(raw,'html.parser')
        props, rows = person_extras(doc)
        self.assertEqual([r['academic_year'] for r in rows],[2026,2025])
        self.assertEqual(props['cv_url'],'https://work.unimi.it/cv.pdf')
        self.assertEqual(len(props['featured_publications']),1)
        self.assertFalse(props['featured_publications_complete'])
        store = Store(self.db)
        import_person(store,'https://www.unimi.it/it/ugov/person/test',{},Document({'key':'s'}),doc)
        self.assertEqual(self.db.execute('SELECT count(*) FROM teaching_assignment').fetchone()[0],2)
        years = sorted(json.loads(r[0])['academic_year'] for r in self.db.execute("SELECT properties FROM relation WHERE predicate='taught_by'"))
        self.assertEqual(years,[2025,2026])


class IncrementalBuildTests(unittest.TestCase):
    def test_people_refresh_preserves_other_entities_and_failed_refresh_is_atomic(self):
        from unimi import build as builder, sources
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_dir = root / 'data/raw'
            raw_dir.mkdir(parents=True)
            (root / 'schema.sql').write_text((ROOT / 'schema.sql').read_text())
            output = root / 'data/unimi.sqlite'
            target = 'https://www.unimi.it/it/ugov/person/test'
            directory_target = directory_url('395')
            profile = b'''<h1>Persona Test</h1><script data-drupal-selector="drupal-settings-json">{"path":{"currentPath":"ugov/rubrica/person0000042"}}</script><div class="ugov-rubrica"><div class="field--name-ur-ruolo">Professore Ordinario</div></div>'''
            jobs = {}
            with patch.object(sources, 'ROOT', root), patch.object(sources, 'RAW', raw_dir), \
                 patch.object(builder, 'ROOT', root), patch.object(builder, 'RAW', raw_dir), \
                 patch.object(builder, 'COLLECTION', root / 'data/collection.json'):
                for address, raw, kind in [(target, profile, 'person'), (directory_target, directory_html().encode(), 'directory')]:
                    key = hashlib.sha256(address.encode()).hexdigest()
                    meta = {'key':key,'url':address,'final_url':address,'fetched_at':'2026-10-18',
                            'status':200,'content_type':'text/html','error':None,'sha256':hashlib.sha256(raw).hexdigest()}
                    sources.Sources.save(meta,raw)
                    jobs[address] = {'kind':kind,'status':200,'source_key':key}
                    if kind == 'directory': jobs[address].update(category_code='395',page=0)
                (root / 'data/collection.json').write_text(json.dumps({'jobs':jobs}))
                with sqlite3.connect(output) as db:
                    db.executescript((root / 'schema.sql').read_text())
                    db.execute('INSERT INTO source(id,url,fetched_at,sha256,path) VALUES(?,?,?,?,?)',('old',target,'2026-10-18','0'*64,'x'))
                    Store(db).entity('department','department:keep','Dipartimento da conservare','old')
                    db.execute("INSERT INTO coverage VALUES('study_plan_source_rows','complete',10,10,'test')")
                builder.build(output,people_only=True)
                with sqlite3.connect(output) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM department').fetchone()[0],1)
                    self.assertEqual(db.execute('SELECT count(*) FROM academic_staff').fetchone()[0],1)
                    self.assertEqual(db.execute("SELECT expected_count,collected_count FROM coverage WHERE scope='study_plan_source_rows'").fetchone(),(10,10))
                before = output.read_bytes()
                with patch.object(builder, 'import_person', side_effect=ValueError('interruzione simulata')):
                    with self.assertRaisesRegex(ValueError,'interruzione simulata'):
                        builder.build(output,people_only=True)
                self.assertEqual(output.read_bytes(),before)
                self.assertFalse(output.with_suffix('.building.sqlite').exists())


if __name__ == '__main__':
    unittest.main()

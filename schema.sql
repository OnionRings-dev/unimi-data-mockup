-- Identificativi stabili, proprietà estensibili e relazioni con provenienza.
PRAGMA foreign_keys = ON;
CREATE TABLE source (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    final_url TEXT,
    fetched_at TEXT NOT NULL,
    status INTEGER,
    content_type TEXT,
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    path TEXT NOT NULL,
    error TEXT,
    request_metadata TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(request_metadata))
) STRICT;
CREATE TABLE entity (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN (
        'faculty','school','department','organisation','programme','programme_offering',
        'study_plan','course','course_offering','edition','person','site','room',
        'agenda_programme','agenda_teacher','agenda_activity','doctoral_course')),
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    code TEXT,
    academic_year INTEGER,
    url TEXT,
    properties TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(properties)),
    source_id TEXT NOT NULL REFERENCES source(id)
) STRICT;
CREATE TABLE identifier (
    value TEXT NOT NULL,
    entity_id TEXT NOT NULL REFERENCES entity(id),
    PRIMARY KEY(value, entity_id)
) STRICT;
CREATE TABLE observation (
    entity_id TEXT NOT NULL REFERENCES entity(id),
    source_id TEXT NOT NULL REFERENCES source(id),
    properties TEXT NOT NULL CHECK(json_valid(properties)),
    PRIMARY KEY(entity_id, source_id)
) STRICT;
CREATE TABLE relation (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES entity(id),
    predicate TEXT NOT NULL CHECK(predicate IN (
        'belongs_to','part_of','includes','taught_by','member_of','located_in',
        'version_of','edition_of','responsible_for','listed_in','references')),
    object_id TEXT NOT NULL REFERENCES entity(id),
    source_id TEXT NOT NULL REFERENCES source(id),
    properties TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(properties)),
    CHECK(subject_id <> object_id)
) STRICT;
CREATE TABLE coverage (
    scope TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('complete','partial','unavailable','not_collected')),
    expected_count INTEGER,
    collected_count INTEGER NOT NULL CHECK(collected_count >= 0),
    notes TEXT NOT NULL
) STRICT;
CREATE INDEX entity_kind ON entity(kind, academic_year);
CREATE INDEX entity_code ON entity(code);
CREATE INDEX relation_object ON relation(object_id, predicate);
CREATE INDEX relation_subject ON relation(subject_id, predicate);
CREATE VIEW programme AS SELECT id,name,code,academic_year,url,
    json_extract(properties,'$.level') AS level,properties,source_id
    FROM entity WHERE kind='programme';
CREATE VIEW faculty AS SELECT * FROM entity WHERE kind IN ('faculty','school');
CREATE VIEW department AS SELECT * FROM entity WHERE kind='department';
CREATE VIEW course AS SELECT * FROM entity WHERE kind='course';
CREATE VIEW course_offering AS SELECT * FROM entity WHERE kind='course_offering';
CREATE VIEW person AS SELECT * FROM entity WHERE kind='person';
CREATE VIEW teacher AS SELECT p.* FROM person p WHERE
    EXISTS(SELECT 1 FROM relation r WHERE r.object_id=p.id AND r.predicate='taught_by')
    OR lower(json_extract(p.properties,'$.role')) LIKE '%professor%'
    OR lower(json_extract(p.properties,'$.role')) LIKE '%ricercator%'
    OR lower(json_extract(p.properties,'$.role')) LIKE '%docent%';
CREATE VIEW agenda_teacher AS SELECT * FROM entity WHERE kind='agenda_teacher';
CREATE VIEW site AS SELECT * FROM entity WHERE kind='site';
CREATE VIEW room AS SELECT id,name,code,json_extract(properties,'$.capacity') AS capacity,
    json_extract(properties,'$.address') AS address,
    json_extract(properties,'$.latitude') AS latitude,json_extract(properties,'$.longitude') AS longitude,
    properties,source_id FROM entity WHERE kind='room';
CREATE VIEW programme_faculty AS
    SELECT DISTINCT p.id AS programme_id, p.name AS programme_name,
        f.id AS faculty_id, f.name AS faculty_name
    FROM entity p JOIN relation r ON r.subject_id=p.id AND r.predicate='belongs_to'
    JOIN entity f ON f.id=r.object_id AND f.kind IN ('faculty','school')
    WHERE p.kind='programme';
CREATE VIEW room_site AS
    SELECT DISTINCT r.id AS room_id,r.name AS room_name,r.code AS room_code,
        json_extract(r.properties,'$.capacity') AS capacity,s.id AS site_id,s.name AS site_name,
        json_extract(r.properties,'$.address') AS address,
        json_extract(r.properties,'$.latitude') AS latitude,json_extract(r.properties,'$.longitude') AS longitude
    FROM entity r JOIN relation rel ON rel.subject_id=r.id AND rel.predicate='located_in'
    JOIN entity s ON s.id=rel.object_id WHERE r.kind='room' AND s.kind='site';
CREATE VIEW teaching_assignment AS
    SELECT DISTINCT r.subject_id AS activity_id,a.kind AS activity_kind,a.name AS activity_name,
        r.object_id AS teacher_id,t.name AS teacher_name,r.properties
    FROM relation r JOIN entity a ON a.id=r.subject_id JOIN entity t ON t.id=r.object_id
    WHERE r.predicate='taught_by' AND t.kind IN ('person','agenda_teacher');

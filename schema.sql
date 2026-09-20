-- Schema v1: un file per snapshot. Il seed è generato dalle fonti archiviate.
-- Gli anni accademici sono rappresentati dall'anno iniziale: 2026 = 2026/2027.
-- source_key: identificativo normalizzato con namespace e contesto della fonte.
PRAGMA foreign_keys = ON;
BEGIN;

CREATE TABLE snapshot (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL UNIQUE,
    academic_year INTEGER NOT NULL CHECK (academic_year BETWEEN 1900 AND 2200),
    acquisition_started_at TEXT NOT NULL,
    acquisition_finished_at TEXT NOT NULL,
    simulation_date TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Europe/Rome',
    schema_version INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    CHECK (acquisition_finished_at >= acquisition_started_at)
);

CREATE TABLE source_document (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    request_method TEXT NOT NULL CHECK (request_method IN ('GET', 'POST', 'LOCAL')),
    request_parameters_json TEXT NOT NULL DEFAULT '{}',
    fetched_at TEXT NOT NULL,
    http_status INTEGER,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    raw_path TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE academic_unit (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('faculty', 'school', 'department')),
    url TEXT,
    source_id INTEGER NOT NULL REFERENCES source_document(id)
);

CREATE TABLE degree_programme (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    level TEXT NOT NULL CHECK (level IN ('bachelor', 'master', 'single_cycle')),
    website_url TEXT,
    notes TEXT,
    source_id INTEGER NOT NULL REFERENCES source_document(id)
);

CREATE TABLE programme_unit (
    programme_id INTEGER NOT NULL REFERENCES degree_programme(id),
    unit_id INTEGER NOT NULL REFERENCES academic_unit(id),
    role TEXT NOT NULL CHECK (role IN ('coordinator', 'participant', 'unspecified')),
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    PRIMARY KEY (programme_id, unit_id)
);

CREATE TABLE programme_version (
    id INTEGER PRIMARY KEY,
    programme_id INTEGER NOT NULL REFERENCES degree_programme(id),
    source_key TEXT NOT NULL UNIQUE,
    university_code TEXT,
    degree_class TEXT,
    cohort_from INTEGER,
    cohort_to INTEGER,
    duration_years INTEGER CHECK (duration_years > 0),
    ects REAL CHECK (ects >= 0),
    language_label TEXT,
    location_label TEXT,
    delivery_mode TEXT,
    status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (status IN ('active', 'phasing_out', 'inactive', 'unknown')),
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    CHECK (cohort_to IS NULL OR cohort_from IS NULL OR cohort_to >= cohort_from)
);

CREATE TABLE study_plan (
    id INTEGER PRIMARY KEY,
    programme_version_id INTEGER NOT NULL REFERENCES programme_version(id),
    source_key TEXT NOT NULL UNIQUE,
    academic_year INTEGER NOT NULL,
    curriculum_label TEXT NOT NULL,
    choice_rules TEXT,
    source_id INTEGER NOT NULL REFERENCES source_document(id)
);

CREATE TABLE course (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    university_code TEXT,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'unknown'
        CHECK (kind IN ('teaching', 'internship', 'final_exam', 'language', 'other', 'unknown')),
    source_id INTEGER NOT NULL REFERENCES source_document(id)
);

CREATE TABLE course_sector (
    course_id INTEGER NOT NULL REFERENCES course(id),
    sector_code TEXT NOT NULL,
    ects REAL CHECK (ects >= 0),
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    PRIMARY KEY (course_id, sector_code)
);

CREATE TABLE plan_course (
    id INTEGER PRIMARY KEY,
    study_plan_id INTEGER NOT NULL REFERENCES study_plan(id),
    course_id INTEGER NOT NULL REFERENCES course(id),
    source_key TEXT NOT NULL UNIQUE,
    study_year INTEGER CHECK (study_year > 0),
    period_label TEXT,
    requirement TEXT NOT NULL DEFAULT 'unknown'
        CHECK (requirement IN ('mandatory', 'elective', 'free_choice', 'unknown')),
    choice_group TEXT,
    ects REAL CHECK (ects >= 0),
    activation_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (activation_status IN ('active', 'future', 'inactive', 'unknown')),
    expected_activation_year INTEGER,
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    UNIQUE (id, course_id)
);

CREATE TABLE course_offering (
    id INTEGER PRIMARY KEY,
    course_id INTEGER NOT NULL REFERENCES course(id),
    source_key TEXT NOT NULL UNIQUE,
    academic_year INTEGER NOT NULL,
    edition_label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (status IN ('active', 'inactive', 'unknown')),
    ects REAL CHECK (ects >= 0),
    total_hours REAL CHECK (total_hours >= 0),
    language_label TEXT,
    period_label TEXT,
    objectives TEXT,
    syllabus TEXT,
    prerequisites TEXT,
    assessment TEXT,
    teaching_methods TEXT,
    materials TEXT,
    website_url TEXT,
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    UNIQUE (id, course_id)
);

CREATE TABLE plan_course_offering (
    plan_course_id INTEGER NOT NULL,
    offering_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    PRIMARY KEY (plan_course_id, offering_id),
    FOREIGN KEY (plan_course_id, course_id) REFERENCES plan_course(id, course_id),
    FOREIGN KEY (offering_id, course_id) REFERENCES course_offering(id, course_id)
);

CREATE TABLE course_module (
    id INTEGER PRIMARY KEY,
    offering_id INTEGER NOT NULL REFERENCES course_offering(id),
    source_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    ects REAL CHECK (ects >= 0),
    total_hours REAL CHECK (total_hours >= 0),
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    UNIQUE (id, offering_id)
);

CREATE TABLE teaching_activity (
    id INTEGER PRIMARY KEY,
    offering_id INTEGER NOT NULL REFERENCES course_offering(id),
    module_id INTEGER,
    source_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('general', 'lecture', 'exercise', 'lab', 'other')),
    group_label TEXT,
    total_hours REAL CHECK (total_hours >= 0),
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    FOREIGN KEY (module_id, offering_id) REFERENCES course_module(id, offering_id)
);

CREATE TABLE teacher (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    university_code TEXT,
    display_name TEXT NOT NULL,
    institutional_email TEXT,
    profile_url TEXT,
    source_id INTEGER NOT NULL REFERENCES source_document(id)
);

CREATE TABLE activity_teacher (
    activity_id INTEGER NOT NULL REFERENCES teaching_activity(id),
    teacher_id INTEGER NOT NULL REFERENCES teacher(id),
    role TEXT NOT NULL DEFAULT 'unspecified'
        CHECK (role IN ('responsible', 'lecturer', 'exercise_teacher', 'tutor', 'unspecified')),
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    PRIMARY KEY (activity_id, teacher_id, role)
);

-- Destinatari effettivamente pubblicati nell'Agenda; include precorsi/tutorati
-- che non compaiono nei piani. Il gruppo è il filtro originale del gestionale.
CREATE TABLE activity_audience (
    activity_id INTEGER NOT NULL REFERENCES teaching_activity(id),
    programme_id INTEGER NOT NULL REFERENCES degree_programme(id),
    programme_code TEXT NOT NULL,
    study_year INTEGER CHECK (study_year > 0),
    group_code TEXT NOT NULL,
    group_label TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    PRIMARY KEY (activity_id, programme_id, group_code)
);

CREATE TABLE building (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    university_code TEXT,
    name TEXT NOT NULL,
    address TEXT,
    source_id INTEGER NOT NULL REFERENCES source_document(id)
);

CREATE TABLE room (
    id INTEGER PRIMARY KEY,
    building_id INTEGER REFERENCES building(id),
    source_key TEXT NOT NULL UNIQUE,
    university_code TEXT,
    name TEXT NOT NULL,
    capacity INTEGER CHECK (capacity >= 0),
    source_id INTEGER NOT NULL REFERENCES source_document(id)
);

CREATE TABLE lesson (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    source_event_id TEXT,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    delivery_mode TEXT NOT NULL DEFAULT 'unknown'
        CHECK (delivery_mode IN ('in_person', 'online', 'hybrid', 'unknown')),
    status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (status IN ('scheduled', 'cancelled', 'unknown')),
    online_url TEXT,
    notes TEXT,
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    CHECK (ends_at > starts_at)
);

CREATE TABLE lesson_activity (
    lesson_id INTEGER NOT NULL REFERENCES lesson(id),
    activity_id INTEGER NOT NULL REFERENCES teaching_activity(id),
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    PRIMARY KEY (lesson_id, activity_id)
);

CREATE TABLE lesson_room (
    lesson_id INTEGER NOT NULL REFERENCES lesson(id),
    room_id INTEGER NOT NULL REFERENCES room(id),
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    PRIMARY KEY (lesson_id, room_id)
);

CREATE TABLE lesson_teacher (
    lesson_id INTEGER NOT NULL REFERENCES lesson(id),
    teacher_id INTEGER NOT NULL REFERENCES teacher(id),
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    PRIMARY KEY (lesson_id, teacher_id)
);

-- Le chiusure pubblicate dall'Agenda non sono lezioni annullate.
CREATE TABLE calendar_closure (
    programme_id INTEGER NOT NULL REFERENCES degree_programme(id),
    day TEXT NOT NULL,
    label TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES source_document(id),
    PRIMARY KEY (programme_id, day, label)
);

CREATE TABLE coverage (
    id INTEGER PRIMARY KEY,
    programme_id INTEGER REFERENCES degree_programme(id), -- NULL = ambito ateneo
    domain TEXT NOT NULL CHECK (domain IN ('catalogue', 'teaching', 'timetable')),
    academic_year INTEGER NOT NULL,
    starts_on TEXT, -- date locali ISO, estremi inclusivi
    ends_on TEXT,
    status TEXT NOT NULL DEFAULT 'not_collected'
        CHECK (status IN ('not_collected', 'partial', 'complete', 'unavailable')),
    expected_count INTEGER CHECK (expected_count >= 0),
    collected_count INTEGER CHECK (collected_count >= 0),
    counting_unit TEXT, -- per esempio: versioni, voci piano, richieste settimanali
    notes TEXT NOT NULL,
    CHECK ((starts_on IS NULL AND ends_on IS NULL)
        OR (starts_on IS NOT NULL AND ends_on IS NOT NULL AND ends_on >= starts_on))
);

CREATE INDEX programme_unit_by_unit ON programme_unit(unit_id);
CREATE INDEX versions_by_programme ON programme_version(programme_id);
CREATE INDEX plans_by_version ON study_plan(programme_version_id, academic_year);
CREATE INDEX plan_courses_by_plan ON plan_course(study_plan_id);
CREATE INDEX plan_courses_by_course ON plan_course(course_id);
CREATE INDEX offerings_by_course ON course_offering(course_id, academic_year);
CREATE INDEX plans_by_offering ON plan_course_offering(offering_id);
CREATE INDEX activities_by_offering ON teaching_activity(offering_id);
CREATE INDEX activities_by_teacher ON activity_teacher(teacher_id);
CREATE INDEX activities_by_programme ON activity_audience(programme_id, study_year);
CREATE INDEX lessons_by_start ON lesson(starts_at);
CREATE INDEX lessons_by_activity ON lesson_activity(activity_id, lesson_id);
CREATE INDEX lessons_by_room ON lesson_room(room_id, lesson_id);
CREATE INDEX lessons_by_teacher ON lesson_teacher(teacher_id, lesson_id);

COMMIT;

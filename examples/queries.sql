-- SQLite: i parametri :programme_id, :study_plan_id e :room_id sono ID del dataset.
-- Database popolato: data/releases/2026-09-20/unimi.sqlite.

-- Catalogo per facoltà/scuola: mantiene anche strutture ancora prive di associazioni.
SELECT u.name AS struttura, p.id AS programme_id, p.name AS laurea, p.level
FROM academic_unit AS u
LEFT JOIN programme_unit AS pu ON pu.unit_id = u.id
LEFT JOIN degree_programme AS p ON p.id = pu.programme_id
WHERE u.kind IN ('faculty', 'school')
ORDER BY u.name, p.level, p.name;

-- Attività di un preciso piano/coorte/curriculum, anche quelle prive di calendario.
SELECT c.university_code, c.title, pc.study_year, pc.period_label,
       pc.ects, pc.requirement, pc.choice_group, pc.activation_status
FROM plan_course AS pc
JOIN course AS c ON c.id = pc.course_id
WHERE pc.study_plan_id = :study_plan_id
ORDER BY pc.study_year, c.title;

-- Eventi di una laurea in una finestra UTC semiaperta [from_utc, to_utc).
-- DISTINCT evita duplicazioni per gruppi e attività condivise.
-- Per un singolo studente aggiungere il filtro aa.group_code/aa.study_year.
SELECT DISTINCT l.id, l.starts_at, l.ends_at, l.status
FROM lesson AS l
JOIN lesson_activity AS la ON la.lesson_id = l.id
JOIN activity_audience AS aa ON aa.activity_id = la.activity_id
WHERE aa.programme_id = :programme_id
  AND l.starts_at < :to_utc AND l.ends_at > :from_utc
  AND l.status = 'scheduled'
ORDER BY l.starts_at, l.id;

-- Docenti dichiarati dall'orario e aule: interrogazioni separate evitano
-- il prodotto cartesiano docenti x aule per eventi con più associazioni.
SELECT t.id, t.display_name
FROM lesson_teacher AS lt JOIN teacher AS t ON t.id = lt.teacher_id
WHERE lt.lesson_id = :lesson_id;

SELECT r.id, r.name, b.name AS edificio, b.address
FROM lesson_room AS lr
JOIN room AS r ON r.id = lr.room_id
LEFT JOIN building AS b ON b.id = r.building_id
WHERE lr.lesson_id = :lesson_id;

-- Occupazione dell'aula. Nessun evento NON significa aula certamente libera:
-- il mock copre solo due lauree e non tutte le prenotazioni dell'università.
SELECT l.id, l.starts_at, l.ends_at
FROM lesson AS l JOIN lesson_room AS lr ON lr.lesson_id = l.id
WHERE lr.room_id = :room_id AND l.status = 'scheduled'
  AND l.starts_at < :to_utc AND l.ends_at > :from_utc
ORDER BY l.starts_at;

-- Prima di interpretare un risultato vuoto, verificare la copertura.
SELECT domain, academic_year, starts_on, ends_on, status,
       expected_count, collected_count, counting_unit, notes
FROM coverage
WHERE programme_id = :programme_id OR programme_id IS NULL;

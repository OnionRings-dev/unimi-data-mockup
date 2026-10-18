-- Opzioni di onboarding: percorsi e facoltà, compresi percorsi senza facoltà associata.
SELECT p.id,p.name,p.level,p.academic_year,pf.faculty_id,pf.faculty_name
FROM programme p LEFT JOIN programme_faculty pf ON pf.programme_id=p.id
ORDER BY p.name;

-- Aule con sede, capienza e coordinate pubblicate (precisione non dichiarata).
SELECT room_id,room_name,room_code,capacity,address,latitude,longitude,site_id,site_name
FROM room_site ORDER BY site_name,room_name;

-- Docenti ufficiali e dipartimento di afferenza.
SELECT p.id,p.name,json_extract(p.properties,'$.email') AS email,d.name AS department
FROM teacher p LEFT JOIN relation r ON r.subject_id=p.id AND r.predicate='member_of'
LEFT JOIN department d ON d.id=r.object_id ORDER BY p.name;

-- Attività di un piano, con anno di corso, obbligatorietà e crediti pubblicati.
SELECT p.id AS plan_id,p.name AS curriculum,c.id AS course_offering_id,c.name,
       json_extract(r.properties,'$.study_year') AS study_year,
       json_extract(r.properties,'$.requirement') AS requirement,
       coalesce(json_extract(r.properties,'$.fields."Crediti massimi"'),
                json_extract(r.properties,'$.fields.Crediti')) AS credits
FROM entity p JOIN relation r ON r.subject_id=p.id AND r.predicate='includes'
JOIN course_offering c ON c.id=r.object_id WHERE p.kind='study_plan';

-- Insegnamenti di un percorso, passando per offerte e piani, senza duplicati.
WITH RECURSIVE descendants(id) AS (
    SELECT :programme_id
    UNION
    SELECT r.subject_id FROM relation r JOIN descendants d ON r.object_id=d.id
    WHERE r.predicate IN ('version_of','part_of')
)
SELECT DISTINCT c.id,c.name,c.academic_year FROM descendants d
JOIN relation r ON r.subject_id=d.id AND r.predicate='includes'
JOIN course_offering c ON c.id=r.object_id ORDER BY c.name;

-- Attività/edizioni e docenti: il livello dell'associazione è esplicito.
SELECT * FROM teaching_assignment ORDER BY teacher_name,activity_name;

-- Provenienza di una relazione e campi della singola osservazione.
SELECT r.predicate,s.url,s.fetched_at,r.properties FROM relation r
JOIN source s ON s.id=r.source_id WHERE r.subject_id=:entity_id;
SELECT s.url,o.properties FROM observation o JOIN source s ON s.id=o.source_id
WHERE o.entity_id=:entity_id;

-- Verificare sempre il perimetro prima di interpretare un risultato vuoto.
SELECT * FROM coverage ORDER BY scope;

-- Persone censite nella rubrica e categorie esplicite (una persona può averne più di una).
SELECT person_id,name,category FROM directory_membership ORDER BY name,category;

-- Arricchimento dei profili; i link non implicano che i documenti siano scaricati.
SELECT id,name,json_extract(properties,'$.scientific_group') AS scientific_group,
       json_extract(properties,'$.cv_url') AS cv_url,
       json_extract(properties,'$.expertise_url') AS expertise_url,
       json_extract(properties,'$.publications_url') AS publications_url,
       json_extract(properties,'$.reception_notes') AS reception_notes,
       json_extract(properties,'$.reception_location') AS reception_location
FROM academic_staff ORDER BY name;

-- Didattica pubblicata sul profilo, con anno e fonte della relazione.
SELECT p.name,c.name,c.academic_year,s.url FROM relation r
JOIN person p ON p.id=r.object_id JOIN entity c ON c.id=r.subject_id
JOIN source s ON s.id=r.source_id WHERE r.predicate='taught_by'
AND json_extract(r.properties,'$.scope')='profile_teaching_list'
ORDER BY p.name,c.academic_year DESC,c.name;

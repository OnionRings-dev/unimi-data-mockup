# Dati UniMi

Database locale di dati pubblici della Statale per applicazioni studentesche:
percorsi di studio, strutture, insegnamenti, piani, docenti, sedi e aule.
Include lauree, master universitari, dottorati, specializzazioni e perfezionamento.
Gli eventi delle lezioni e l'occupazione delle aule sono esclusi.

## Utilizzo

Il database è in [`data/unimi.sqlite`](data/unimi.sqlite).
[`data/unimi.json`](data/unimi.json) riporta conteggi e copertura del rilascio.
Si apre con qualsiasi client SQLite, senza avviare un server. Database, cache e
stato della raccolta restano locali e sono esclusi da Git; si rigenerano con i
comandi sotto.

```python
import sqlite3

db = sqlite3.connect('file:data/unimi.sqlite?mode=ro', uri=True)
db.row_factory = sqlite3.Row
for row in db.execute('SELECT id, name, level FROM programme ORDER BY name'):
    print(dict(row))
```

Le viste `programme`, `faculty`, `department`, `course`, `course_offering`,
`person`, `teacher`, `academic_staff`, `directory_membership`, `agenda_teacher`,
`site`, `room`, `programme_faculty`, `room_site` e
`teaching_assignment` offrono punti di accesso semplici. Altri esempi in
[`queries.sql`](queries.sql).

## Snapshot disponibile

Snapshot del 18 ottobre 2026: **591,9 MB** di SQLite (564,5 MiB), senza eventi.

- 181 percorsi di laurea e 276 schede annuali post laurea/formazione continua.
- 31 dipartimenti, 8 facoltà e 3 scuole.
- 14.377 schede annuali di attività con dettaglio U-GOV, più attività senza scheda
  individuale ricavate dai piani; 1.290 piani e 14.993 edizioni. I profili aggiungono
  anche riferimenti a insegnamenti storici senza acquisirne le schede di dettaglio.
- 6.413 profili personali acquisiti, inclusi tutti i 5.758 nominativi unici delle
  sette categorie accademiche di Chi e Dove; `teacher` seleziona 5.370 persone
  con ruolo accademico o assegnazione didattica nelle fonti raccolte.
- 535 spazi: 533 indirizzi e 531 coppie di coordinate pubblicate.
- 366.079 relazioni con provenienza, inclusi gli elenchi didattici dei profili.

Le 28.816 richieste censite includono 24 fonti non raggiunte. Questi conteggi
riguardano il perimetro raccolto; dettagli e limiti in `data/unimi.json` e
[fonti e copertura](docs/sources.md).

## Comandi

È richiesto Python 3.11+; le dipendenze sono fissate in `uv.lock`.

```sh
uv sync
uv run unimi collect
uv run unimi build
uv run unimi check
uv run unimi audit-programmes --live
uv run python -m unittest discover -s tests -v
```

- `collect` scarica le fonti mancanti, con quattro worker e un limite condiviso di
  cinque avvii HTTP al secondo. Una raccolta interrotta si riprende dallo stesso
  comando. Le risposte già acquisite rimangono congelate.
- `collect --retry-failed` riprova una volta per esecuzione gli errori di trasporto
  e gli HTTP transitori. Non forza i blocchi o ripete i `404`.
- `collect --indexes-only` raccoglie cataloghi, piani e indici, rimandando le schede
  degli insegnamenti e i profili personali.
- `collect --people-only` censisce tutte le pagine delle sette categorie accademiche
  di Chi e Dove e acquisisce i profili mancanti, senza ripercorrere i cataloghi.
- `build --people-only` aggiorna rubrica e profili su una copia del database
  esistente, conservando gli altri dati e sostituendo il rilascio dopo i controlli.
  La prima costruzione richiede `build` completo.
- `audit-programmes` confronta i percorsi di laurea con i due cataloghi e tutti
  i filtri per facoltà: verifica le identità e le associazioni, non soltanto i
  conteggi. `--live` rilegge le fonti attuali senza modificare lo snapshot.
  Rapporti ed evidenze sono in `data/audits/`; un esito da verificare restituisce
  codice di uscita 1. Senza `--live` controlla le copie già archiviate.
- `build` è interamente offline: verifica gli hash, crea un database temporaneo,
  controlla l'integrità e sostituisce il rilascio soltanto a import riuscito.
  `build --output /tmp/unimi.sqlite` crea una copia separata.

## Modello

Lo [schema](schema.sql) contiene sei tabelle:

- `entity`: entità tipizzate con nome, codice, anno, URL e proprietà JSON.
- `relation`: associazioni direzionali con proprietà e fonte della relazione.
- `identifier`: URL/codici che identificano la stessa entità verificata.
- `observation`: campi pubblicati dalla singola fonte, prima della normalizzazione.
- `source`: provenienza, data, esito HTTP, checksum e percorso della risposta.
- `coverage`: ambiti raccolti, parziali o ancora da raccogliere.

Questa struttura permette di aggiungere informazioni pubblicate senza creare una
nuova tabella per ogni variante di scheda. Le viste SQL espongono le categorie
principali all'applicazione. Gli ID sono stabili per tipo e identità sorgente;
nomi uguali non comportano fusioni.

Facoltà, dipartimenti e corsi sono distinti. Un percorso può avere più offerte e
piani; un insegnamento ha attività annuali ed edizioni con più docenti. Le relazioni
conservano anno, gruppo, requisiti e altre proprietà quando pubblicati.

Le attività senza una scheda individuale, frequenti nelle specializzazioni, hanno
un'identità limitata al piano in cui sono pubblicate e codice universitario `NULL`.
Conservano i crediti, le ore e i docenti disponibili nella tabella sorgente.

I record dell'Agenda rimangono distinti da quelli U-GOV. Le relazioni `references`
segnalano le corrispondenze univoche fra codice attività e anno, o fra codice
numerico del docente e nome completo. Il metodo e le fonti rimangono consultabili;
le corrispondenze non comportano fusioni di entità.

## Fonti e limiti

Vedi [fonti e copertura](docs/sources.md). La raccolta parte dai cataloghi ufficiali,
dalle schede U-GOV, dai siti dipartimentali e dalle selezioni dell'Agenda Web.
Priorità didattica al 2026/2027; i cataloghi post laurea espongono anche il 2025/2026.
Le date di acquisizione effettive sono registrate per ogni fonte.

`complete` in `coverage` riguarda il preciso elenco o insieme di richieste indicato:
non certifica la completezza di tutto l'ateneo. Un profilo collegato può esistere
come riferimento prima che la sua scheda sia stata acquisita. La proprietà
`detail_collected` segnala le schede importate con successo.

Le aule includono indirizzi e coordinate pubblicate dal gestionale, quando presenti.
La fonte non ne dichiara la precisione; non sono punti verificati sul posto.
Le planimetrie e le posizioni interne agli edifici restano da reperire.
Per informazioni operative aggiornate restano di riferimento i servizi UniMi.

## Struttura

```text
unimi/                 raccolta, parser, importazione e CLI
schema.sql             schema SQLite e viste per l'app
queries.sql            query di esempio
tests/                 verifiche dei parser, identità e dataset
docs/sources.md        fonti e limiti
data/collection.json   perimetro e stato delle richieste
data/raw/              risposte gzip e metadati JSON
data/unimi.sqlite      database pronto
data/unimi.json        conteggi e copertura
```

# UniMi — dataset SQLite statico

Database popolato con dati reali delle fonti pubbliche UniMi, congelati il
**20 settembre 2026**, per l'anno accademico **2026/2027**.

**[Apri il database](data/releases/2026-09-20/unimi.sqlite)** ·
[Copertura e limiti](docs/dataset.md) ·
[Manifest del rilascio](data/releases/2026-09-20/manifest.json)

| Contenuto | Quantità |
| --- | ---: |
| Facoltà e scuole | 10 |
| Corsi di laurea | 181 |
| Versioni dei corsi | 185 |
| Piani/coorti di Informatica e Fisica triennali | 6 |
| Voci dei piani didattici | 226 |
| Attività formative distinte | 220, incluse 2 attività di tutorato |
| Edizioni | 255, comprese quelle dichiarate inattive |
| Docenti | 144 |
| Lezioni distinte nel primo semestre | 2.189 |
| Aule | 32 |
| Fonti archiviate | 445 |

Il catalogo copre tutte le voci dei due elenchi ufficiali di lauree. Il dettaglio
didattico e gli orari coprono **Informatica e Fisica triennali**. Le altre lauree
hanno copertura `not_collected` per insegnamenti e orari: un risultato vuoto non
significa che non abbiano insegnamenti.

Gli orari comprendono le occorrenze **pubblicate al momento dell'acquisizione**
nella finestra **21/09/2026–15/01/2027**. Quindici lezioni non hanno un'aula
indicata dalla fonte. I dati mancanti rimangono `NULL`; i dati non vengono aggiornati
quando cambia il sito dell'università.

## Consultazione

Il database è già pronto: non serve eseguire la raccolta. Si può aprire con qualsiasi
client SQLite o con la libreria standard Python:

```python
import sqlite3

db = sqlite3.connect(
    'file:data/releases/2026-09-20/unimi.sqlite?mode=ro', uri=True
)
db.row_factory = sqlite3.Row
for row in db.execute('SELECT id, name, level FROM degree_programme ORDER BY name'):
    print(dict(row))
```

- [Query SQL di esempio](examples/queries.sql): catalogo, piani, orari, docenti e aule.
- [Schema relazionale](schema.sql): 25 tabelle, incluse le relazioni e i metadati.
- [Studio delle fonti e motivazioni del modello](docs/proposta.md).

Gli istanti delle lezioni sono UTC (`YYYY-MM-DDTHH:MM:SSZ`); visualizzarli in
`Europe/Rome` per gestire correttamente l'ora legale. Per una demo stabile usare
`snapshot.simulation_date`, impostata a `2026-09-21`, al posto della data odierna.
Le chiusure sono in `calendar_closure`. `activity_audience` collega le attività
ai destinatari effettivamente pubblicati nell'agenda, inclusi i tutorati.

## Ricostruzione offline

Dalla directory del progetto, installare la dipendenza del parser nell'ambiente
Python, ad esempio con `uv`:

```sh
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m unimi_mock.build
.venv/bin/python -m unittest discover -s tests -v
```

`build` legge esclusivamente i file di `data/raw/2026-09-20/`, verifica gli hash,
crea un file temporaneo, verifica l'integrità e sostituisce il database di rilascio
solo a import completato. Il risultato è deterministico dalle stesse fonti e dallo
stesso schema. Per creare una copia senza sostituire il rilascio:

```sh
.venv/bin/python -m unimi_mock.build --output /tmp/unimi-check/unimi.sqlite
```

L'acquisizione originale è ripetibile con:

```sh
.venv/bin/python -m unimi_mock.collect --offline
```

Senza `--offline`, `collect` scarica soltanto richieste ancora assenti dalla cache.
Non aggiorna le risposte già congelate. Per uno snapshot di un altro periodo occorre
configurare un nuovo percorso, anno e intervallo: questa prima versione è
deliberatamente dedicata al rilascio 2026/2027.

## Provenienza

`data/raw/2026-09-20/manifest.json` registra URL, parametri, timestamp, stato HTTP,
percorso e SHA-256 di ogni risposta. `source_document` e le foreign key `source_id`
permettono di risalire alle fonti. Il manifest di rilascio riporta conteggi, copertura,
corrispondenze dei codici, campi mancanti e checksum del database e dello schema.

Le fonti sono il catalogo e le schede pubbliche su `www.unimi.it` e l'Agenda Web su
`orari.unimi.it`. È un dataset per sviluppo e demo: per l'organizzazione delle lezioni
effettive resta necessario consultare i servizi ufficiali aggiornati.

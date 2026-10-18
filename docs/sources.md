# Fonti e copertura

Le copie delle risposte pubbliche sono in `data/raw/`, compresse con gzip.
Ogni risposta ha un JSON con URL, URL finale, esito, timestamp UTC e SHA-256 del
contenuto archiviato non compresso. Il database importa anche le fonti fallite e mantiene separato
il censimento delle richieste (`data/collection.json`) dai dati estratti.

## Raccolta iniziale

Il censimento del 18 ottobre 2026 comprende 28.816 richieste: 28.792 risposte
HTTP 200, 19 risposte 404 e cinque errori di trasporto. La riuscita HTTP non
certifica l’avvenuta estrazione: `coverage` riporta separatamente schede
normalizzate e righe di piano.

I cataloghi contengono 181 percorsi di laurea per il 2026/2027 e 276 schede
annuali post laurea/formazione continua, per un totale di 457 schede. Non sono
457 percorsi logicamente distinti: alcune annualità dello stesso percorso
rimangono record separati. Le 76.019 righe di piano delle 1.216 pagine acquisite
sono state confrontate con le celle pubblicate; includono ripetizioni fra URL
e offerte, e non rappresentano 76.019 insegnamenti distinti.

## Fonti implementate

- [Lauree triennali e ciclo unico](https://www.unimi.it/it/corsi/corsi-di-laurea-triennali-e-magistrali-ciclo-unico)
  e [magistrali](https://www.unimi.it/it/corsi/corsi-di-laurea-magistrale): cataloghi,
  filtri per facoltà, schede, offerte/coorti, piani e insegnamenti collegati.
- [Master](https://www.unimi.it/it/corsi/corsi-post-laurea-e-formazione-continua/master-e-perfezionamento/catalogo-master),
  [dottorati](https://www.unimi.it/it/corsi/corsi-post-laurea-e-formazione-continua/corsi-di-dottorato-phd),
  [specializzazioni](https://www.unimi.it/it/corsi/corsi-post-laurea-e-formazione-continua/catalogo-scuole-di-specializzazione)
  e [perfezionamento](https://www.unimi.it/it/corsi/corsi-post-laurea-e-formazione-continua/master-e-perfezionamento/catalogo-corsi-di-perfezionamento):
  elenchi e schede per gli anni pubblicati; gli anni rimangono distinti.
- [Catalogo dottorale](https://www.unimi.it/it/corsi/corsi-post-laurea-e-formazione-continua/corsi-di-dottorato-phd/catalogo-degli-insegnamenti-la-formazione-dottorale):
  paginazione e schede degli insegnamenti collegati.
- [Strutture](https://www.unimi.it/it/ateneo/uffici-e-strutture): dipartimenti,
  facoltà/scuole e schede organizzative. Il centro CFI è un'organizzazione distinta.
  I siti dipartimentali forniscono indici di insegnamenti e personale.
- Schede U-GOV di insegnamenti e persone: codici, CFU, ore, lingua, edizioni,
  docenti, programma, campi descrittivi, ruolo, afferenza e contatti istituzionali.
  Gli alias leggibili sono ricondotti al percorso interno esplicitato dalla pagina.
- [Sedi](https://www.unimi.it/it/ateneo/uffici-e-strutture/sedi): schede di indirizzi
  e strutture ospitate. Le sedi istituzionali e quelle Agenda hanno identità separate.
- [Agenda Web](https://orari.unimi.it/PortaleStudenti/): elenchi, gruppi e anagrafica
  degli spazi. La cache conserva solo i metadati statici, senza eventi.

## Rubrica accademica e profili

[Chi e Dove](https://www.unimi.it/it/cerca/chi-e-dove) viene censita nelle sette
categorie accademiche: Docenti, Ricercatori, Professori a Contratto, Visiting
Professor, Visiting Scholar, Assegnisti, Lettori e Collaboratori Linguistici.
Si seguono gli indici pubblici di paginazione e il collegamento all'ultima pagina;
il parametro Drupal `page=,N` mantiene il filtro per categoria. Ogni pagina viene
verificata confrontando categoria selezionata e pagina corrente.

Le categorie possono sovrapporsi. `directory_membership` espone le appartenenze;
`academic_staff` è l'unione deduplicata delle persone censite, mentre `teacher`
seleziona ruoli di docenza/ricerca e persone con assegnazioni didattiche.
La sola categoria Personale TAB non viene censita; può apparire fra le categorie
di persone che hanno anche un ruolo accademico.

La copertura `directory_pages:<codice>` verifica tutte le pagine attese;
`directory_profiles:<codice>` confronta le identità elencate con i profili
acquisiti. `directory_academic_people` conta l'unione senza sommare le categorie.
Questi indicatori distinguono il censimento delle persone dal semplice successo
delle richieste di profili già conosciuti.

Nel rilascio tutte le 198 pagine sono verificate e tutti i 5.758 nominativi unici
hanno un profilo acquisito: 2.109 Docenti, 581 Ricercatori, 2.648 Professori a
Contratto, 444 Assegnisti, 6 Visiting Professor, 21 Visiting Scholar e 19 Lettori
e Collaboratori Linguistici. La somma è maggiore dell'unione perché 70
appartenenze sono ulteriori categorie di persone già contate.

Rispetto al rilascio precedente sono state aggiunte 1.779 identità personali.
Il totale dei profili acquisiti è 6.413: comprende anche persone individuate
tramite altre fonti. I nove URL di profilo che restituiscono 404 non impediscono
la copertura completa degli elenchi accademici della rubrica. Sono disponibili
4.542 link a CV, 3.092 a Expertise e 4.063 all'archivio delle pubblicazioni AIR.


I profili espongono, quando presenti, gruppo scientifico-disciplinare, contatti,
CV, Expertise, archivio AIR, note e luogo di ricevimento. Si conservano i link,
senza scaricare CV, foto o archivi di pubblicazioni. Le pubblicazioni mostrate
nel profilo sono una selezione: `featured_publications_complete` è sempre falso.

Gli elenchi didattici del profilo generano associazioni `taught_by` con
`scope=profile_teaching_list` e anno accademico. I collegamenti degli anni passati
rimangono riferimenti senza dettaglio se la scheda non era già stata acquisita;
non si scaricano tutti gli insegnamenti storici. La presenza di una relazione
nel profilo non dimostra che tutti i ruoli e tutte le edizioni siano pubblicati.
Le afferenze alla stessa struttura rimangono relazioni distinte con fonte.

## Agenda Web

Percorsi relativi a `https://orari.unimi.it/PortaleStudenti/`:

```text
combo.php?sw=ec_&aa=2026&page=corsi
combo.php?sw=ec_&aa=2026&page=docenti
combo.php?sw=ec_&aa=2026&page=attivita
combo.php?sw=rooms_
call_redis.php?key=UNIMI_2026_ec_elenco_anno2_<codice>
rooms_call.php (POST, proiezione area_rooms)
```

Sono chiamate pubbliche del sito, non un'API documentata. Il JSON viene estratto
dagli assegnamenti JavaScript senza eseguirne il codice.
Le selezioni verificate contengono 535 spazi, 3.018 docenti e 6.552 attività.
Le attività comprendono moduli, edizioni e iniziative senza equivalenza necessaria
con un insegnamento di piano. Gli spazi comprendono sedi esterne, ad esempio sportive.
Capienza significa valore dichiarato dal gestionale, non verifica fisica.

Una sola richiesta POST a `rooms_call.php`, selezionando uno spazio per il
18 ottobre 2026 e senza richiedere tutti gli eventi, restituisce anche
`area_rooms`: l’anagrafica globale dei 535 spazi. Si archivia soltanto questo
oggetto; ogni altro contenuto della risposta viene scartato. I metadati della
fonte registrano metodo, parametri, proiezione e hash della risposta originale.
Il checksum del contenuto archiviato riguarda la proiezione, non la risposta
completa. Sono pubblicati 533 indirizzi e 531 coppie di coordinate valide.
La precisione dei punti non è dichiarata: spesso più aule condividono un punto
dell’edificio. Non si estraggono coordinate dal centro della mappa e non si
effettua geocodifica. I campi per planimetrie e posizioni interne sono vuoti.

Le relazioni Agenda docente–corso e corso–attività sono mantenute quando esplicite.
I nomi abbreviati dei docenti nelle attività rimangono dati sorgente: non vengono
trasformati automaticamente in assegnazioni a persone della rubrica.
Le corrispondenze `references` con U-GOV richiedono un codice attività esplicito
e anno concordante, oppure codice numerico personale e nome completo concordanti.
Sono collegamenti tracciati, non fusioni delle identità originarie.

## Limiti espliciti

- Nessuna certificazione di completezza di tutto l'ateneo. I conteggi del rilascio,
  gli errori e gli ambiti raccolti sono in `data/unimi.json` e `coverage`.
- `complete` per una categoria di richieste significa che tutte le richieste
  censite hanno risposto correttamente, non che il parser abbia ricostruito ogni
  relazione possibile o che tutte le fonti universitarie siano già censite.
- Le pagine non raggiungibili e gli indici non disponibili sono segnalati;
  riferimenti a entità possono essere presenti senza una scheda di dettaglio.
- Gli indici dipartimentali collegano docenti e attività annuali. Solo le schede
  degli insegnamenti permettono di attribuire il ruolo alla specifica edizione.
- Le attività prive di un collegamento individuale sono importate dalle righe
  dei piani, comprese le associazioni ai docenti pubblicate nella stessa riga.
  La loro identità rimane legata al piano e il codice universitario è sconosciuto.
- La raccolta didattica privilegia l'offerta 2026/2027; il post laurea include anche
  cataloghi 2025/2026. Non è una ricostruzione di tutto lo storico dell'ateneo.
- Quattro spazi non hanno coordinate valide e due non hanno un indirizzo
  nell’anagrafica raccolta. Planimetrie, posizioni interne, percorsi accessibili,
  biblioteche, mense, alloggi e altri servizi sono estensioni future.
- Facoltà/scuole, dipartimenti e raggruppamenti amministrativi dell'Agenda sono
  concetti diversi e non vengono equiparati in base al nome.
- Il database non contiene lezioni, prenotazioni, occupazione, né disponibilità
  delle aule. Una relazione corso–aula non viene dedotta per mancanza di eventi.

La raccolta si amplia aggiungendo fonti e parser alle categorie esistenti.
I campi Drupal sono conservati anche come osservazioni per consentire ulteriori
normalizzazioni senza scaricare nuovamente la fonte.

## Verifica dei corsi di laurea per facoltà

`uv run unimi audit-programmes --live` rilegge i due cataloghi di laurea e tutti
i loro filtri per facoltà/scuola. Confronta URL identificativi con `identifier`,
controlla le associazioni in `programme_faculty` e segnala corsi assenti, record
presenti solo nel database, relazioni mancanti o in eccesso e strutture ambigue.
I totali pubblicati sono controllati distinguendo il numero selezionato dal
totale generale della pagina. Non si sommano semplicemente i conteggi per
facoltà: un corso può appartenere a più strutture.

Le risposte live sono archiviate separatamente in `data/audits/` con hash,
data di acquisizione e URL; ogni esecuzione produce un `report.json`.
Il controllo usa le diverse viste dello stesso catalogo istituzionale: prova
la copertura di quel catalogo nell’anno pubblicato, non l’assenza di percorsi
fuori catalogo o la completezza di tutti gli insegnamenti. Master, dottorati e
specializzazioni restano verificati separatamente dai rispettivi cataloghi.

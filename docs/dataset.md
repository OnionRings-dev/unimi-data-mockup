# Copertura del rilascio 2026-09-20

Il [database SQLite](../data/releases/2026-09-20/unimi.sqlite) contiene una fotografia
reale del 2026/2027. I conteggi e i controlli riproducibili sono nel
[manifest del rilascio](../data/releases/2026-09-20/manifest.json).

## Catalogo

Sono state acquisite tutte le **99 voci** dell'elenco triennali/ciclo unico e le
**82 voci** dell'elenco magistrali. I conteggi sono quelli dichiarati e verificati
nelle pagine ufficiali, non una stima ricavata dall'agenda. Le associazioni alle
dieci facoltà/scuole derivano dai venti filtri ufficiali del catalogo.

Le 187 associazioni facoltà–laurea comprendono corsi appartenenti a più strutture.
Le 185 versioni comprendono le versioni principali del catalogo e le quattro
versioni/coorti aggiuntive dei due corsi pilota. Non è un censimento di tutti gli
ordinamenti storici di tutte le lauree. I dipartimenti non sono stati censiti.

## Piani didattici

| Laurea | Codice | Coorte di ingresso | Voci del piano |
| --- | --- | --- | ---: |
| Informatica | F1X | 2018/2019–2024/2025 | 34 |
| Informatica | FAA | 2025/2026 | 39 |
| Informatica | FAA | 2026/2027 | 38 |
| Fisica | F63 | 2021/2022–2024/2025 | 37 |
| Fisica | FAN | 2025/2026 | 39 |
| Fisica | FAN | 2026/2027 | 39 |

Tutte le 226 voci dei sei piani e le 218 schede didattiche distinte collegate sono
state acquisite. Le attività comuni possono comparire in più piani. Le attività
future o relative ad annualità non più attive rimangono nel piano con lo stato
originale, senza essere collegate a un'erogazione corrente di quell'annualità.

Il database contiene anche due tutorati pubblicati nell'agenda, per un totale di
220 attività. Hanno codici interni con prefisso `agenda:course:aux:` e non ricevono
CFU o codici U-GOV inventati. Sono collegati ai destinatari tramite `activity_audience`.

Programmi, obiettivi, prerequisiti, modalità d'esame, gruppi, moduli e docenti sono
importati quando presenti. Le 255 edizioni comprendono 150 attive e 105 indicate
come inattive. Quattordici edizioni attive non hanno un programma importabile,
incluse le cinque edizioni/attività identificate soltanto nell'agenda. Il manifest
elenca queste ultime: non vengono associate per somiglianza del titolo a gruppi
potenzialmente differenti.

Sono presenti quattro moduli espliciti con CFU e ore. Il fatto che il titolo di un
insegnamento contenga “modulo” non lo trasforma automaticamente in un sottomodulo:
si conserva la distinzione pubblicata nella scheda.

## Orari

Sono stati interrogati tutti i filtri disponibili per FAA, F1X, FAN e F63 con
`all_events=1`, lo stesso parametro usato dall'interfaccia pubblica per l'elenco
completo. Sono state mantenute le date dal **21 settembre 2026 al 15 gennaio 2027**,
estremi inclusi in ora locale:

| Laurea | Filtri interrogati | Lezioni distinte |
| --- | ---: | ---: |
| Informatica | 7 | 885 |
| Fisica | 3 | 1.304 |

Le risposte contengono anche righe di chiusura: le 26 associazioni corso–giorno di
sospensione sono in `calendar_closure`, separate dalle 2.189 lezioni. Quattro
eventi distinti anteriori alla finestra, relativi al precorso, non sono inclusi.

I suffissi dei codici dei laboratori sono ricondotti al codice base **solo quando
quest'ultimo esiste nelle schede ufficiali**. Le corrispondenze sono nel manifest.
I turni condivisi hanno un'unica lezione collegata a più attività: 2.233 associazioni
lezione–attività non significano 2.233 lezioni.

Ogni lezione ha almeno un docente e un'attività con destinatari riconosciuti.
Sono presenti 32 aule in nove sedi; per 15 lezioni la fonte non riporta un codice
aula. Gli indirizzi degli edifici e le capienze non sono stati integrati da altre
fonti e rimangono `NULL`. Non è quindi possibile dedurre che un'aula sia libera
dall'assenza di lezioni nel mock: non contiene tutte le prenotazioni dell'ateneo.

`complete` nella tabella `coverage` significa **completo rispetto ai manifesti e
alle risposte pubblicate consultate per il perimetro dichiarato**. Non significa
che l'università abbia già pubblicato ogni futura lezione, né che il calendario
non cambierà dopo la fotografia. Il secondo semestre e gli orari delle altre
lauree non sono coperti.

## Scelte di importazione e verifiche

- Chiavi U-GOV delle schede usate per identificare gli insegnamenti; nessuna fusione
  per solo titolo. Nomi e codici originali sono conservati.
- Docenti identificati dai profili ufficiali e dai codici dell'agenda; una
  corrispondenza di nome viene utilizzata solo se univoca fra i profili acquisiti.
- Le fonti grezze sono conservate integralmente con hash. I testi di presentazione
  sono ripuliti dal markup prima dell'importazione nei campi testuali.
- Foreign key SQLite, controllo integrità, intervalli temporali e deduplicazione
  degli eventi verificati. La gestione del fuso include il cambio dell'ora legale.
- I test offline controllano anche un evento reale, le coorti, i laboratori
  condivisi, le chiusure, i dati mancanti e i checksum delle fonti.

Le date di acquisizione sono documentate per singola fonte e come intervallo in
`snapshot`: non si presenta la raccolta, durata diversi minuti, come un unico
istante atomico. La ricostruzione del database non effettua richieste di rete.

Verifica del rilascio: **12 test superati**; una seconda ricostruzione con accesso
HTTP disabilitato ha prodotto un database **identico byte per byte** al rilascio.

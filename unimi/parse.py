"""Lettura delle pagine pubbliche; identità basate sui codici, mai sui nomi."""
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

BASE = "https://www.unimi.it"


def text(node):
    return node.get_text(" ", strip=True).replace("\ufeff", "") if node else ""


def url(value, base=BASE):
    p = urlsplit(urljoin(base, value))
    return urlunsplit((p.scheme, p.netloc, p.path.replace("/index.php/", "/"), p.query, ""))


def links(doc, fragment):
    return {url(a["href"]): text(a) for a in doc.select("a[href]") if fragment in a["href"]}


def path(doc):
    tag = doc.select_one("[data-drupal-selector=drupal-settings-json]")
    return json.loads(tag.string).get("path", {}).get("currentPath", "") if tag and tag.string else ""


def identity(doc, fallback):
    current = path(doc)
    return BASE + "/it/" + current if current.startswith("ugov/") else fallback


def number(value):
    match = re.search(r"-?\d+(?:[.,]\d+)?", value or "")
    result = float(match[0].replace(",", ".")) if match else None
    return result if result is not None and result >= 0 else None


def field(doc, selector):
    node = doc.select_one(selector)
    return text(node.select_one(".field--item") or node) if node else None


def properties(doc):
    """Campi Drupal atomici; evita di duplicarli nei contenitori di impaginazione."""
    out = {}
    for n in doc.select('[class*="field--name-"], [class*="views-field-"]'):
        if n.select_one('[class*="field--name-"], [class*="views-field-"]'):
            continue
        key = next((c[12:] for c in n.get("class", []) if c.startswith(("field--name-", "views-field-"))), None)
        if key:
            values = [text(x) for x in n.select(":scope > .field--item")]
            value = values if len(values) > 1 else values[0] if values else text(n)
            if value:
                out.setdefault(key, [])
                if value not in out[key]:
                    out[key].append(value)
    return out


def academic_year(value):
    match = re.search(r"(?:aa-|/af|/cdsi|/insegnamenti-dei-corsi-di-laurea/)(20\d\d)", value)
    if match:
        return int(match[1]) if "aa-" in match[0] else int(match[1]) - 1
    match = re.search(r"(20\d\d)\s*[/–-]\s*(?:20)?\d\d", value)
    return int(match[1]) if match else None


def cards(doc, base):
    result = []
    for card in doc.select(".card-content"):
        a = card.select_one(".bp-title a[href]")
        if not a:
            continue
        link = url(a["href"], base)
        if "/corsi/" not in link:
            continue
        label = text(card.select_one(".anno-accademico"))
        result.append({"url": link, "name": text(a), "academic_year": academic_year(label),
                       "summary": text(card), "level_label": text(card.select_one(".card_left"))})
    return result


def pager(doc, base):
    return {url(a["href"], base) for a in doc.select(".pager a[href], .pager-nav a[href], .pagination a[href]")}


def course_code(doc):
    match = re.search(r"/af(20\d\d)0*([a-z][a-z0-9]*-[a-z0-9-]+)$", path(doc), re.I)
    return (match[2].upper(), int(match[1]) - 1) if match else (None, None)


def choice_rules(container):
    blocks = container.select(".ugov-of-pd-rules")
    if blocks:
        fragments = []
        for block in blocks:
            for node in block.children:
                if not getattr(node, "name", None):
                    if str(node).strip():
                        fragments.append(str(node).strip())
                elif node.name != "table" and not node.select_one("table"):
                    fragments.append(text(node))
        return "\n".join(fragments) or None
    result = []
    for heading in container.select(".titoletto"):
        if "regole di composizione" in text(heading).lower():
            result.append(text(heading))
            result.extend(text(node) for node in heading.next_siblings if getattr(node, "name", None))
    return "\n".join(result) or None


def plan_links(doc):
    return [a for a in doc.select('td.cdl-title a[href],td[data-title="Attività formative"] a[href]')
            if not a.find_parent(lambda p: p.get("id", "").startswith("curr-") and p.get("id", "").endswith("-p"))]


def plan_cells(doc):
    return [td for td in doc.select('td.cdl-title,td[data-title="Attività formative"]')
            if text(td) and not td.find_parent(lambda p: p.get("id", "").startswith("curr-") and p.get("id", "").endswith("-p"))]


def plan_rows(doc):
    result = []
    for container in doc.select("[id^=curr-]"):
        match = re.fullmatch(r"curr-(20\d\d)0*([a-z0-9]+of\d+)-(.+)", container["id"], re.I)
        if (not match and container["id"] != "curr--") or container["id"].endswith("-p"):
            continue
        panes = container.select("[id^=ugov-of-pd-year-af-]")
        tables_without_year = not panes
        if tables_without_year:
            panes = [container]
        rows = []
        for pane in panes:
            label = text(container.find("a", href="#" + pane["id"]))
            year = re.search(r"Anno:\s*(\d+)", label)
            activation_label = text(pane)[:200]
            future = re.search(r"attivat[oa].*?(20\d\d)", activation_label, re.I)
            activation_status = "future" if future else "inactive" if "non più attiva" in activation_label else "active"
            tables = pane.select("table")
            for table_index, table in enumerate(tables):
                if table.find_parent(lambda tag: tag.get("id", "").startswith("curr-") and tag.get("id", "").endswith("-p")):
                    continue
                period = text(table.find_previous_sibling(class_="titoletto")) or None
                group = table.find_parent(class_="ugov-of-pd-rules")
                choice_group = text(group.select_one(".yyy")) if group else None
                if group and not choice_group:
                    choice_group = text(table.parent.find_previous_sibling()) or None
                requirement = text(table.find_previous_sibling(class_="special-i")) or choice_group
                last_row = None
                for row_index, tr in enumerate(table.select("tbody > tr")):
                    if "rowsubtitle" in tr.get("class", []):
                        requirement = text(tr)
                        continue
                    title = tr.select_one('td.cdl-title,td[data-title="Attività formative"]')
                    a = title.select_one("a[href]") if title else None
                    if title and text(title):
                        teachers = {**links(tr, "/ugov/person/"), **links(tr, "/ugov/rubrica/")}
                        last_row = {"url": url(a["href"]) if a else None, "name": text(a or title),
                                     "source_key": f"{pane.get('id', container['id'])}:{table_index}:{row_index}",
                                     "teachers": [{"url": link, "name": name} for link, name in teachers.items()],
                                     "study_year": int(year[1]) if year else None,
                                     "requirement": requirement, "choice_group": choice_group,
                                     "period_label": period,
                                     "fields": {td.get("data-title"): text(td) for td in tr.select("td[data-title]")},
                                     "activation_label": activation_label, "activation_status": activation_status,
                                     "activation_year": int(future[1]) if future else None}
                        rows.append(last_row)
                    else:
                        cells = [text(td) for td in tr.select(":scope > td")]
                        if last_row is not None and cells and cells[0].startswith("-"):
                            last_row.setdefault("components", []).append(cells)
        version = match[2].upper() if match else None
        if match:
            suffix = re.search(r"OF\d+$", version)[0]
            prefix = match[3].split("-")[0].upper()
            if version[:-len(suffix)].lstrip("0") == prefix.lstrip("0"):
                version = prefix + suffix
        result.append({"key": container["id"], "year": int(match[1]) - 1 if match else academic_year(path(doc)),
                       "offering_code": version, "curriculum_code": match[3] if match else None,
                       "name": text(doc.find("a", href="#" + container["id"])) or (match[3] if match else "Piano di studio"),
                       "rules": choice_rules(container),
                       "rows": rows})
    return result


def editions(doc):
    result = []
    for i, header in enumerate(doc.select("h3.js-views-accordion-group-header")):
        block = header.parent
        teachers = []
        for a in block.select(".field--name-uof-person a[href], .af-edition-nomination a[href]"):
            teachers.append({"url": url(a["href"]), "name": text(a),
                             "role": "responsible" if a.find_parent(class_="field--name-uof-person") else "lecturer"})
        result.append({"index": i, "name": text(header), "teachers": teachers,
                       "status": "inactive" if "edizione non attiva" in text(block).lower() else "active",
                       "fields": properties(block), "period": field(block, ".field--name-ugov-erogazione")})
    return result


def department_teaching(doc):
    records = []
    for panel in doc.select(".accordion-insegnamento__content"):
        a = panel.select_one("a[href*='/ugov/of/af']")
        if not a:
            continue
        header = doc.find(id=panel.get("aria-labelledby"))
        records.append({"url": url(a["href"]), "name": text(header) or text(a),
                        "teachers": links(panel, "/ugov/rubrica/"),
                        "offerings": links(panel, "/ugov/of/cdsi"), "summary": text(panel)})
    return records

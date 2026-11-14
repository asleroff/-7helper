import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
PP_RE = re.compile(r"(?:пп|pp)[_\s-]*(\d+)", re.IGNORECASE)

HEADER_NAME = "фио курьера"
HEADER_PHONE = "телефон"
HEADER_POINTS = "получатели"
HEADER_DATE = "дата доставки мл"


class CourierFileError(ValueError):
    pass


def _column_index(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    index = 0
    for ch in letters:
        index = index * 26 + ord(ch.upper()) - 64
    return index


def _row_index(ref: str) -> int:
    digits = "".join(ch for ch in ref if ch.isdigit())
    return int(digits or 0)


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("m:si", NS):
        values.append("".join(node.text or "" for node in item.iter(MAIN + "t")))
    return values


def _cell_text(cell, shared: list[str]) -> str:
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(MAIN + "t")).strip()
    value = cell.find("m:v", NS)
    if value is None or value.text is None:
        return ""
    if kind == "s":
        return shared[int(value.text)].strip()
    return value.text.strip()


def _sheet_rows(payload: bytes) -> list[dict[int, str]]:
    with zipfile.ZipFile(BytesIO(payload)) as book:
        shared = _shared_strings(book)
        sheet_name = next(
            (name for name in book.namelist() if name.startswith("xl/worksheets/sheet")),
            None,
        )
        if sheet_name is None:
            raise CourierFileError("В файле нет листа")
        sheet = ET.fromstring(book.read(sheet_name))
    rows: dict[int, dict[int, str]] = {}
    for cell in sheet.findall(".//m:c", NS):
        ref = cell.attrib.get("r", "")
        text = _cell_text(cell, shared)
        if not text:
            continue
        rows.setdefault(_row_index(ref), {})[_column_index(ref)] = text
    return [rows[index] for index in sorted(rows)]


def _find_column(header: dict[str, int], *parts: str) -> int | None:
    for title, column in header.items():
        if any(part in title for part in parts):
            return column
    return None


def parse_courier_file(payload: bytes) -> dict:
    try:
        rows = _sheet_rows(payload)
    except zipfile.BadZipFile as exc:
        raise CourierFileError("Файл не похож на xlsx") from exc
    if not rows:
        raise CourierFileError("Файл пустой")

    header_row = 0
    header: dict[str, int] = {}
    for index, row in enumerate(rows[:8]):
        found = {text.casefold(): column for column, text in row.items()}
        if _find_column(found, "фио") is not None and _find_column(found, "получател") is not None:
            header_row = index
            header = found
            break
    if not header:
        raise CourierFileError("В таблице нет колонок: ФИО Курьера, Получатели")

    name_col = _find_column(header, "фио")
    phone_col = _find_column(header, "телефон", "контакт")
    points_col = _find_column(header, "получател")
    date_col = _find_column(header, "дата")

    couriers: dict[str, dict] = {}
    dates: list[str] = []
    for row in rows[header_row + 1:]:
        name = row.get(name_col, "").strip()
        if not name:
            continue
        points = PP_RE.findall(row.get(points_col, ""))
        if not points:
            continue
        phone = row.get(phone_col, "").strip() if phone_col is not None else ""
        if date_col is not None and row.get(date_col):
            dates.append(row[date_col])
        slot = couriers.get(name)
        if slot is None:
            slot = {"name": name, "phone": phone, "points": []}
            couriers[name] = slot
        elif phone and not slot["phone"]:
            slot["phone"] = phone
        for point in points:
            if point not in slot["points"]:
                slot["points"].append(point)

    if not couriers:
        raise CourierFileError("В файле нет пунктов вида ПП_1125")

    return {"route_date": latest_route_date(dates), "couriers": list(couriers.values())}


def _parse_route_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%d.%m.%y %H:%M:%S",
        "%d.%m.%y %H:%M",
        "%d.%m.%y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def latest_route_date(values: list[str]) -> str:
    """Из нескольких дат файлов оставляет самую позднюю, без времени."""
    best: datetime | None = None
    fallback = ""
    for value in values:
        text = (value or "").strip()
        if not text:
            continue
        fallback = text
        parsed = _parse_route_datetime(text)
        if parsed is not None and (best is None or parsed > best):
            best = parsed
    if best is None:
        return fallback
    return best.strftime("%d.%m.%Y")


_REPLACEMENT_HEAD = re.compile(
    r"^замена\b(?:\s+(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?))?",
    re.IGNORECASE,
)
_INSTEAD = re.compile(r"^вместо\b\s*(.*)$", re.IGNORECASE)
_PP_LINE = re.compile(r"^(?:пп|pp)\s*:\s*(.+)$", re.IGNORECASE)


def phone_key(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 10:
        return ""
    return digits[-10:]


def person_names(value: str) -> tuple[str, str]:
    text = (value or "").casefold().replace("ё", "е")
    text = re.sub(r"[^a-zа-я\s-]", " ", text)
    parts = [part for part in re.split(r"[\s-]+", text) if part]
    surname = parts[0] if parts else ""
    first = parts[1] if len(parts) > 1 else ""
    return surname, first


def same_courier(name_a: str, phone_a: str, name_b: str, phone_b: str) -> bool:
    left_phone = phone_key(phone_a)
    right_phone = phone_key(phone_b)
    if left_phone and right_phone and left_phone == right_phone:
        return True
    surname_a, first_a = person_names(name_a)
    surname_b, first_b = person_names(name_b)
    if not surname_a or surname_a != surname_b:
        return False
    if not first_a or not first_b:
        return True
    return first_a == first_b or first_a.startswith(first_b) or first_b.startswith(first_a)


def _phone_line(line: str) -> str:
    compact = re.sub(r"[\s\-()]", "", line.strip())
    if not re.fullmatch(r"\+?\d{10,12}", compact):
        return ""
    return compact.lstrip("+")


def _name_and_phone(lines: list[str]) -> tuple[str, str]:
    phone = ""
    names = []
    for line in lines:
        found = _phone_line(line)
        if found:
            phone = found
            continue
        if line.strip():
            names.append(line.strip())
    return " ".join(names).strip(), phone


def _parse_replacement_block(date: str, source: list[str]) -> dict | None:
    warehouse = ""
    body = []
    for line in source:
        if line.casefold().startswith("склад"):
            warehouse = line
            continue
        body.append(line)
    instead_at = None
    old_inline = ""
    for index, line in enumerate(body):
        match = _INSTEAD.match(line)
        if match:
            instead_at = index
            old_inline = match.group(1).strip()
            break
    if instead_at is None:
        return None
    new_name, new_phone = _name_and_phone(body[:instead_at])
    points: list[str] = []
    old_lines = [old_inline] if old_inline else []
    for line in body[instead_at + 1:]:
        point_line = _PP_LINE.match(line)
        if point_line:
            points.extend(re.findall(r"\d+", point_line.group(1)))
            continue
        old_lines.append(line)
    old_name, old_phone = _name_and_phone(old_lines)
    if not new_name or not old_name:
        return None
    unique_points = []
    for point in points:
        if point not in unique_points:
            unique_points.append(point)
    return {
        "date": date,
        "warehouse": warehouse,
        "new_name": new_name,
        "new_phone": new_phone,
        "old_name": old_name,
        "old_phone": old_phone,
        "points": unique_points,
    }


def parse_replacements(text: str) -> list[dict]:
    """Сообщения «Замена»: новый водитель, затем «вместо» и старый, ПП по желанию."""
    blocks: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        head = _REPLACEMENT_HEAD.match(line)
        if head:
            if current:
                blocks.append(current)
            current = {"date": head.group(1) or "", "lines": []}
            continue
        if current is not None and line:
            current["lines"].append(line)
    if current:
        blocks.append(current)
    parsed = []
    for block in blocks:
        item = _parse_replacement_block(block["date"], block["lines"])
        if item:
            parsed.append(item)
    return parsed


def collapse_replacements(items: list[dict]) -> list[dict]:
    """Если одну замену прислали и без ПП, и со списком ПП — берём только список."""
    groups: list[dict] = []
    index: dict[tuple[str, str], int] = {}
    for item in items:
        key = (person_names(item["old_name"]), person_names(item["new_name"]))
        if key not in index:
            index[key] = len(groups)
            groups.append({
                **item,
                "points": list(item.get("points") or []),
                "limited": bool(item.get("points")),
            })
            continue
        group = groups[index[key]]
        if not group["new_phone"] and item.get("new_phone"):
            group["new_phone"] = item["new_phone"]
        if not group["old_phone"] and item.get("old_phone"):
            group["old_phone"] = item["old_phone"]
        if item.get("points"):
            if not group["limited"]:
                group["points"] = []
                group["limited"] = True
            for point in item["points"]:
                if point not in group["points"]:
                    group["points"].append(point)
    for group in groups:
        if not group["limited"]:
            group["points"] = None
        group.pop("limited", None)
    return groups

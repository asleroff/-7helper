import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
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

    route_date = Counter(dates).most_common(1)[0][0] if dates else ""
    return {"route_date": route_date, "couriers": list(couriers.values())}

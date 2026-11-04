import re
from datetime import datetime
from typing import Optional

import aiosqlite

DB_PATH = "addresses.db"


def normalize_text(value: str) -> str:
    text = value.casefold().replace("ё", "е")
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def extract_ozon_id(value: str) -> Optional[str]:
    match = re.search(
        r"(?:https?://)?(?:www\.)?ozon\.ru/(?:[\w.-]+/)*point/(\d+)",
        value,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def extract_pp(value: str) -> Optional[str]:
    cleaned = value.strip().strip(".,;")
    match = re.fullmatch(r"(?:пп|pp)[_\-\s]*(\d+)", cleaned, re.IGNORECASE)
    return match.group(1) if match else None


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS places (
                pp_number TEXT PRIMARY KEY,
                ozon_id TEXT UNIQUE,
                address TEXT NOT NULL,
                address_norm TEXT NOT NULL,
                created_at TEXT
            )
        """)
        async with db.execute("PRAGMA table_info(places)") as cursor:
            columns = await cursor.fetchall()
        ozon_column = next(column for column in columns if column[1] == "ozon_id")
        if ozon_column[3]:
            await db.execute("ALTER TABLE places RENAME TO places_old")
            await db.execute("""
                CREATE TABLE places (
                    pp_number TEXT PRIMARY KEY,
                    ozon_id TEXT UNIQUE,
                    address TEXT NOT NULL,
                    address_norm TEXT NOT NULL,
                    created_at TEXT
                )
            """)
            await db.execute("""
                INSERT INTO places (pp_number, ozon_id, address, address_norm, created_at)
                SELECT pp_number, ozon_id, address, address_norm, created_at FROM places_old
            """)
            await db.execute("DROP TABLE places_old")
        await db.commit()


async def _get_by(column: str, value: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT pp_number, ozon_id, address FROM places WHERE {column} = ?",
            (value,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_by_pp(pp_number: str) -> Optional[dict]:
    return await _get_by("pp_number", pp_number)


async def get_by_ozon(ozon_id: str) -> Optional[dict]:
    return await _get_by("ozon_id", ozon_id)


async def get_place_row(rowid: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT rowid, pp_number, ozon_id, address FROM places WHERE rowid = ?",
            (rowid,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def find_places(query: str) -> list[dict]:
    raw = query.strip()
    ozon_id = extract_ozon_id(raw)
    pp_number = extract_pp(raw)
    compact = re.sub(r"\s+", "", raw)
    if compact.isdigit():
        ozon_id = ozon_id or compact
        pp_number = pp_number or compact
    clauses = []
    params = []
    if pp_number:
        clauses.append("pp_number = ?")
        params.append(pp_number)
    if ozon_id:
        clauses.append("ozon_id = ?")
        params.append(ozon_id)
    if not clauses:
        return []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT rowid, pp_number, ozon_id, address FROM places WHERE {' OR '.join(clauses)}",
            params,
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def update_place_field(rowid: int, field: str, value: str) -> None:
    if field not in {"pp_number", "ozon_id", "address"}:
        raise ValueError("field")
    current = await get_place_row(rowid)
    if current is None:
        raise LookupError("missing")
    if field == "pp_number":
        owner = await get_by_pp(value)
        if owner:
            owner_row = await find_places(value)
            if any(row["rowid"] != rowid and row["pp_number"] == value for row in owner_row):
                raise ValueError(f"ПП_{value}")
        assignments = "pp_number = ?"
        params = [value]
    elif field == "ozon_id":
        owner = await get_by_ozon(value)
        if owner:
            rows = await find_places(value)
            if any(row["rowid"] != rowid and row["ozon_id"] == value for row in rows):
                raise ValueError(f"ПП_{owner['pp_number'] or 'без номера'}")
        assignments = "ozon_id = ?"
        params = [value]
    else:
        assignments = "address = ?, address_norm = ?"
        params = [value.strip(), normalize_text(value)]
    params.append(rowid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE places SET {assignments} WHERE rowid = ?", params)
        await db.commit()


async def list_places() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT pp_number, ozon_id, address
               FROM places
               ORDER BY CASE WHEN pp_number IS NULL OR pp_number = '' THEN 1 ELSE 0 END,
                        CAST(pp_number AS INTEGER),
                        pp_number"""
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


def build_places_pdf(places: list[dict]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_font("Arial", fname=r"C:\Windows\Fonts\arial.ttf")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Arial", size=14)
    pdf.cell(0, 8, f"Адреса пунктов: {len(places)}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Arial", size=9)
    for place in places:
        pp = place.get("pp_number") or "—"
        ozon = place.get("ozon_id") or "—"
        address = (place.get("address") or "").replace("\n", " ")
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 5, f"ПП_{pp}    {ozon}    {address}")
    return bytes(pdf.output())


async def save_place(pp_number: str, ozon_id: Optional[str], address: str) -> str:
    if ozon_id:
        owner = await get_by_ozon(ozon_id)
        if owner and owner["pp_number"] != pp_number:
            raise ValueError(owner["pp_number"])

    existed = await get_by_pp(pp_number) is not None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO places
               (pp_number, ozon_id, address, address_norm, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (pp_number, ozon_id, address.strip(), normalize_text(address), datetime.now().isoformat()),
        )
        await db.commit()
    return "updated" if existed else "created"


async def search_address(query: str, limit: int = 10) -> list[dict]:
    words = [word for word in normalize_text(query).split() if word]
    if not words:
        return []
    clauses = " AND ".join("address_norm LIKE ?" for _ in words)
    params = [f"%{word}%" for word in words]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""SELECT pp_number, ozon_id, address
                FROM places
                WHERE {clauses}
                ORDER BY CAST(pp_number AS INTEGER), pp_number
                LIMIT ?""",
            (*params, limit),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def search_places(query: str) -> list[dict]:
    raw = query.strip()
    if not raw:
        return []

    ozon_id = extract_ozon_id(raw)
    if ozon_id:
        place = await get_by_ozon(ozon_id)
        return [_with_match(place, "номеру пункта")] if place else []

    pp_number = extract_pp(raw)
    if pp_number:
        place = await get_by_pp(pp_number)
        return [_with_match(place, "номеру ПП")] if place else []

    compact = re.sub(r"\s+", "", raw)
    if compact.isdigit():
        found = []
        by_pp = await get_by_pp(compact)
        by_ozon = await get_by_ozon(compact)
        if by_pp:
            found.append(_with_match(by_pp, "номеру ПП"))
        if by_ozon and (not by_pp or by_ozon["pp_number"] != by_pp["pp_number"]):
            found.append(_with_match(by_ozon, "номеру пункта"))
        return found

    places = await search_address(raw)
    return [_with_match(place, "адресу") for place in places]


def _with_match(place: dict, matched_by: str) -> dict:
    return {**place, "matched_by": matched_by}

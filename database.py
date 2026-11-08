import asyncio
import re

import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = "bot_database.db"
_courier_lock = asyncio.Lock()

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                is_admin INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS points (
                point_number TEXT PRIMARY KEY,
                chat_id INTEGER,
                title TEXT,
                address TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                point_number TEXT,
                report_type TEXT,
                user_id INTEGER,
                data TEXT,
                accepted INTEGER,
                issued INTEGER,
                created_at TEXT
            )
        """)
        await _ensure_column(db, "reports", "leftover", "INTEGER")
        await _backfill_leftover(db)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS courier_loads (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                route_date TEXT,
                file_name TEXT,
                loaded_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS courier_stops (
                courier_name TEXT,
                phone TEXT,
                pp_number TEXT,
                stop_order INTEGER,
                source_file TEXT
            )
        """)
        await _ensure_column(db, "courier_stops", "source_file", "TEXT")
        await db.commit()

async def _ensure_column(db, table: str, column: str, column_type: str):
    async with db.execute(f"PRAGMA table_info({table})") as cursor:
        columns = [row[1] for row in await cursor.fetchall()]
    if column not in columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

async def _backfill_leftover(db):
    async with db.execute(
        "SELECT id, data FROM reports WHERE leftover IS NULL AND data LIKE '%Остатк%'"
    ) as cursor:
        rows = await cursor.fetchall()
    for report_id, data in rows:
        match = re.search(r"Остатк\w*(?:\s+на складе)?\s*:?\s*(\d+)", data or "", re.I)
        if match:
            await db.execute(
                "UPDATE reports SET leftover = ? WHERE id = ?",
                (int(match.group(1)), report_id),
            )

async def add_user(user_id: int, username: str = None, full_name: str = None, is_admin: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (user_id, username, full_name, is_admin, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username,
                 full_name=excluded.full_name""",
            (user_id, username, full_name, int(is_admin), datetime.now().isoformat())
        )
        await db.commit()

async def is_admin(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return bool(row and row[0])

async def set_admin(user_id: int, value: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_admin = ? WHERE user_id = ?", (int(value), user_id))
        await db.commit()

async def add_point(point_number: str, chat_id: int, title: str = None, address: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO points (point_number, chat_id, title, address, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (point_number, chat_id, title or f"ПП_{point_number}", address, datetime.now().isoformat())
        )
        await db.commit()

async def get_point(point_number: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM points WHERE point_number = ?", (point_number,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def save_report(point_number: str, report_type: str, user_id: int, data: str,
                      accepted: int = None, issued: int = None, leftover: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO reports
               (point_number, report_type, user_id, data, accepted, issued, leftover, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (point_number, report_type, user_id, data, accepted, issued, leftover, datetime.now().isoformat())
        )
        await db.commit()

def _local_period_filter() -> str:
    return "datetime(replace(substr(created_at, 1, 19), 'T', ' ')) >= datetime('now', 'localtime', ?)"

async def get_stats(point_number: str, days: int = 7) -> Dict[str, Any]:
    period = f"-{int(days)} days"
    where = f"point_number = ? AND report_type = 'closing' AND {_local_period_filter()}"
    empty = {
        "count": 0,
        "total_accepted": 0,
        "total_issued": 0,
        "avg_accepted": 0,
        "avg_issued": 0,
        "leftover_avg": None,
        "leftover_last": None,
    }
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"""SELECT COUNT(*),
                       SUM(accepted),
                       SUM(issued),
                       AVG(accepted),
                       AVG(issued),
                       AVG(leftover)
                FROM reports
                WHERE {where}""",
            (point_number, period),
        ) as cursor:
            row = await cursor.fetchone()
        if not row or not row[0]:
            return empty
        async with db.execute(
            f"""SELECT leftover FROM reports
                WHERE {where} AND leftover IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 1""",
            (point_number, period),
        ) as cursor:
            last = await cursor.fetchone()
        return {
            "count": row[0],
            "total_accepted": row[1] or 0,
            "total_issued": row[2] or 0,
            "avg_accepted": round(row[3] or 0, 1),
            "avg_issued": round(row[4] or 0, 1),
            "leftover_avg": round(row[5], 1) if row[5] is not None else None,
            "leftover_last": last[0] if last else None,
        }


async def save_courier_load(route_date: str, file_name: str, couriers: list[dict]) -> dict:
    async with _courier_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT route_date, file_name, loaded_at FROM courier_loads WHERE id = 1"
            ) as cursor:
                existing = await cursor.fetchone()
            now = datetime.now().isoformat()
            fresh_day = not existing or (existing["loaded_at"] or "")[:10] != now[:10]
            if fresh_day:
                await db.execute("DELETE FROM courier_stops")
                await db.execute("DELETE FROM courier_loads")
                await db.execute(
                    "INSERT INTO courier_loads (id, route_date, file_name, loaded_at) VALUES (1, ?, ?, ?)",
                    (route_date, file_name, now),
                )
            else:
                await db.execute(
                    "DELETE FROM courier_stops WHERE source_file = ?",
                    (file_name,),
                )
                names = [part for part in (existing["file_name"] or "").split(", ") if part and part != file_name]
                names.append(file_name)
                dates = [part for part in (existing["route_date"] or "").split(", ") if part]
                if route_date and route_date not in dates:
                    dates.append(route_date)
                await db.execute(
                    "UPDATE courier_loads SET route_date = ?, file_name = ?, loaded_at = ? WHERE id = 1",
                    (", ".join(dates), ", ".join(names), now),
                )
            async with db.execute("SELECT COALESCE(MAX(stop_order), -1) FROM courier_stops") as cursor:
                order = (await cursor.fetchone())[0] + 1
            for courier in couriers:
                phone = courier.get("phone") or ""
                for point in courier["points"]:
                    await db.execute(
                        """INSERT INTO courier_stops
                           (courier_name, phone, pp_number, stop_order, source_file)
                           VALUES (?, ?, ?, ?, ?)""",
                        (courier["name"], phone, point, order, file_name),
                    )
                    order += 1
                if phone:
                    await db.execute(
                        """UPDATE courier_stops
                           SET phone = ?
                           WHERE courier_name = ? AND (phone IS NULL OR phone = '')""",
                        (phone, courier["name"]),
                    )
            async with db.execute(
                "SELECT COUNT(DISTINCT courier_name), COUNT(DISTINCT pp_number) FROM courier_stops"
            ) as cursor:
                total_couriers, total_points = await cursor.fetchone()
            await db.commit()
            return {
                "file_couriers": len(couriers),
                "file_points": sum(len(courier["points"]) for courier in couriers),
                "total_couriers": total_couriers,
                "total_points": total_points,
            }


async def courier_load() -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT route_date, file_name, loaded_at FROM courier_loads WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def couriers_for_point(pp_number: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT courier_name, MAX(phone) AS phone
               FROM courier_stops
               WHERE pp_number = ?
               GROUP BY courier_name
               ORDER BY courier_name""",
            (pp_number,),
        ) as cursor:
            people = [dict(row) for row in await cursor.fetchall()]
        result = []
        for person in people:
            async with db.execute(
                """SELECT pp_number FROM courier_stops
                   WHERE courier_name = ?
                   ORDER BY stop_order""",
                (person["courier_name"],),
            ) as cursor:
                points = []
                for row in await cursor.fetchall():
                    if row[0] not in points:
                        points.append(row[0])
            result.append({
                "name": person["courier_name"],
                "phone": person["phone"],
                "points": points,
            })
        return result

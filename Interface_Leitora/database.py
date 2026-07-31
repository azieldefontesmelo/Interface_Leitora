from __future__ import annotations

import csv
import math
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 10_000


def _application_dir() -> Path:
    """Return the source/bundle directory that contains the application assets."""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir)
    return Path(__file__).resolve().parent


DEFAULT_DB_PATH = (
    _application_dir() / "assets" / "database" / "measurements.sqlite3"
)

MEASUREMENT_COLUMNS = (
    "id",
    "measured_at",
    "test_mode",
    "reader_id",
    "dosimeter_id",
    "file_name",
    "file_path",
    "count_01s",
    "current_ma",
    "light_mv",
    "dose_msv",
    "ecc_applied",
    "rcf_applied",
    "fang_applied",
    "fenerg_applied",
    "baseline_applied",
    "status",
    "notes",
    "created_at",
    "updated_at",
)

VALID_TEST_MODES = frozenset({"MANUAL", "DOSIMETER_ID"})
VALID_MEASUREMENT_STATUSES = frozenset(
    {"EM_ANDAMENTO", "CONCLUIDO", "INTERROMPIDO", "ERRO"}
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dosimeters (
    dosimeter_id TEXT PRIMARY KEY
                 CHECK (
                     length(dosimeter_id) = 10
                     AND dosimeter_id NOT GLOB '*[^0-9]*'
                 ),
    ecc          REAL NOT NULL CHECK (ecc > 0),
    begin_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    CHECK (end_date >= begin_date)
);

CREATE TABLE IF NOT EXISTS readers (
    reader_id  TEXT PRIMARY KEY CHECK (
        length(trim(reader_id)) BETWEEN 1 AND 64
    ),
    rcf        REAL NOT NULL CHECK (rcf > 0),
    begin_date TEXT NOT NULL,
    end_date   TEXT,
    active     INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (end_date IS NULL OR end_date >= begin_date)
);

CREATE TABLE IF NOT EXISTS measurements (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    measured_at      TEXT NOT NULL,
    test_mode        TEXT NOT NULL CHECK (
        test_mode IN ('MANUAL', 'DOSIMETER_ID')
    ),
    reader_id        TEXT,
    dosimeter_id     TEXT,
    file_name        TEXT NOT NULL DEFAULT '',
    file_path        TEXT,
    count_01s        INTEGER NOT NULL DEFAULT 0 CHECK (count_01s >= 0),
    current_ma       REAL NOT NULL DEFAULT 0 CHECK (current_ma >= 0),
    light_mv         REAL NOT NULL DEFAULT 0 CHECK (light_mv >= 0),
    dose_msv         REAL NOT NULL DEFAULT 0 CHECK (dose_msv >= 0),
    ecc_applied      REAL NOT NULL CHECK (ecc_applied > 0),
    rcf_applied      REAL NOT NULL CHECK (rcf_applied > 0),
    fang_applied     REAL NOT NULL CHECK (fang_applied > 0),
    fenerg_applied   REAL NOT NULL CHECK (fenerg_applied > 0),
    baseline_applied REAL NOT NULL CHECK (baseline_applied >= 0),
    status           TEXT NOT NULL DEFAULT 'EM_ANDAMENTO' CHECK (
        status IN ('EM_ANDAMENTO', 'CONCLUIDO', 'INTERROMPIDO', 'ERRO')
    ),
    notes            TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    CHECK (
        test_mode != 'DOSIMETER_ID'
        OR (reader_id IS NOT NULL AND dosimeter_id IS NOT NULL)
    ),
    FOREIGN KEY (reader_id)
        REFERENCES readers(reader_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (dosimeter_id)
        REFERENCES dosimeters(dosimeter_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_measurements_measured_at
    ON measurements(measured_at);

CREATE INDEX IF NOT EXISTS idx_measurements_dosimeter_date
    ON measurements(dosimeter_id, measured_at);

CREATE INDEX IF NOT EXISTS idx_measurements_reader_date
    ON measurements(reader_id, measured_at);

CREATE INDEX IF NOT EXISTS idx_measurements_mode_date
    ON measurements(test_mode, measured_at);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def normalize_datetime(value: datetime | str | None) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("data/hora não pode ficar vazia")
        try:
            parsed = datetime.fromisoformat(clean_value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("data/hora inválida") from error
    else:
        raise TypeError("data/hora deve ser datetime, texto ISO ou None")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def normalize_date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("data não pode ficar vazia")
        try:
            if "/" in clean_value:
                parsed = datetime.strptime(clean_value, "%d/%m/%Y").date()
            else:
                parsed = date.fromisoformat(clean_value)
        except ValueError as error:
            raise ValueError("data inválida") from error
    else:
        raise TypeError("data deve ser date, datetime ou texto")
    return parsed.isoformat()


def normalize_dosimeter_id(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("dosimeter_id deve ser texto")
    clean_id = value.strip()
    if (
        len(clean_id) != 10
        or not clean_id.isascii()
        or not clean_id.isdigit()
    ):
        raise ValueError("O ID deve conter exatamente 10 dígitos")
    return clean_id


def normalize_reader_id(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("reader_id deve ser texto")
    clean_id = value.strip()
    if not clean_id:
        raise ValueError("reader_id não pode ficar vazio")
    if len(clean_id) > 64:
        raise ValueError("reader_id deve ter no máximo 64 caracteres")
    if any(ord(character) < 32 for character in clean_id):
        raise ValueError("reader_id contém caractere de controle")
    return clean_id


def _positive_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} deve ser numérico")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} deve ser numérico") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field_name} deve ser maior que zero")
    return number


def _non_negative_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} deve ser numérico")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} deve ser numérico") from error
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field_name} não pode ser negativo")
    return number


def _count_value(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError("count_01s deve ser um número inteiro")
    if isinstance(value, float) and not value.is_integer():
        raise TypeError("count_01s deve ser um número inteiro")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise TypeError("count_01s deve ser um número inteiro") from error
    if parsed < 0:
        raise ValueError("count_01s não pode ser negativo")
    return parsed


def _active_value(value: bool | int) -> int:
    if isinstance(value, bool):
        return int(value)
    if value in (0, 1):
        return int(value)
    raise ValueError("active deve ser verdadeiro ou falso")


def _filter_datetime(
    value: date | datetime | str,
    *,
    end_of_day: bool,
) -> str:
    if isinstance(value, datetime):
        return normalize_datetime(value)
    if isinstance(value, date):
        day = value
    elif isinstance(value, str):
        clean_value = value.strip()
        if "T" in clean_value or " " in clean_value:
            return normalize_datetime(clean_value)
        day = date.fromisoformat(normalize_date(clean_value))
    else:
        raise TypeError("filtro de data inválido")

    boundary = time.max if end_of_day else time.min
    return normalize_datetime(datetime.combine(day, boundary, timezone.utc))


class Database:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        *,
        busy_timeout_ms: int = BUSY_TIMEOUT_MS,
    ) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.busy_timeout_ms = int(busy_timeout_ms)
        if self.busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms deve ser positivo")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.create_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.db_path,
            timeout=self.busy_timeout_ms / 1000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_schema(self) -> None:
        with self.connect() as connection:
            current_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    "O banco foi criado por uma versão mais nova da aplicação"
                )
            connection.executescript(SCHEMA)
            if current_version < SCHEMA_VERSION:
                now = utc_now()
                connection.execute(
                    """
                    INSERT OR IGNORE INTO schema_versions (version, applied_at)
                    VALUES (?, ?)
                    """,
                    (SCHEMA_VERSION, now),
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def register_dosimeter(
        self,
        dosimeter_id: str,
        *,
        ecc: float = 1.0,
        begin_date: date | datetime | str,
        end_date: date | datetime | str,
        active: bool = True,
    ) -> None:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        clean_ecc = _positive_number(ecc, "ECC")
        begin = normalize_date(begin_date)
        end = normalize_date(end_date)
        if end < begin:
            raise ValueError("A data final não pode ser anterior à data inicial")
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO dosimeters (
                    dosimeter_id, ecc, begin_date, end_date, active,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (clean_id, clean_ecc, begin, end, _active_value(active), now, now),
            )

    def get_dosimeter(self, dosimeter_id: str) -> dict[str, Any] | None:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM dosimeters WHERE dosimeter_id = ?",
                (clean_id,),
            ).fetchone()
        return dict(row) if row else None

    def search_dosimeters(
        self,
        *,
        text: str | None = None,
        active: bool | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if text:
            clauses.append("dosimeter_id LIKE ?")
            parameters.append(f"%{text.strip()}%")
        if active is not None:
            clauses.append("active = ?")
            parameters.append(_active_value(active))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM dosimeters
                {where}
                ORDER BY dosimeter_id
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def update_dosimeter(
        self,
        dosimeter_id: str,
        *,
        ecc: float,
        begin_date: date | datetime | str,
        end_date: date | datetime | str,
        active: bool,
    ) -> bool:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        clean_ecc = _positive_number(ecc, "ECC")
        begin = normalize_date(begin_date)
        end = normalize_date(end_date)
        if end < begin:
            raise ValueError("A data final não pode ser anterior à data inicial")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE dosimeters
                SET ecc = ?, begin_date = ?, end_date = ?, active = ?,
                    updated_at = ?
                WHERE dosimeter_id = ?
                """,
                (
                    clean_ecc,
                    begin,
                    end,
                    _active_value(active),
                    utc_now(),
                    clean_id,
                ),
            )
            return cursor.rowcount == 1

    def set_dosimeter_active(
        self,
        dosimeter_id: str,
        active: bool,
    ) -> bool:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE dosimeters
                SET active = ?, updated_at = ?
                WHERE dosimeter_id = ?
                """,
                (_active_value(active), utc_now(), clean_id),
            )
            return cursor.rowcount == 1

    def delete_dosimeter(self, dosimeter_id: str) -> bool:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM dosimeters WHERE dosimeter_id = ?",
                (clean_id,),
            )
            return cursor.rowcount == 1

    def register_reader(
        self,
        reader_id: str,
        *,
        rcf: float = 1.0,
        begin_date: date | datetime | str,
        end_date: date | datetime | str | None = None,
        active: bool = True,
    ) -> None:
        clean_id = normalize_reader_id(reader_id)
        clean_rcf = _positive_number(rcf, "RCF")
        begin = normalize_date(begin_date)
        end = normalize_date(end_date) if end_date not in (None, "") else None
        if end is not None and end < begin:
            raise ValueError("A data final não pode ser anterior à data inicial")
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO readers (
                    reader_id, rcf, begin_date, end_date, active,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (clean_id, clean_rcf, begin, end, _active_value(active), now, now),
            )

    def get_reader(self, reader_id: str) -> dict[str, Any] | None:
        clean_id = normalize_reader_id(reader_id)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM readers WHERE reader_id = ?",
                (clean_id,),
            ).fetchone()
        return dict(row) if row else None

    def search_readers(
        self,
        *,
        text: str | None = None,
        active: bool | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if text:
            clauses.append("reader_id LIKE ?")
            parameters.append(f"%{text.strip()}%")
        if active is not None:
            clauses.append("active = ?")
            parameters.append(_active_value(active))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM readers
                {where}
                ORDER BY reader_id
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def update_reader(
        self,
        reader_id: str,
        *,
        rcf: float,
        begin_date: date | datetime | str,
        end_date: date | datetime | str | None,
        active: bool,
    ) -> bool:
        clean_id = normalize_reader_id(reader_id)
        clean_rcf = _positive_number(rcf, "RCF")
        begin = normalize_date(begin_date)
        end = normalize_date(end_date) if end_date not in (None, "") else None
        if end is not None and end < begin:
            raise ValueError("A data final não pode ser anterior à data inicial")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE readers
                SET rcf = ?, begin_date = ?, end_date = ?, active = ?,
                    updated_at = ?
                WHERE reader_id = ?
                """,
                (
                    clean_rcf,
                    begin,
                    end,
                    _active_value(active),
                    utc_now(),
                    clean_id,
                ),
            )
            return cursor.rowcount == 1

    def set_reader_active(self, reader_id: str, active: bool) -> bool:
        clean_id = normalize_reader_id(reader_id)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE readers
                SET active = ?, updated_at = ?
                WHERE reader_id = ?
                """,
                (_active_value(active), utc_now(), clean_id),
            )
            return cursor.rowcount == 1

    def delete_reader(self, reader_id: str) -> bool:
        clean_id = normalize_reader_id(reader_id)
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM readers WHERE reader_id = ?",
                (clean_id,),
            )
            return cursor.rowcount == 1

    def get_valid_dosimeter_for_test(
        self,
        dosimeter_id: str,
        *,
        at_date: date | datetime | str | None = None,
    ) -> dict[str, Any]:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        record = self.get_dosimeter(clean_id)
        if record is None:
            raise ValueError("Dosímetro não cadastrado")
        if not record["active"]:
            raise ValueError("Dosímetro inativo")
        check_date = (
            normalize_date(at_date)
            if at_date is not None
            else datetime.now(timezone.utc).date().isoformat()
        )
        if not record["begin_date"] <= check_date <= record["end_date"]:
            raise ValueError("Dosímetro fora do período de validade")
        _positive_number(record["ecc"], "ECC")
        return record

    def get_valid_reader_for_test(
        self,
        reader_id: str,
        *,
        at_date: date | datetime | str | None = None,
    ) -> dict[str, Any]:
        clean_id = normalize_reader_id(reader_id)
        record = self.get_reader(clean_id)
        if record is None:
            raise ValueError("Leitora não cadastrada")
        if not record["active"]:
            raise ValueError("Leitora inativa")
        check_date = (
            normalize_date(at_date)
            if at_date is not None
            else datetime.now(timezone.utc).date().isoformat()
        )
        if check_date < record["begin_date"] or (
            record["end_date"] is not None
            and check_date > record["end_date"]
        ):
            raise ValueError("Leitora fora do período de validade")
        _positive_number(record["rcf"], "RCF")
        return record

    def add_measurement(
        self,
        reader_id: str | None = None,
        dosimeter_id: str | None = None,
        *,
        test_mode: str | None = None,
        file_name: str = "",
        file_path: str | Path | None = None,
        count_01s: int = 0,
        current_ma: float = 0,
        light_mv: float = 0,
        dose_msv: float = 0,
        ecc_applied: float | None = None,
        rcf_applied: float | None = None,
        fang_applied: float = 1.0,
        fenerg_applied: float = 1.0,
        baseline_applied: float = 0.0,
        measured_at: datetime | str | None = None,
        status: str = "EM_ANDAMENTO",
        notes: str | None = None,
    ) -> int:
        mode = (
            test_mode.strip().upper()
            if test_mode is not None
            else ("DOSIMETER_ID" if dosimeter_id else "MANUAL")
        )
        if mode not in VALID_TEST_MODES:
            raise ValueError("test_mode deve ser MANUAL ou DOSIMETER_ID")
        clean_status = status.strip().upper()
        if clean_status not in VALID_MEASUREMENT_STATUSES:
            raise ValueError("status de medição inválido")

        measurement_time = normalize_datetime(measured_at)
        measurement_date = measurement_time[:10]
        clean_reader_id = (
            normalize_reader_id(reader_id) if reader_id is not None else None
        )
        clean_dosimeter_id = (
            normalize_dosimeter_id(dosimeter_id)
            if dosimeter_id is not None
            else None
        )

        reader: dict[str, Any] | None = None
        dosimeter: dict[str, Any] | None = None
        if mode == "DOSIMETER_ID":
            if clean_reader_id is None:
                raise ValueError("Selecione uma leitora antes de iniciar")
            if clean_dosimeter_id is None:
                raise ValueError("Dosímetro ID é obrigatório")
            reader = self.get_valid_reader_for_test(
                clean_reader_id,
                at_date=measurement_date,
            )
            dosimeter = self.get_valid_dosimeter_for_test(
                clean_dosimeter_id,
                at_date=measurement_date,
            )

        if ecc_applied is None:
            ecc_applied = dosimeter["ecc"] if dosimeter else 1.0
        if rcf_applied is None:
            rcf_applied = reader["rcf"] if reader else 1.0

        values = {
            "count_01s": _count_value(count_01s),
            "current_ma": _non_negative_number(current_ma, "Current"),
            "light_mv": _non_negative_number(light_mv, "Light"),
            "dose_msv": _non_negative_number(dose_msv, "Dose"),
            "ecc_applied": _positive_number(ecc_applied, "ECC"),
            "rcf_applied": _positive_number(rcf_applied, "RCF"),
            "fang_applied": _positive_number(fang_applied, "Fang"),
            "fenerg_applied": _positive_number(fenerg_applied, "Fenerg"),
            "baseline_applied": _non_negative_number(
                baseline_applied,
                "Base Line",
            ),
        }
        now = utc_now()
        clean_file_name = str(file_name).strip()
        clean_file_path = str(file_path) if file_path is not None else None
        clean_notes = str(notes).strip() if notes not in (None, "") else None
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO measurements (
                    measured_at, test_mode, reader_id, dosimeter_id,
                    file_name, file_path, count_01s, current_ma, light_mv,
                    dose_msv, ecc_applied, rcf_applied, fang_applied,
                    fenerg_applied, baseline_applied, status, notes,
                    created_at, updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    measurement_time,
                    mode,
                    clean_reader_id,
                    clean_dosimeter_id,
                    clean_file_name,
                    clean_file_path,
                    values["count_01s"],
                    values["current_ma"],
                    values["light_mv"],
                    values["dose_msv"],
                    values["ecc_applied"],
                    values["rcf_applied"],
                    values["fang_applied"],
                    values["fenerg_applied"],
                    values["baseline_applied"],
                    clean_status,
                    clean_notes,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def get_measurement(self, measurement_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM measurements WHERE id = ?",
                (int(measurement_id),),
            ).fetchone()
        return dict(row) if row else None

    def update_measurement(
        self,
        measurement_id: int,
        *,
        count_01s: int | None = None,
        current_ma: float | None = None,
        light_mv: float | None = None,
        dose_msv: float | None = None,
        file_path: str | Path | None = None,
        status: str | None = None,
        notes: str | None = None,
    ) -> bool:
        changes: dict[str, Any] = {}
        if count_01s is not None:
            changes["count_01s"] = _count_value(count_01s)
        if current_ma is not None:
            changes["current_ma"] = _non_negative_number(current_ma, "Current")
        if light_mv is not None:
            changes["light_mv"] = _non_negative_number(light_mv, "Light")
        if dose_msv is not None:
            changes["dose_msv"] = _non_negative_number(dose_msv, "Dose")
        if file_path is not None:
            changes["file_path"] = str(file_path)
        if status is not None:
            clean_status = status.strip().upper()
            if clean_status not in VALID_MEASUREMENT_STATUSES:
                raise ValueError("status de medição inválido")
            changes["status"] = clean_status
        if notes is not None:
            changes["notes"] = str(notes).strip() or None
        if not changes:
            return False

        changes["updated_at"] = utc_now()
        assignments = ", ".join(f"{field} = ?" for field in changes)
        parameters = [*changes.values(), int(measurement_id)]
        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE measurements SET {assignments} WHERE id = ?",
                parameters,
            )
            return cursor.rowcount == 1

    def search_measurements(
        self,
        *,
        reader_id: str | None = None,
        dosimeter_id: str | None = None,
        test_mode: str | None = None,
        date_from: date | datetime | str | None = None,
        date_to: date | datetime | str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not 1 <= int(limit) <= 10_000:
            raise ValueError("limit deve estar entre 1 e 10000")
        clauses: list[str] = []
        parameters: list[Any] = []
        if reader_id:
            clauses.append("reader_id = ?")
            parameters.append(normalize_reader_id(reader_id))
        if dosimeter_id:
            clauses.append("dosimeter_id = ?")
            parameters.append(normalize_dosimeter_id(dosimeter_id))
        if test_mode:
            mode = test_mode.strip().upper()
            if mode not in VALID_TEST_MODES:
                raise ValueError("modo de teste inválido")
            clauses.append("test_mode = ?")
            parameters.append(mode)
        if date_from is not None:
            clauses.append("measured_at >= ?")
            parameters.append(_filter_datetime(date_from, end_of_day=False))
        if date_to is not None:
            clauses.append("measured_at <= ?")
            parameters.append(_filter_datetime(date_to, end_of_day=True))
        if status:
            clean_status = status.strip().upper()
            if clean_status not in VALID_MEASUREMENT_STATUSES:
                raise ValueError("status de medição inválido")
            clauses.append("status = ?")
            parameters.append(clean_status)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(int(limit))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM measurements
                {where}
                ORDER BY measured_at DESC, id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def export_csv(
        self,
        destination: str | Path,
        rows: Sequence[Mapping[str, Any]] | None = None,
    ) -> Path:
        data = list(rows) if rows is not None else self.search_measurements()
        output = Path(destination).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=MEASUREMENT_COLUMNS,
                extrasaction="ignore",
            )
            writer.writeheader()
            for row in data:
                writer.writerow(dict(row))
        return output

    def backup(self, destination: str | Path) -> Path:
        output = Path(destination).expanduser().resolve()
        if output == self.db_path:
            raise ValueError("O backup deve ter destino diferente do banco")
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise FileExistsError(f"O arquivo de backup já existe: {output}")

        source = sqlite3.connect(self.db_path, timeout=self.busy_timeout_ms / 1000)
        target = sqlite3.connect(output)
        try:
            source.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            source.backup(target)
            target.commit()
            result = target.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise sqlite3.DatabaseError("backup SQLite inválido")
        except Exception:
            target.close()
            source.close()
            if output.exists():
                output.unlink()
            raise
        else:
            target.close()
            source.close()
        return output

from __future__ import annotations

import csv
import math
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


SCHEMA_VERSION = 5
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
    "reading_type",
    "reader_id",
    "dosimeter_id",
    "file_name",
    "file_path",
    "count_01s",
    "current_ma",
    "light_mv",
    "raw_signal",
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

PERSONAL_DOSE_COLUMNS = (
    "id",
    "measurement_id",
    "time_dos",
    "dosimeter_id",
    "dose_dos",
    "status_dos",
    "created_at",
)

BACKGROUND_COLUMNS = (
    "id",
    "measurement_id",
    "time_bg",
    "dosimeter_id",
    "dose_bg",
    "status_bg",
    "created_at",
)

PERSONAL_DOSE_STATUS = "Need to Erase"
BACKGROUND_STATUS = "Ready to Use"

VALID_TEST_MODES = frozenset({"MANUAL", "DOSIMETER_ID"})
VALID_READING_TYPES = frozenset({"PERSONAL_DOSE", "BACKGROUND"})
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
    end_date     TEXT,
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    CHECK (end_date IS NULL OR end_date >= begin_date)
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
    reading_type     TEXT CHECK (
        reading_type IS NULL
        OR reading_type IN ('PERSONAL_DOSE', 'BACKGROUND')
    ),
    reader_id        TEXT,
    dosimeter_id     TEXT,
    file_name        TEXT NOT NULL DEFAULT '',
    file_path        TEXT,
    count_01s        INTEGER NOT NULL DEFAULT 0 CHECK (count_01s >= 0),
    current_ma       REAL NOT NULL DEFAULT 0 CHECK (current_ma >= 0),
    light_mv         REAL NOT NULL DEFAULT 0 CHECK (light_mv >= 0),
    raw_signal       REAL NOT NULL DEFAULT 0 CHECK (raw_signal >= 0),
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

CREATE TABLE IF NOT EXISTS historico_dose (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    measurement_id INTEGER,
    time_dos     TEXT NOT NULL,
    dosimeter_id TEXT NOT NULL,
    dose_dos     REAL NOT NULL CHECK (dose_dos >= 0),
    status_dos   TEXT NOT NULL DEFAULT 'Need to Erase'
                 CHECK (status_dos = 'Need to Erase'),
    created_at   TEXT NOT NULL,
    FOREIGN KEY (dosimeter_id)
        REFERENCES dosimeters(dosimeter_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (measurement_id)
        REFERENCES measurements(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_historico_dose_dosimeter_time
    ON historico_dose(dosimeter_id, time_dos DESC);

CREATE INDEX IF NOT EXISTS idx_historico_dose_time
    ON historico_dose(time_dos DESC);

CREATE TABLE IF NOT EXISTS historico_branco (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    measurement_id INTEGER,
    time_bg      TEXT NOT NULL,
    dosimeter_id TEXT NOT NULL,
    dose_bg      REAL NOT NULL CHECK (dose_bg >= 0),
    status_bg    TEXT NOT NULL DEFAULT 'Ready to Use'
                 CHECK (status_bg = 'Ready to Use'),
    created_at   TEXT NOT NULL,
    FOREIGN KEY (dosimeter_id)
        REFERENCES dosimeters(dosimeter_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (measurement_id)
        REFERENCES measurements(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_historico_branco_dosimeter_time
    ON historico_branco(dosimeter_id, time_bg DESC);

CREATE INDEX IF NOT EXISTS idx_historico_branco_time
    ON historico_branco(time_bg DESC);
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
            self._migrate_optional_dosimeter_end_date(connection)
            self._migrate_measurement_histories(connection)
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

    @staticmethod
    def _migrate_optional_dosimeter_end_date(
        connection: sqlite3.Connection,
    ) -> None:
        """Allow dosimeter validity to remain open-ended in old databases."""
        columns = {
            row["name"]: row
            for row in connection.execute("PRAGMA table_info(dosimeters)")
        }
        end_date = columns.get("end_date")
        if end_date is None or not end_date["notnull"]:
            return

        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.execute(
                """
                CREATE TABLE dosimeters_v5 (
                    dosimeter_id TEXT PRIMARY KEY
                                 CHECK (
                                     length(dosimeter_id) = 10
                                     AND dosimeter_id NOT GLOB '*[^0-9]*'
                                 ),
                    ecc          REAL NOT NULL CHECK (ecc > 0),
                    begin_date   TEXT NOT NULL,
                    end_date     TEXT,
                    active       INTEGER NOT NULL DEFAULT 1
                                 CHECK (active IN (0, 1)),
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    CHECK (end_date IS NULL OR end_date >= begin_date)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO dosimeters_v5 (
                    dosimeter_id, ecc, begin_date, end_date, active,
                    created_at, updated_at
                )
                SELECT dosimeter_id, ecc, begin_date, end_date, active,
                       created_at, updated_at
                FROM dosimeters
                """
            )
            connection.execute("DROP TABLE dosimeters")
            connection.execute(
                "ALTER TABLE dosimeters_v5 RENAME TO dosimeters"
            )
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _migrate_measurement_histories(
        connection: sqlite3.Connection,
    ) -> None:
        """Migrate legacy channel histories to the single-dose v4 model."""

        def ensure_column(table: str, column: str, definition: str) -> None:
            columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )

        ensure_column(
            "measurements",
            "reading_type",
            "TEXT CHECK (reading_type IS NULL OR reading_type IN "
            "('PERSONAL_DOSE', 'BACKGROUND'))",
        )
        ensure_column(
            "measurements",
            "raw_signal",
            "REAL NOT NULL DEFAULT 0 CHECK (raw_signal >= 0)",
        )
        ensure_column(
            "historico_dose",
            "measurement_id",
            "INTEGER REFERENCES measurements(id) ON UPDATE CASCADE "
            "ON DELETE RESTRICT",
        )
        ensure_column(
            "historico_branco",
            "measurement_id",
            "INTEGER REFERENCES measurements(id) ON UPDATE CASCADE "
            "ON DELETE RESTRICT",
        )

        dose_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(historico_dose)")
        }
        if "dose_dos" not in dose_columns:
            connection.executescript(
                """
                CREATE TABLE historico_dose_v4 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    measurement_id INTEGER,
                    time_dos TEXT NOT NULL,
                    dosimeter_id TEXT NOT NULL,
                    dose_dos REAL NOT NULL CHECK (dose_dos >= 0),
                    status_dos TEXT NOT NULL DEFAULT 'Need to Erase'
                        CHECK (status_dos = 'Need to Erase'),
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (dosimeter_id) REFERENCES dosimeters(dosimeter_id)
                        ON UPDATE CASCADE ON DELETE RESTRICT,
                    FOREIGN KEY (measurement_id) REFERENCES measurements(id)
                        ON UPDATE CASCADE ON DELETE RESTRICT
                );
                INSERT INTO historico_dose_v4 (
                    id, measurement_id, time_dos, dosimeter_id, dose_dos,
                    status_dos, created_at
                )
                SELECT h.id, h.measurement_id, h.time_dos, h.dosimeter_id,
                       COALESCE(m.dose_msv, MAX(h.hp10_dos, h.hp007_dos)),
                       h.status_dos, h.created_at
                FROM historico_dose h
                LEFT JOIN measurements m ON m.id = h.measurement_id;
                DROP TABLE historico_dose;
                ALTER TABLE historico_dose_v4 RENAME TO historico_dose;
                """
            )

        background_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(historico_branco)")
        }
        if "dose_bg" not in background_columns:
            connection.executescript(
                """
                CREATE TABLE historico_branco_v4 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    measurement_id INTEGER,
                    time_bg TEXT NOT NULL,
                    dosimeter_id TEXT NOT NULL,
                    dose_bg REAL NOT NULL CHECK (dose_bg >= 0),
                    status_bg TEXT NOT NULL DEFAULT 'Ready to Use'
                        CHECK (status_bg = 'Ready to Use'),
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (dosimeter_id) REFERENCES dosimeters(dosimeter_id)
                        ON UPDATE CASCADE ON DELETE RESTRICT,
                    FOREIGN KEY (measurement_id) REFERENCES measurements(id)
                        ON UPDATE CASCADE ON DELETE RESTRICT
                );
                INSERT INTO historico_branco_v4 (
                    id, measurement_id, time_bg, dosimeter_id, dose_bg,
                    status_bg, created_at
                )
                SELECT h.id, h.measurement_id, h.time_bg, h.dosimeter_id,
                       COALESCE(m.dose_msv, MAX(h.hp10_bg, h.hp007_bg)),
                       h.status_bg, h.created_at
                FROM historico_branco h
                LEFT JOIN measurements m ON m.id = h.measurement_id;
                DROP TABLE historico_branco;
                ALTER TABLE historico_branco_v4 RENAME TO historico_branco;
                """
            )

        measurement_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(measurements)")
        }
        if "dose_channel" in measurement_columns:
            connection.execute(
                "ALTER TABLE measurements DROP COLUMN dose_channel"
            )

        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_historico_dose_dosimeter_time
                ON historico_dose(dosimeter_id, time_dos DESC);
            CREATE INDEX IF NOT EXISTS idx_historico_dose_time
                ON historico_dose(time_dos DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_historico_dose_measurement
                ON historico_dose(measurement_id)
                WHERE measurement_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_historico_branco_dosimeter_time
                ON historico_branco(dosimeter_id, time_bg DESC);
            CREATE INDEX IF NOT EXISTS idx_historico_branco_time
                ON historico_branco(time_bg DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_historico_branco_measurement
                ON historico_branco(measurement_id)
                WHERE measurement_id IS NOT NULL;
            """
        )
        connection.execute(
            """
            UPDATE measurements
            SET reading_type = COALESCE(reading_type, 'PERSONAL_DOSE')
            WHERE test_mode = 'DOSIMETER_ID'
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO historico_dose (
                measurement_id, time_dos, dosimeter_id, dose_dos,
                status_dos, created_at
            )
            SELECT id, measured_at, dosimeter_id, dose_msv,
                   'Need to Erase', created_at
            FROM measurements
            WHERE test_mode = 'DOSIMETER_ID'
              AND status = 'CONCLUIDO'
              AND reading_type = 'PERSONAL_DOSE'
              AND dosimeter_id IS NOT NULL
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO historico_branco (
                measurement_id, time_bg, dosimeter_id, dose_bg,
                status_bg, created_at
            )
            SELECT id, measured_at, dosimeter_id, dose_msv,
                   'Ready to Use', created_at
            FROM measurements
            WHERE test_mode = 'DOSIMETER_ID'
              AND status = 'CONCLUIDO'
              AND reading_type = 'BACKGROUND'
              AND dosimeter_id IS NOT NULL
            """
        )

    def register_dosimeter(
        self,
        dosimeter_id: str,
        *,
        ecc: float = 1.0,
        begin_date: date | datetime | str,
        end_date: date | datetime | str | None = None,
        active: bool = True,
    ) -> None:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        clean_ecc = _positive_number(ecc, "ECC")
        begin = normalize_date(begin_date)
        end = normalize_date(end_date) if end_date not in (None, "") else None
        if end is not None and end < begin:
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
        end_date: date | datetime | str | None = None,
        active: bool,
    ) -> bool:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        clean_ecc = _positive_number(ecc, "ECC")
        begin = normalize_date(begin_date)
        end = normalize_date(end_date) if end_date not in (None, "") else None
        if end is not None and end < begin:
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
        if record["begin_date"] > check_date or (
            record["end_date"] is not None
            and check_date > record["end_date"]
        ):
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
        reading_type: str | None = None,
        file_name: str = "",
        file_path: str | Path | None = None,
        count_01s: int = 0,
        current_ma: float = 0,
        light_mv: float = 0,
        raw_signal: float = 0,
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
        clean_reading_type: str | None = None
        if mode == "DOSIMETER_ID":
            clean_reading_type = str(
                reading_type or "PERSONAL_DOSE"
            ).strip().upper()
            if clean_reading_type not in VALID_READING_TYPES:
                raise ValueError(
                    "reading_type deve ser PERSONAL_DOSE ou BACKGROUND"
                )
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
            "raw_signal": _non_negative_number(raw_signal, "Sinal bruto"),
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
                    measured_at, test_mode, reading_type, reader_id,
                    dosimeter_id, file_name, file_path,
                    count_01s, current_ma, light_mv, raw_signal, dose_msv,
                    ecc_applied, rcf_applied, fang_applied,
                    fenerg_applied, baseline_applied, status, notes,
                    created_at, updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    measurement_time,
                    mode,
                    clean_reading_type,
                    clean_reader_id,
                    clean_dosimeter_id,
                    clean_file_name,
                    clean_file_path,
                    values["count_01s"],
                    values["current_ma"],
                    values["light_mv"],
                    values["raw_signal"],
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
        raw_signal: float | None = None,
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
        if raw_signal is not None:
            changes["raw_signal"] = _non_negative_number(
                raw_signal,
                "Sinal bruto",
            )
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

    def sync_measurement_history(
        self,
        measurement_id: int,
    ) -> dict[str, Any] | None:
        """Copy one completed dosimeter acquisition into its typed history."""
        clean_id = int(measurement_id)
        with self.connect() as connection:
            measurement = connection.execute(
                "SELECT * FROM measurements WHERE id = ?",
                (clean_id,),
            ).fetchone()
            if measurement is None:
                raise ValueError("Medição não encontrada")
            if (
                measurement["test_mode"] != "DOSIMETER_ID"
                or measurement["status"] != "CONCLUIDO"
            ):
                return None

            reading_type = measurement["reading_type"] or "PERSONAL_DOSE"
            if reading_type not in VALID_READING_TYPES:
                raise ValueError("Tipo de leitura da medição é inválido")
            dose = float(measurement["dose_msv"])

            if reading_type == "PERSONAL_DOSE":
                table = "historico_dose"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO historico_dose (
                        measurement_id, time_dos, dosimeter_id, dose_dos,
                        status_dos, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_id,
                        measurement["measured_at"],
                        measurement["dosimeter_id"],
                        dose,
                        PERSONAL_DOSE_STATUS,
                        utc_now(),
                    ),
                )
            else:
                table = "historico_branco"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO historico_branco (
                        measurement_id, time_bg, dosimeter_id, dose_bg,
                        status_bg, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_id,
                        measurement["measured_at"],
                        measurement["dosimeter_id"],
                        dose,
                        BACKGROUND_STATUS,
                        utc_now(),
                    ),
                )
            row = connection.execute(
                f"SELECT * FROM {table} WHERE measurement_id = ?",
                (clean_id,),
            ).fetchone()
        return dict(row) if row else None

    def add_personal_dose(
        self,
        dosimeter_id: str,
        *,
        dose_dos: float,
        time_dos: datetime | str | None = None,
        status_dos: str = PERSONAL_DOSE_STATUS,
    ) -> int:
        """Store a used dosimeter reading in ``historico_dose``."""
        clean_id = normalize_dosimeter_id(dosimeter_id)
        if self.get_dosimeter(clean_id) is None:
            raise ValueError("Dosímetro não cadastrado")
        clean_status = str(status_dos).strip()
        if clean_status.casefold() != PERSONAL_DOSE_STATUS.casefold():
            raise ValueError(
                f"status_dos deve ser '{PERSONAL_DOSE_STATUS}'"
            )
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO historico_dose (
                    time_dos, dosimeter_id, dose_dos, status_dos, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    normalize_datetime(time_dos),
                    clean_id,
                    _non_negative_number(dose_dos, "Dose"),
                    PERSONAL_DOSE_STATUS,
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def get_personal_dose(self, record_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM historico_dose WHERE id = ?",
                (int(record_id),),
            ).fetchone()
        return dict(row) if row else None

    def search_personal_doses(
        self,
        *,
        dosimeter_id: str | None = None,
        date_from: date | datetime | str | None = None,
        date_to: date | datetime | str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if isinstance(limit, bool) or not 1 <= int(limit) <= 10_000:
            raise ValueError("limit deve estar entre 1 e 10000")
        if dosimeter_id:
            clauses.append("h.dosimeter_id = ?")
            parameters.append(normalize_dosimeter_id(dosimeter_id))
        if date_from is not None:
            clauses.append("h.time_dos >= ?")
            parameters.append(_filter_datetime(date_from, end_of_day=False))
        if date_to is not None:
            clauses.append("h.time_dos <= ?")
            parameters.append(_filter_datetime(date_to, end_of_day=True))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(int(limit))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT h.*
                FROM historico_dose h
                {where}
                ORDER BY h.time_dos DESC, h.id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def add_background(
        self,
        dosimeter_id: str,
        *,
        dose_bg: float,
        time_bg: datetime | str | None = None,
        status_bg: str = BACKGROUND_STATUS,
    ) -> int:
        """Store a post-erasure reading in ``historico_branco``."""
        clean_id = normalize_dosimeter_id(dosimeter_id)
        if self.get_dosimeter(clean_id) is None:
            raise ValueError("Dosímetro não cadastrado")
        clean_status = str(status_bg).strip()
        if clean_status.casefold() != BACKGROUND_STATUS.casefold():
            raise ValueError(f"status_bg deve ser '{BACKGROUND_STATUS}'")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO historico_branco (
                    time_bg, dosimeter_id, dose_bg, status_bg, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    normalize_datetime(time_bg),
                    clean_id,
                    _non_negative_number(dose_bg, "Dose de background"),
                    BACKGROUND_STATUS,
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def get_background(self, record_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM historico_branco WHERE id = ?",
                (int(record_id),),
            ).fetchone()
        return dict(row) if row else None

    def get_latest_background(
        self,
        dosimeter_id: str,
        *,
        at_time: datetime | str | None = None,
    ) -> dict[str, Any] | None:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        parameters: list[Any] = [clean_id]
        time_clause = ""
        if at_time is not None:
            time_clause = "AND time_bg <= ?"
            parameters.append(normalize_datetime(at_time))
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM historico_branco
                WHERE dosimeter_id = ? {time_clause}
                ORDER BY time_bg DESC, id DESC
                LIMIT 1
                """,
                parameters,
            ).fetchone()
        return dict(row) if row else None

    def get_background_value(
        self,
        dosimeter_id: str,
        *,
        at_time: datetime | str | None = None,
        default: float = 0.0,
    ) -> float:
        """Return the latest dose background or the configured default."""
        fallback = _non_negative_number(default, "Background padrão")
        record = self.get_latest_background(dosimeter_id, at_time=at_time)
        if record is None:
            return fallback
        return float(record["dose_bg"])

    def calculate_net_personal_dose(
        self,
        dosimeter_id: str,
        reader_id: str,
        *,
        dose_reading: float,
        measured_at: datetime | str | None = None,
        default_background: float = 0.0,
    ) -> dict[str, float]:
        """Subtract the latest same-dosimeter background from a dose in mSv."""
        measurement_time = normalize_datetime(measured_at)
        measurement_date = measurement_time[:10]
        dosimeter = self.get_valid_dosimeter_for_test(
            dosimeter_id,
            at_date=measurement_date,
        )
        reader = self.get_valid_reader_for_test(
            reader_id,
            at_date=measurement_date,
        )
        dose = _non_negative_number(dose_reading, "Leitura de dose")
        background = self.get_background_value(
            dosimeter["dosimeter_id"],
            at_time=measurement_time,
            default=default_background,
        )
        ecc = float(dosimeter["ecc"])
        rcf = float(reader["rcf"])
        return {
            "dose_msv": max(0.0, dose - background),
            "background_msv": background,
            "ecc_applied": ecc,
            "rcf_applied": rcf,
        }

    def search_backgrounds(
        self,
        *,
        dosimeter_id: str | None = None,
        date_from: date | datetime | str | None = None,
        date_to: date | datetime | str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if isinstance(limit, bool) or not 1 <= int(limit) <= 10_000:
            raise ValueError("limit deve estar entre 1 e 10000")
        if dosimeter_id:
            clauses.append("h.dosimeter_id = ?")
            parameters.append(normalize_dosimeter_id(dosimeter_id))
        if date_from is not None:
            clauses.append("h.time_bg >= ?")
            parameters.append(_filter_datetime(date_from, end_of_day=False))
        if date_to is not None:
            clauses.append("h.time_bg <= ?")
            parameters.append(_filter_datetime(date_to, end_of_day=True))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(int(limit))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT h.*
                FROM historico_branco h
                {where}
                ORDER BY h.time_bg DESC, h.id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _export_rows(
        destination: str | Path,
        rows: Sequence[Mapping[str, Any]],
        columns: Sequence[str],
    ) -> Path:
        output = Path(destination).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=columns,
                extrasaction="ignore",
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))
        return output

    def export_personal_doses_csv(
        self,
        destination: str | Path,
        rows: Sequence[Mapping[str, Any]] | None = None,
    ) -> Path:
        data = list(rows) if rows is not None else self.search_personal_doses()
        return self._export_rows(destination, data, PERSONAL_DOSE_COLUMNS)

    def export_backgrounds_csv(
        self,
        destination: str | Path,
        rows: Sequence[Mapping[str, Any]] | None = None,
    ) -> Path:
        data = list(rows) if rows is not None else self.search_backgrounds()
        return self._export_rows(destination, data, BACKGROUND_COLUMNS)

    def export_csv(
        self,
        destination: str | Path,
        rows: Sequence[Mapping[str, Any]] | None = None,
    ) -> Path:
        data = list(rows) if rows is not None else self.search_measurements()
        return self._export_rows(destination, data, MEASUREMENT_COLUMNS)

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

    def import_database(
        self,
        source: str | Path,
        *,
        backup_destination: str | Path | None = None,
    ) -> dict[str, Any]:
        """Validate, migrate and import another application SQLite database."""
        input_path = Path(source).expanduser().resolve()
        if not input_path.is_file():
            raise FileNotFoundError(f"Banco não encontrado: {input_path}")
        if input_path == self.db_path:
            raise ValueError("Selecione um banco diferente do banco atual")

        required_tables = {"dosimeters", "readers", "measurements"}
        with tempfile.TemporaryDirectory(prefix="osl_import_") as temp_dir:
            candidate_path = Path(temp_dir) / "import_candidate.sqlite3"
            source_connection = sqlite3.connect(
                input_path,
                timeout=self.busy_timeout_ms / 1000,
            )
            candidate_connection = sqlite3.connect(candidate_path)
            try:
                integrity = source_connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
                if integrity is None or integrity[0] != "ok":
                    raise sqlite3.DatabaseError(
                        "O arquivo selecionado não é um banco SQLite íntegro"
                    )
                tables = {
                    row[0]
                    for row in source_connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                missing = required_tables - tables
                if missing:
                    raise ValueError(
                        "Banco incompatível; tabelas ausentes: "
                        + ", ".join(sorted(missing))
                    )
                source_connection.backup(candidate_connection)
                candidate_connection.commit()
            finally:
                candidate_connection.close()
                source_connection.close()

            candidate = Database(
                candidate_path,
                busy_timeout_ms=self.busy_timeout_ms,
            )
            with candidate.connect() as connection:
                integrity = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
                if integrity is None or integrity[0] != "ok":
                    raise sqlite3.DatabaseError(
                        "Falha de integridade após migrar o banco importado"
                    )
                foreign_key_errors = connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                if foreign_key_errors:
                    raise sqlite3.IntegrityError(
                        "O banco importado possui referências inválidas"
                    )

            if backup_destination is None:
                backup_directory = self.db_path.parent.parent / "backups"
                backup_name = datetime.now().strftime(
                    "pre_import_%Y-%m-%d_%H-%M-%S_%f.sqlite3"
                )
                backup_path = backup_directory / backup_name
            else:
                backup_path = Path(backup_destination).expanduser().resolve()
            backup_path = self.backup(backup_path)

            try:
                imported_source = sqlite3.connect(
                    candidate_path,
                    timeout=self.busy_timeout_ms / 1000,
                )
                current_target = sqlite3.connect(
                    self.db_path,
                    timeout=self.busy_timeout_ms / 1000,
                )
                try:
                    imported_source.backup(current_target)
                    current_target.commit()
                finally:
                    current_target.close()
                    imported_source.close()

                with self.connect() as connection:
                    imported_integrity = connection.execute(
                        "PRAGMA integrity_check"
                    ).fetchone()
                    if (
                        imported_integrity is None
                        or imported_integrity[0] != "ok"
                    ):
                        raise sqlite3.DatabaseError(
                            "Falha de integridade ao instalar o banco importado"
                        )
                    if connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchone() is not None:
                        raise sqlite3.IntegrityError(
                            "O banco importado possui referências inválidas"
                        )
            except Exception as import_error:
                restore_source = sqlite3.connect(backup_path)
                restore_target = sqlite3.connect(self.db_path)
                try:
                    restore_source.backup(restore_target)
                    restore_target.commit()
                except Exception as restore_error:
                    raise RuntimeError(
                        "A importação falhou e o backup automático não pôde "
                        "ser restaurado"
                    ) from restore_error
                finally:
                    restore_target.close()
                    restore_source.close()
                raise import_error

        return {
            "source": input_path,
            "backup": backup_path,
            "schema_version": SCHEMA_VERSION,
        }

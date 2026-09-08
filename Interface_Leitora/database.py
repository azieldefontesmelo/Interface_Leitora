from __future__ import annotations

import csv
import math
import sqlite3
import sys
import tempfile
from uuid import uuid4
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from app_paths import USER_DATA_DIR


SCHEMA_VERSION = 9
BUSY_TIMEOUT_MS = 10_000


def _application_dir() -> Path:
    """Return the persistent application-data directory."""
    return USER_DATA_DIR


DEFAULT_DB_PATH = (
    _application_dir() / "assets" / "database" / "measurements.sqlite3"
)

MEASUREMENT_COLUMNS = (
    "id",
    "measured_at",
    "test_mode",
    "reading_type",
    "dose_channel",
    "test_session_id",
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
    "test_session_id",
    "hp10_measurement_id",
    "hp007_measurement_id",
    "time_dos",
    "dosimeter_id",
    "hp10_dos",
    "hp007_dos",
    "dose_dos",
    "status_dos",
    "created_at",
)

BACKGROUND_COLUMNS = (
    "id",
    "measurement_id",
    "test_session_id",
    "hp10_measurement_id",
    "hp007_measurement_id",
    "time_bg",
    "dosimeter_id",
    "hp10_counts",
    "hp007_counts",
    "counts",
    "status_bg",
    "created_at",
)

PERSONAL_DOSE_STATUS = "Need to Erase"
READY_FOR_USE_STATUS = "Ready to Use"
NEED_RE_READ_STATUS = "Need to Re-read"
BACKGROUND_STATUS = "Ready to Use"

VALID_PERSONAL_DOSE_STATUSES = frozenset(
    {PERSONAL_DOSE_STATUS, READY_FOR_USE_STATUS, NEED_RE_READ_STATUS}
)

VALID_TEST_MODES = frozenset({"MANUAL", "DOSIMETER_ID"})
VALID_READING_TYPES = frozenset({"PERSONAL_DOSE", "BACKGROUND"})
VALID_DOSE_CHANNELS = frozenset({"HP10", "HP007"})
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
    ecc_hp10     REAL NOT NULL CHECK (ecc_hp10 > 0),
    ecc_hp007    REAL NOT NULL CHECK (ecc_hp007 > 0),
    bl_hp10      REAL NOT NULL DEFAULT 1 CHECK (bl_hp10 >= 0),
    bl_hp007     REAL NOT NULL DEFAULT 1 CHECK (bl_hp007 >= 0),
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
    dose_channel     TEXT CHECK (
        dose_channel IS NULL OR dose_channel IN ('HP10', 'HP007')
    ),
    test_session_id  TEXT,
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
    test_session_id TEXT,
    hp10_measurement_id INTEGER,
    hp007_measurement_id INTEGER,
    time_dos     TEXT NOT NULL,
    dosimeter_id TEXT NOT NULL,
    hp10_dos     REAL CHECK (hp10_dos IS NULL OR hp10_dos >= 0),
    hp007_dos    REAL CHECK (hp007_dos IS NULL OR hp007_dos >= 0),
    dose_dos     REAL NOT NULL CHECK (dose_dos >= 0),
    status_dos   TEXT NOT NULL DEFAULT 'Need to Erase'
                 CHECK (
                     status_dos IN (
                         'Need to Erase', 'Ready to Use', 'Need to Re-read'
                     )
                 ),
    created_at   TEXT NOT NULL,
    FOREIGN KEY (dosimeter_id)
        REFERENCES dosimeters(dosimeter_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (measurement_id)
        REFERENCES measurements(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (hp10_measurement_id)
        REFERENCES measurements(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (hp007_measurement_id)
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
    test_session_id TEXT,
    hp10_measurement_id INTEGER,
    hp007_measurement_id INTEGER,
    time_bg      TEXT NOT NULL,
    dosimeter_id TEXT NOT NULL,
    hp10_counts  REAL CHECK (hp10_counts IS NULL OR hp10_counts >= 0),
    hp007_counts REAL CHECK (hp007_counts IS NULL OR hp007_counts >= 0),
    counts       REAL NOT NULL CHECK (counts >= 0),
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
        ON DELETE RESTRICT,
    FOREIGN KEY (hp10_measurement_id)
        REFERENCES measurements(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (hp007_measurement_id)
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
            self._migrate_dual_dosimeter_parameters(connection)
            self._migrate_measurement_histories(connection)
            self._migrate_personal_dose_statuses(connection)
            # This cleanup belongs to the v8 migration. Do not run it again
            # when a v8 database is upgraded only for the status-tag schema.
            if current_version < 8:
                self._migrate_legacy_history_duplicates(connection)
            self._refresh_personal_dose_statuses(connection)
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
    def _refresh_personal_dose_statuses(
        connection: sqlite3.Connection,
    ) -> None:
        """Keep the persisted personal-dose tag derived from the dose value."""
        connection.execute(
            """
            UPDATE historico_dose
            SET status_dos = CASE
                WHEN dose_dos < 0.01 THEN 'Need to Erase'
                WHEN dose_dos < 2 THEN 'Ready to Use'
                ELSE 'Need to Re-read'
            END
            """
        )

    @staticmethod
    def _migrate_personal_dose_statuses(
        connection: sqlite3.Connection,
    ) -> None:
        """Upgrade the old one-tag history table to the dose-based tags."""
        table_sql = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'historico_dose'
            """
        ).fetchone()[0]
        if table_sql and "status_dos = 'Need to Erase'" in table_sql:
            connection.execute("PRAGMA foreign_keys = OFF")
            try:
                connection.executescript(
                    """
                    DROP INDEX IF EXISTS idx_historico_dose_dosimeter_time;
                    DROP INDEX IF EXISTS idx_historico_dose_time;
                    DROP INDEX IF EXISTS idx_historico_dose_measurement;
                    DROP INDEX IF EXISTS idx_historico_dose_session;

                    CREATE TABLE historico_dose_v9 (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        measurement_id INTEGER,
                        test_session_id TEXT,
                        hp10_measurement_id INTEGER,
                        hp007_measurement_id INTEGER,
                        time_dos     TEXT NOT NULL,
                        dosimeter_id TEXT NOT NULL,
                        hp10_dos     REAL CHECK (hp10_dos IS NULL OR hp10_dos >= 0),
                        hp007_dos    REAL CHECK (hp007_dos IS NULL OR hp007_dos >= 0),
                        dose_dos     REAL NOT NULL CHECK (dose_dos >= 0),
                        status_dos   TEXT NOT NULL DEFAULT 'Need to Erase'
                                     CHECK (
                                         status_dos IN (
                                             'Need to Erase', 'Ready to Use',
                                             'Need to Re-read'
                                         )
                                     ),
                        created_at   TEXT NOT NULL,
                        FOREIGN KEY (dosimeter_id)
                            REFERENCES dosimeters(dosimeter_id)
                            ON UPDATE CASCADE ON DELETE RESTRICT,
                        FOREIGN KEY (measurement_id)
                            REFERENCES measurements(id)
                            ON UPDATE CASCADE ON DELETE RESTRICT,
                        FOREIGN KEY (hp10_measurement_id)
                            REFERENCES measurements(id)
                            ON UPDATE CASCADE ON DELETE RESTRICT,
                        FOREIGN KEY (hp007_measurement_id)
                            REFERENCES measurements(id)
                            ON UPDATE CASCADE ON DELETE RESTRICT
                    );

                    INSERT INTO historico_dose_v9 (
                        id, measurement_id, test_session_id,
                        hp10_measurement_id, hp007_measurement_id,
                        time_dos, dosimeter_id, hp10_dos, hp007_dos,
                        dose_dos, status_dos, created_at
                    )
                    SELECT id, measurement_id, test_session_id,
                           hp10_measurement_id, hp007_measurement_id,
                           time_dos, dosimeter_id, hp10_dos, hp007_dos,
                           dose_dos,
                           CASE
                               WHEN dose_dos < 0.01 THEN 'Need to Erase'
                               WHEN dose_dos < 2 THEN 'Ready to Use'
                               ELSE 'Need to Re-read'
                           END,
                           created_at
                    FROM historico_dose;

                    DROP TABLE historico_dose;
                    ALTER TABLE historico_dose_v9 RENAME TO historico_dose;

                    CREATE INDEX idx_historico_dose_dosimeter_time
                        ON historico_dose(dosimeter_id, time_dos DESC);
                    CREATE INDEX idx_historico_dose_time
                        ON historico_dose(time_dos DESC);
                    CREATE UNIQUE INDEX idx_historico_dose_measurement
                        ON historico_dose(measurement_id)
                        WHERE measurement_id IS NOT NULL;
                    CREATE UNIQUE INDEX idx_historico_dose_session
                        ON historico_dose(test_session_id)
                        WHERE test_session_id IS NOT NULL;
                    """
                )
            finally:
                connection.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _personal_dose_status(dose: float) -> str:
        """Return the English tag for a personal dose reading."""
        value = float(dose)
        if not math.isfinite(value) or value < 0:
            raise ValueError("A dose deve ser um número finito não negativo")
        if value < 0.01:
            return PERSONAL_DOSE_STATUS
        if value < 2:
            return READY_FOR_USE_STATUS
        return NEED_RE_READ_STATUS

    @staticmethod
    def _migrate_legacy_history_duplicates(
        connection: sqlite3.Connection,
    ) -> None:
        """Collapse one legacy history row per acquisition into one per session.

        Older migrations created a synthetic history session for every completed
        measurement.  That made repeated BL readings appear as repeated final
        history records.  The source measurements still contain the real
        session id, so use it to retain one consolidated row per session.
        """

        configurations = (
            (
                "historico_dose",
                "legacy-measurement-dose-%",
                "time_dos",
                "hp10_dos",
                "hp007_dos",
                "dose_dos",
                "status_dos",
                PERSONAL_DOSE_STATUS,
                "dose_msv",
            ),
            (
                "historico_branco",
                "legacy-measurement-background-%",
                "time_bg",
                "hp10_counts",
                "hp007_counts",
                "counts",
                "status_bg",
                BACKGROUND_STATUS,
                "raw_signal",
            ),
        )

        for (
            table,
            legacy_pattern,
            time_column,
            hp10_column,
            hp007_column,
            aggregate_column,
            status_column,
            status_value,
            source_value_column,
        ) in configurations:
            legacy_rows = connection.execute(
                f"""
                SELECT h.*, m.test_session_id AS source_session_id
                FROM {table} AS h
                LEFT JOIN measurements AS m
                  ON m.id = COALESCE(
                        h.measurement_id,
                        h.hp10_measurement_id,
                        h.hp007_measurement_id
                     )
                WHERE h.test_session_id LIKE ?
                ORDER BY h.id
                """,
                (legacy_pattern,),
            ).fetchall()
            groups: dict[str, list[sqlite3.Row]] = {}
            for row in legacy_rows:
                source_session_id = row["source_session_id"]
                if source_session_id:
                    groups.setdefault(str(source_session_id), []).append(row)

            if not groups:
                continue

            consolidated_sessions = {
                row["test_session_id"]
                for row in connection.execute(
                    f"""
                    SELECT test_session_id
                    FROM {table}
                    WHERE test_session_id IS NOT NULL
                      AND test_session_id NOT LIKE ?
                    """,
                    (legacy_pattern,),
                ).fetchall()
            }

            # Delete first.  This lets the representative row take the real
            # session id without violating the unique session index.
            rows_to_delete: list[tuple[int]] = []
            representatives: list[tuple[str, sqlite3.Row]] = []
            for source_session_id, rows in groups.items():
                if source_session_id in consolidated_sessions:
                    rows_to_delete.extend((int(row["id"]),) for row in rows)
                    continue
                representative = max(
                    rows,
                    key=lambda row: (
                        str(row[time_column] or ""),
                        int(row["id"]),
                    ),
                )
                representatives.append((source_session_id, representative))
                rows_to_delete.extend(
                    (int(row["id"]),)
                    for row in rows
                    if int(row["id"]) != int(representative["id"])
                )

            if rows_to_delete:
                connection.executemany(
                    f"DELETE FROM {table} WHERE id = ?",
                    rows_to_delete,
                )

            for source_session_id, representative in representatives:
                measurements = connection.execute(
                    f"""
                    SELECT *
                    FROM measurements
                    WHERE test_session_id = ?
                      AND test_mode = 'DOSIMETER_ID'
                      AND reading_type = ?
                      AND status = 'CONCLUIDO'
                      AND dose_channel IN ('HP10', 'HP007')
                    ORDER BY measured_at DESC, id DESC
                    """,
                    (
                        source_session_id,
                        "BACKGROUND"
                        if table == "historico_branco"
                        else "PERSONAL_DOSE",
                    ),
                ).fetchall()
                latest_by_channel: dict[str, sqlite3.Row] = {}
                for measurement in measurements:
                    latest_by_channel.setdefault(
                        measurement["dose_channel"],
                        measurement,
                    )

                source_by_channel = {
                    "HP10": latest_by_channel.get("HP10"),
                    "HP007": latest_by_channel.get("HP007"),
                }
                selected_measurements = [
                    measurement
                    for measurement in source_by_channel.values()
                    if measurement is not None
                ]
                if selected_measurements:
                    primary = max(
                        selected_measurements,
                        key=lambda row: (
                            str(row["measured_at"] or ""),
                            int(row["id"]),
                        ),
                    )
                    hp10_value = (
                        None
                        if source_by_channel["HP10"] is None
                        else source_by_channel["HP10"][source_value_column]
                    )
                    hp007_value = (
                        None
                        if source_by_channel["HP007"] is None
                        else source_by_channel["HP007"][source_value_column]
                    )
                    aggregate_value = max(
                        float(value)
                        for value in (hp10_value, hp007_value)
                        if value is not None
                    )
                    update_values = (
                        source_session_id,
                        int(primary["id"]),
                        None
                        if source_by_channel["HP10"] is None
                        else int(source_by_channel["HP10"]["id"]),
                        None
                        if source_by_channel["HP007"] is None
                        else int(source_by_channel["HP007"]["id"]),
                        primary["measured_at"],
                        primary["dosimeter_id"],
                        hp10_value,
                        hp007_value,
                        aggregate_value,
                        status_value,
                        representative["created_at"],
                        int(representative["id"]),
                    )
                    connection.execute(
                        f"""
                        UPDATE {table}
                        SET test_session_id = ?, measurement_id = ?,
                            hp10_measurement_id = ?, hp007_measurement_id = ?,
                            {time_column} = ?, dosimeter_id = ?,
                            {hp10_column} = ?, {hp007_column} = ?,
                            {aggregate_column} = ?, {status_column} = ?,
                            created_at = ?
                        WHERE id = ?
                        """,
                        update_values,
                    )
                else:
                    # Keep malformed legacy rows available for audit instead of
                    # deleting data that cannot be linked to source measurements.
                    connection.execute(
                        f"""
                        UPDATE {table}
                        SET test_session_id = ?
                        WHERE id = ?
                        """,
                        (source_session_id, int(representative["id"])),
                    )

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
    def _migrate_dual_dosimeter_parameters(
        connection: sqlite3.Connection,
    ) -> None:
        """Add per-channel ECC/BL values and rename legacy BC columns."""
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(dosimeters)")
        }
        for old_column, new_column in (
            ("bc_hp10", "bl_hp10"),
            ("bc_hp007", "bl_hp007"),
        ):
            if old_column in columns and new_column not in columns:
                connection.execute(
                    f"ALTER TABLE dosimeters RENAME COLUMN "
                    f"{old_column} TO {new_column}"
                )
                columns.remove(old_column)
                columns.add(new_column)
        legacy_ecc = "ecc" in columns
        additions = (
            ("ecc_hp10", "REAL NOT NULL DEFAULT 1 CHECK (ecc_hp10 > 0)"),
            ("ecc_hp007", "REAL NOT NULL DEFAULT 1 CHECK (ecc_hp007 > 0)"),
            ("bl_hp10", "REAL NOT NULL DEFAULT 1 CHECK (bl_hp10 >= 0)"),
            ("bl_hp007", "REAL NOT NULL DEFAULT 1 CHECK (bl_hp007 >= 0)"),
        )
        for column, definition in additions:
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE dosimeters ADD COLUMN {column} {definition}"
                )
        if legacy_ecc:
            connection.execute(
                """
                UPDATE dosimeters
                SET ecc_hp10 = ecc,
                    ecc_hp007 = ecc
                """
            )

    @staticmethod
    def _migrate_measurement_histories(
        connection: sqlite3.Connection,
    ) -> None:
        """Upgrade acquisitions and histories to the paired-channel model."""

        def rename_column(table: str, old: str, new: str) -> None:
            columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if old in columns and new not in columns:
                connection.execute(
                    f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}"
                )

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
            "measurements",
            "dose_channel",
            "TEXT CHECK (dose_channel IS NULL OR dose_channel IN "
            "('HP10', 'HP007'))",
        )
        ensure_column("measurements", "test_session_id", "TEXT")
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

        rename_column("historico_branco", "hp10_bg", "hp10_counts")
        rename_column("historico_branco", "hp007_bg", "hp007_counts")
        rename_column("historico_branco", "dose_bg", "counts")

        history_additions = {
            "historico_dose": (
                ("test_session_id", "TEXT"),
                ("hp10_measurement_id", "INTEGER"),
                ("hp007_measurement_id", "INTEGER"),
                ("hp10_dos", "REAL CHECK (hp10_dos IS NULL OR hp10_dos >= 0)"),
                ("hp007_dos", "REAL CHECK (hp007_dos IS NULL OR hp007_dos >= 0)"),
                ("dose_dos", "REAL"),
            ),
            "historico_branco": (
                ("test_session_id", "TEXT"),
                ("hp10_measurement_id", "INTEGER"),
                ("hp007_measurement_id", "INTEGER"),
                (
                    "hp10_counts",
                    "REAL CHECK (hp10_counts IS NULL OR hp10_counts >= 0)",
                ),
                (
                    "hp007_counts",
                    "REAL CHECK (hp007_counts IS NULL OR hp007_counts >= 0)",
                ),
                ("counts", "REAL"),
            ),
        }
        for table, additions in history_additions.items():
            for column, definition in additions:
                ensure_column(table, column, definition)

        # Preserve the original two-channel values when present. For records
        # created by the v5 single-dose model, Hp(10) is used as the explicit
        # legacy channel and Hp(0.07) remains unknown (NULL).
        connection.execute(
            """
            UPDATE historico_dose
            SET dose_dos = COALESCE(dose_dos, MAX(hp10_dos, hp007_dos, 0)),
                hp10_dos = COALESCE(hp10_dos, dose_dos),
                test_session_id = COALESCE(
                    test_session_id, 'legacy-dose-' || id
                ),
                hp10_measurement_id = COALESCE(
                    hp10_measurement_id, measurement_id
                )
            """
        )
        connection.execute(
            """
            UPDATE historico_branco
            SET counts = COALESCE(
                    counts,
                    MAX(COALESCE(hp10_counts, 0), COALESCE(hp007_counts, 0))
                ),
                hp10_counts = COALESCE(hp10_counts, counts),
                test_session_id = COALESCE(
                    test_session_id, 'legacy-background-' || id
                ),
                hp10_measurement_id = COALESCE(
                    hp10_measurement_id, measurement_id
                )
            """
        )
        connection.execute(
            """
            UPDATE historico_branco
            SET hp10_counts = COALESCE(
                    (
                        SELECT raw_signal
                        FROM measurements
                        WHERE id = historico_branco.hp10_measurement_id
                    ),
                    hp10_counts
                ),
                hp007_counts = COALESCE(
                    (
                        SELECT raw_signal
                        FROM measurements
                        WHERE id = historico_branco.hp007_measurement_id
                    ),
                    hp007_counts
                )
            """
        )
        connection.execute(
            """
            UPDATE historico_branco
            SET counts = MAX(
                COALESCE(hp10_counts, 0),
                COALESCE(hp007_counts, 0)
            )
            """
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
            CREATE UNIQUE INDEX IF NOT EXISTS idx_historico_dose_session
                ON historico_dose(test_session_id)
                WHERE test_session_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_historico_branco_dosimeter_time
                ON historico_branco(dosimeter_id, time_bg DESC);
            CREATE INDEX IF NOT EXISTS idx_historico_branco_time
                ON historico_branco(time_bg DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_historico_branco_measurement
                ON historico_branco(measurement_id)
                WHERE measurement_id IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_historico_branco_session
                ON historico_branco(test_session_id)
                WHERE test_session_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_measurements_test_session
                ON measurements(test_session_id, dose_channel);
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
                measurement_id, test_session_id, hp10_measurement_id,
                time_dos, dosimeter_id, hp10_dos, dose_dos,
                status_dos, created_at
            )
            SELECT id, 'legacy-measurement-dose-' || id, id,
                   measured_at, dosimeter_id, dose_msv, dose_msv,
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
                measurement_id, test_session_id, hp10_measurement_id,
                time_bg, dosimeter_id, hp10_counts, counts,
                status_bg, created_at
            )
            SELECT id, 'legacy-measurement-background-' || id, id,
                   measured_at, dosimeter_id, raw_signal, raw_signal,
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
        ecc_hp10: float | None = None,
        ecc_hp007: float | None = None,
        bl_hp10: float = 1.0,
        bl_hp007: float = 1.0,
        ecc: float | None = None,
        begin_date: date | datetime | str,
        end_date: date | datetime | str | None = None,
        active: bool = True,
    ) -> None:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        hp10_ecc = _positive_number(
            ecc_hp10 if ecc_hp10 is not None else (ecc if ecc is not None else 1),
            "ECC Hp(10)",
        )
        hp007_ecc = _positive_number(
            ecc_hp007 if ecc_hp007 is not None else (
                ecc if ecc is not None else hp10_ecc
            ),
            "ECC Hp(0,07)",
        )
        hp10_bl = _non_negative_number(bl_hp10, "BL Hp(10)")
        hp007_bl = _non_negative_number(bl_hp007, "BL Hp(0,07)")
        begin = normalize_date(begin_date)
        end = normalize_date(end_date) if end_date not in (None, "") else None
        if end is not None and end < begin:
            raise ValueError("A data final não pode ser anterior à data inicial")
        now = utc_now()
        with self.connect() as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(dosimeters)")
            }
            if "ecc" in columns:
                connection.execute(
                    """
                    INSERT INTO dosimeters (
                        dosimeter_id, ecc, ecc_hp10, ecc_hp007,
                        bl_hp10, bl_hp007, begin_date, end_date, active,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_id, hp10_ecc, hp10_ecc, hp007_ecc,
                        hp10_bl, hp007_bl, begin, end,
                        _active_value(active), now, now,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO dosimeters (
                        dosimeter_id, ecc_hp10, ecc_hp007,
                        bl_hp10, bl_hp007, begin_date, end_date, active,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_id, hp10_ecc, hp007_ecc, hp10_bl, hp007_bl,
                        begin, end, _active_value(active), now, now,
                    ),
                )

    def get_dosimeter(self, dosimeter_id: str) -> dict[str, Any] | None:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM dosimeters WHERE dosimeter_id = ?",
                (clean_id,),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["ecc"] = record["ecc_hp10"]
        return record

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
        records = [dict(row) for row in rows]
        for record in records:
            record["ecc"] = record["ecc_hp10"]
        return records

    def search_dosimeters_for_export(
        self,
        *,
        text: str | None = None,
        active: bool | None = None,
        date_from: date | datetime | str | None = None,
        date_to: date | datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        """Return dosimeters valid during the requested period.

        A dosimeter is included when its validity interval overlaps the
        selected period. The latest BL reading is returned independently.
        """
        clauses: list[str] = []
        parameters: list[Any] = []
        if text:
            clauses.append("d.dosimeter_id LIKE ?")
            parameters.append(f"%{text.strip()}%")
        if active is not None:
            clauses.append("d.active = ?")
            parameters.append(_active_value(active))
        if date_from is not None:
            clauses.append("(d.end_date IS NULL OR d.end_date >= ?)")
            parameters.append(normalize_date(date_from))
        if date_to is not None:
            clauses.append("d.begin_date <= ?")
            parameters.append(normalize_date(date_to))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT d.*,
                       (
                           SELECT h.time_bg
                           FROM historico_branco AS h
                           WHERE h.dosimeter_id = d.dosimeter_id
                           ORDER BY h.time_bg DESC, h.id DESC
                           LIMIT 1
                       ) AS last_bl_read_at
                FROM dosimeters AS d
                {where}
                ORDER BY d.dosimeter_id
                """,
                parameters,
            ).fetchall()
        records = [dict(row) for row in rows]
        for record in records:
            record["ecc"] = record["ecc_hp10"]
        return records

    def update_dosimeter(
        self,
        dosimeter_id: str,
        *,
        new_dosimeter_id: str | None = None,
        ecc_hp10: float | None = None,
        ecc_hp007: float | None = None,
        bl_hp10: float | None = None,
        bl_hp007: float | None = None,
        ecc: float | None = None,
        begin_date: date | datetime | str,
        end_date: date | datetime | str | None = None,
        active: bool,
    ) -> bool:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        new_clean_id = normalize_dosimeter_id(
            new_dosimeter_id if new_dosimeter_id is not None else clean_id
        )
        current = self.get_dosimeter(clean_id)
        if current is None:
            return False
        hp10_ecc = _positive_number(
            ecc_hp10 if ecc_hp10 is not None else (
                ecc if ecc is not None else current["ecc_hp10"]
            ),
            "ECC Hp(10)",
        )
        hp007_ecc = _positive_number(
            ecc_hp007 if ecc_hp007 is not None else (
                ecc if ecc is not None else current["ecc_hp007"]
            ),
            "ECC Hp(0,07)",
        )
        hp10_bl = _non_negative_number(
            current["bl_hp10"] if bl_hp10 is None else bl_hp10,
            "BL Hp(10)",
        )
        hp007_bl = _non_negative_number(
            current["bl_hp007"] if bl_hp007 is None else bl_hp007,
            "BL Hp(0,07)",
        )
        begin = normalize_date(begin_date)
        end = normalize_date(end_date) if end_date not in (None, "") else None
        if end is not None and end < begin:
            raise ValueError("A data final não pode ser anterior à data inicial")
        with self.connect() as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(dosimeters)")
            }
            legacy_assignment = "ecc = ?, " if "ecc" in columns else ""
            values = [new_clean_id]
            values += ([hp10_ecc] if "ecc" in columns else []) + [
                hp10_ecc, hp007_ecc, hp10_bl, hp007_bl, begin, end,
                _active_value(active), utc_now(), clean_id,
            ]
            cursor = connection.execute(
                f"""
                UPDATE dosimeters
                SET dosimeter_id = ?,
                    {legacy_assignment}ecc_hp10 = ?, ecc_hp007 = ?,
                    bl_hp10 = ?, bl_hp007 = ?, begin_date = ?, end_date = ?,
                    active = ?, updated_at = ?
                WHERE dosimeter_id = ?
                """,
                values,
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

    def delete_dosimeter_with_history(
        self,
        dosimeter_id: str,
    ) -> dict[str, int]:
        """Delete a dosimeter and all of its linked measurements/history."""
        clean_id = normalize_dosimeter_id(dosimeter_id)
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM dosimeters WHERE dosimeter_id = ?",
                (clean_id,),
            ).fetchone()
            if exists is None:
                raise ValueError("Dosímetro não encontrado")
            dose_rows = connection.execute(
                "DELETE FROM historico_dose WHERE dosimeter_id = ?",
                (clean_id,),
            ).rowcount
            background_rows = connection.execute(
                "DELETE FROM historico_branco WHERE dosimeter_id = ?",
                (clean_id,),
            ).rowcount
            measurement_rows = connection.execute(
                "DELETE FROM measurements WHERE dosimeter_id = ?",
                (clean_id,),
            ).rowcount
            dosimeter_rows = connection.execute(
                "DELETE FROM dosimeters WHERE dosimeter_id = ?",
                (clean_id,),
            ).rowcount
        return {
            "dosimeters": dosimeter_rows,
            "measurements": measurement_rows,
            "personal_doses": dose_rows,
            "backgrounds": background_rows,
        }

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
        new_reader_id: str | None = None,
        rcf: float,
        begin_date: date | datetime | str,
        end_date: date | datetime | str | None,
        active: bool,
    ) -> bool:
        clean_id = normalize_reader_id(reader_id)
        new_clean_id = normalize_reader_id(
            new_reader_id if new_reader_id is not None else clean_id
        )
        clean_rcf = _positive_number(rcf, "RCF")
        begin = normalize_date(begin_date)
        end = normalize_date(end_date) if end_date not in (None, "") else None
        if end is not None and end < begin:
            raise ValueError("A data final não pode ser anterior à data inicial")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE readers
                SET reader_id = ?, rcf = ?, begin_date = ?, end_date = ?, active = ?,
                    updated_at = ?
                WHERE reader_id = ?
                """,
                (
                    new_clean_id,
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

    def delete_reader_with_measurements(
        self,
        reader_id: str,
    ) -> dict[str, int]:
        """Delete a reader and acquisitions/history that reference it."""
        clean_id = normalize_reader_id(reader_id)
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM readers WHERE reader_id = ?",
                (clean_id,),
            ).fetchone()
            if exists is None:
                raise ValueError("Leitora não encontrada")
            dose_rows = connection.execute(
                """
                DELETE FROM historico_dose
                WHERE measurement_id IN (
                    SELECT id FROM measurements WHERE reader_id = ?
                )
                   OR hp10_measurement_id IN (
                    SELECT id FROM measurements WHERE reader_id = ?
                )
                   OR hp007_measurement_id IN (
                    SELECT id FROM measurements WHERE reader_id = ?
                )
                """,
                (clean_id, clean_id, clean_id),
            ).rowcount
            background_rows = connection.execute(
                """
                DELETE FROM historico_branco
                WHERE measurement_id IN (
                    SELECT id FROM measurements WHERE reader_id = ?
                )
                   OR hp10_measurement_id IN (
                    SELECT id FROM measurements WHERE reader_id = ?
                )
                   OR hp007_measurement_id IN (
                    SELECT id FROM measurements WHERE reader_id = ?
                )
                """,
                (clean_id, clean_id, clean_id),
            ).rowcount
            measurement_rows = connection.execute(
                "DELETE FROM measurements WHERE reader_id = ?",
                (clean_id,),
            ).rowcount
            reader_rows = connection.execute(
                "DELETE FROM readers WHERE reader_id = ?",
                (clean_id,),
            ).rowcount
        return {
            "readers": reader_rows,
            "measurements": measurement_rows,
            "personal_doses": dose_rows,
            "backgrounds": background_rows,
        }

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
        _positive_number(record["ecc_hp10"], "ECC Hp(10)")
        _positive_number(record["ecc_hp007"], "ECC Hp(0,07)")
        _non_negative_number(record["bl_hp10"], "BL Hp(10)")
        _non_negative_number(record["bl_hp007"], "BL Hp(0,07)")
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
        dose_channel: str | None = None,
        test_session_id: str | None = None,
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
        baseline_applied: float | None = None,
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
        clean_dose_channel: str | None = None
        clean_test_session_id: str | None = None
        if mode == "DOSIMETER_ID":
            clean_reading_type = str(
                reading_type or "PERSONAL_DOSE"
            ).strip().upper()
            if clean_reading_type not in VALID_READING_TYPES:
                raise ValueError(
                    "reading_type deve ser PERSONAL_DOSE ou BACKGROUND"
                )
            clean_dose_channel = str(dose_channel or "HP10").strip().upper()
            if clean_dose_channel not in VALID_DOSE_CHANNELS:
                raise ValueError("dose_channel deve ser HP10 ou HP007")
            clean_test_session_id = str(
                test_session_id or uuid4().hex
            ).strip()
            if not clean_test_session_id or len(clean_test_session_id) > 64:
                raise ValueError("test_session_id inválido")
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
            if dosimeter and clean_dose_channel == "HP007":
                ecc_applied = dosimeter["ecc_hp007"]
            elif dosimeter:
                ecc_applied = dosimeter["ecc_hp10"]
            else:
                ecc_applied = 1.0
        if rcf_applied is None:
            rcf_applied = reader["rcf"] if reader else 1.0
        if baseline_applied is None:
            if dosimeter and clean_dose_channel == "HP007":
                baseline_applied = dosimeter["bl_hp007"]
            elif dosimeter:
                baseline_applied = dosimeter["bl_hp10"]
            else:
                baseline_applied = 0.0

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
                "BL",
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
                    measured_at, test_mode, reading_type, dose_channel,
                    test_session_id, reader_id,
                    dosimeter_id, file_name, file_path,
                    count_01s, current_ma, light_mv, raw_signal, dose_msv,
                    ecc_applied, rcf_applied, fang_applied,
                    fenerg_applied, baseline_applied, status, notes,
                    created_at, updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    measurement_time,
                    mode,
                    clean_reading_type,
                    clean_dose_channel,
                    clean_test_session_id,
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

    def get_baseline_session_measurements(
        self,
        test_session_id: str,
    ) -> list[dict[str, Any]]:
        """Return selectable, completed BL readings from an existing session."""
        clean_session_id = str(test_session_id).strip()
        if not clean_session_id:
            raise ValueError("test_session_id inválido")
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM measurements
                WHERE test_session_id = ?
                  AND test_mode = 'DOSIMETER_ID'
                  AND reading_type = 'BACKGROUND'
                  AND status = 'CONCLUIDO'
                  AND dose_channel IN ('HP10', 'HP007')
                ORDER BY measured_at, id
                """,
                (clean_session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def apply_baseline_selection(
        self,
        test_session_id: str,
        dosimeter_id: str,
        *,
        hp10_measurement_id: int | None = None,
        hp007_measurement_id: int | None = None,
        hp10_counts: float | None = None,
        hp007_counts: float | None = None,
    ) -> dict[str, Any]:
        """Apply selected BL readings or calculated BL values."""
        clean_session_id = str(test_session_id).strip()
        clean_dosimeter_id = normalize_dosimeter_id(dosimeter_id)
        if not clean_session_id:
            raise ValueError("test_session_id inválido")
        selected_ids = {
            "HP10": hp10_measurement_id,
            "HP007": hp007_measurement_id,
        }
        selected_counts = {
            "HP10": hp10_counts,
            "HP007": hp007_counts,
        }
        if all(
            measurement_id is None and selected_counts[channel] is None
            for channel, measurement_id in selected_ids.items()
        ):
            raise ValueError("Selecione ao menos uma leitura de BL")
        if any(
            measurement_id is not None and selected_counts[channel] is not None
            for channel, measurement_id in selected_ids.items()
        ):
            raise ValueError("Escolha uma leitura ou um valor calculado por grandeza")

        with self.connect() as connection:
            dosimeter = connection.execute(
                "SELECT * FROM dosimeters WHERE dosimeter_id = ?",
                (clean_dosimeter_id,),
            ).fetchone()
            if dosimeter is None:
                raise ValueError("Dosímetro não cadastrado")

            selected: dict[str, sqlite3.Row] = {}
            for channel, measurement_id in selected_ids.items():
                if measurement_id is None:
                    continue
                measurement = connection.execute(
                    "SELECT * FROM measurements WHERE id = ?",
                    (int(measurement_id),),
                ).fetchone()
                if measurement is None:
                    raise ValueError("Leitura de BL não encontrada")
                if (
                    measurement["test_session_id"] != clean_session_id
                    or measurement["dosimeter_id"] != clean_dosimeter_id
                    or measurement["test_mode"] != "DOSIMETER_ID"
                    or measurement["reading_type"] != "BACKGROUND"
                    or measurement["dose_channel"] != channel
                    or measurement["status"] != "CONCLUIDO"
                ):
                    raise ValueError(
                        f"A leitura selecionada para {channel} não pertence "
                        "à sessão BL ativa"
                    )
                selected[channel] = measurement

            hp10_counts = (
                float(selected["HP10"]["raw_signal"])
                if "HP10" in selected
                else (
                    _non_negative_number(
                        selected_counts["HP10"],
                        "Contagens Hp(10)",
                    )
                    if selected_counts["HP10"] is not None
                    else None
                )
            )
            hp007_counts = (
                float(selected["HP007"]["raw_signal"])
                if "HP007" in selected
                else (
                    _non_negative_number(
                        selected_counts["HP007"],
                        "Contagens Hp(0,07)",
                    )
                    if selected_counts["HP007"] is not None
                    else None
                )
            )
            applied_at = utc_now()
            connection.execute(
                """
                UPDATE dosimeters
                SET bl_hp10 = ?, bl_hp007 = ?, updated_at = ?
                WHERE dosimeter_id = ?
                """,
                (
                    dosimeter["bl_hp10"] if hp10_counts is None else hp10_counts,
                    dosimeter["bl_hp007"] if hp007_counts is None else hp007_counts,
                    applied_at,
                    clean_dosimeter_id,
                ),
            )

            selected_rows = list(selected.values())
            primary_measurement = (
                max(selected_rows, key=lambda row: row["id"])
                if selected_rows
                else None
            )
            applied_counts = [
                value for value in (hp10_counts, hp007_counts) if value is not None
            ]
            connection.execute(
                """
                INSERT OR IGNORE INTO historico_branco (
                    measurement_id, test_session_id,
                    hp10_measurement_id, hp007_measurement_id,
                    time_bg, dosimeter_id, hp10_counts, hp007_counts,
                    counts, status_bg, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    primary_measurement["id"] if primary_measurement else None,
                    clean_session_id,
                    selected["HP10"]["id"] if "HP10" in selected else None,
                    selected["HP007"]["id"] if "HP007" in selected else None,
                    (
                        max(row["measured_at"] for row in selected_rows)
                        if selected_rows
                        else applied_at
                    ),
                    clean_dosimeter_id,
                    hp10_counts,
                    hp007_counts,
                    max(applied_counts),
                    BACKGROUND_STATUS,
                    applied_at,
                ),
            )
            for channel, measurement in selected.items():
                note = f"Selecionada como BL {channel} em {applied_at}"
                existing_note = str(measurement["notes"] or "").strip()
                connection.execute(
                    """
                    UPDATE measurements
                    SET notes = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        f"{existing_note}; {note}" if existing_note else note,
                        applied_at,
                        measurement["id"],
                    ),
                )
            history = connection.execute(
                """
                SELECT *
                FROM historico_branco
                WHERE test_session_id = ?
                """,
                (clean_session_id,),
            ).fetchone()
        return dict(history)

    def sync_measurement_history(
        self,
        measurement_id: int,
    ) -> dict[str, Any] | None:
        """Consolidate a dosimeter session after both channels are complete."""
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
            test_session_id = measurement["test_session_id"]
            dose_channel = measurement["dose_channel"]
            if not test_session_id or dose_channel not in VALID_DOSE_CHANNELS:
                return None
            acquisitions = connection.execute(
                """
                SELECT *
                FROM measurements
                WHERE test_session_id = ?
                  AND test_mode = 'DOSIMETER_ID'
                  AND reading_type = ?
                  AND dosimeter_id = ?
                  AND status = 'CONCLUIDO'
                  AND dose_channel IN ('HP10', 'HP007')
                ORDER BY id DESC
                """,
                (
                    test_session_id,
                    reading_type,
                    measurement["dosimeter_id"],
                ),
            ).fetchall()
            by_channel: dict[str, sqlite3.Row] = {}
            for acquisition in acquisitions:
                by_channel.setdefault(acquisition["dose_channel"], acquisition)
            if set(by_channel) != VALID_DOSE_CHANNELS:
                return None

            hp10 = by_channel["HP10"]
            hp007 = by_channel["HP007"]
            pair_time = max(hp10["measured_at"], hp007["measured_at"])
            aggregate_dose = max(
                float(hp10["dose_msv"]),
                float(hp007["dose_msv"]),
            )

            if reading_type == "PERSONAL_DOSE":
                table = "historico_dose"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO historico_dose (
                        measurement_id, test_session_id,
                        hp10_measurement_id, hp007_measurement_id,
                        time_dos, dosimeter_id, hp10_dos, hp007_dos,
                        dose_dos, status_dos, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hp007["id"],
                        test_session_id,
                        hp10["id"],
                        hp007["id"],
                        pair_time,
                        measurement["dosimeter_id"],
                        hp10["dose_msv"],
                        hp007["dose_msv"],
                        aggregate_dose,
                        self._personal_dose_status(aggregate_dose),
                        utc_now(),
                    ),
                )
            else:
                table = "historico_branco"
                hp10_counts = float(hp10["raw_signal"])
                hp007_counts = float(hp007["raw_signal"])
                connection.execute(
                    """
                    INSERT OR IGNORE INTO historico_branco (
                        measurement_id, test_session_id,
                        hp10_measurement_id, hp007_measurement_id,
                        time_bg, dosimeter_id, hp10_counts, hp007_counts,
                        counts, status_bg, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hp007["id"],
                        test_session_id,
                        hp10["id"],
                        hp007["id"],
                        pair_time,
                        measurement["dosimeter_id"],
                        hp10_counts,
                        hp007_counts,
                        max(hp10_counts, hp007_counts),
                        BACKGROUND_STATUS,
                        utc_now(),
                    ),
                )
                connection.execute(
                    """
                    UPDATE dosimeters
                    SET bl_hp10 = ?, bl_hp007 = ?, updated_at = ?
                    WHERE dosimeter_id = ?
                    """,
                    (
                        hp10_counts,
                        hp007_counts,
                        utc_now(),
                        measurement["dosimeter_id"],
                    ),
                )
            row = connection.execute(
                f"SELECT * FROM {table} WHERE test_session_id = ?",
                (test_session_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_test_session_progress(
        self,
        test_session_id: str,
    ) -> dict[str, Any]:
        """Return the completed channels for one two-acquisition test."""
        clean_session_id = str(test_session_id).strip()
        if not clean_session_id:
            raise ValueError("test_session_id inválido")
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT dose_channel, id, status
                FROM measurements
                WHERE test_session_id = ?
                ORDER BY id
                """,
                (clean_session_id,),
            ).fetchall()
        completed = {
            row["dose_channel"]
            for row in rows
            if row["status"] == "CONCLUIDO"
            and row["dose_channel"] in VALID_DOSE_CHANNELS
        }
        return {
            "test_session_id": clean_session_id,
            "completed_channels": completed,
            "complete": completed == VALID_DOSE_CHANNELS,
            "measurements": [dict(row) for row in rows],
        }

    def add_personal_dose(
        self,
        dosimeter_id: str,
        *,
        hp10_dos: float | None = None,
        hp007_dos: float | None = None,
        dose_dos: float | None = None,
        time_dos: datetime | str | None = None,
        status_dos: str | None = None,
    ) -> int:
        """Store a used dosimeter reading in ``historico_dose``."""
        clean_id = normalize_dosimeter_id(dosimeter_id)
        if self.get_dosimeter(clean_id) is None:
            raise ValueError("Dosímetro não cadastrado")
        if hp10_dos is None and hp007_dos is None and dose_dos is not None:
            hp10_dos = dose_dos
            hp007_dos = dose_dos
        if hp10_dos is None or hp007_dos is None:
            raise ValueError("Informe Hp(10) e Hp(0,07)")
        hp10 = _non_negative_number(hp10_dos, "Hp(10)")
        hp007 = _non_negative_number(hp007_dos, "Hp(0,07)")
        aggregate_dose = max(hp10, hp007)
        expected_status = self._personal_dose_status(aggregate_dose)
        if status_dos is None:
            clean_status = expected_status
        else:
            clean_status = str(status_dos).strip()
            if clean_status not in VALID_PERSONAL_DOSE_STATUSES:
                valid = ", ".join(sorted(VALID_PERSONAL_DOSE_STATUSES))
                raise ValueError(f"status_dos deve ser uma destas tags: {valid}")
            if clean_status != expected_status:
                raise ValueError(
                    "status_dos não corresponde à dose informada; "
                    f"use '{expected_status}'"
                )
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO historico_dose (
                    test_session_id, time_dos, dosimeter_id,
                    hp10_dos, hp007_dos, dose_dos, status_dos, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"manual-dose-{uuid4().hex}",
                    normalize_datetime(time_dos),
                    clean_id,
                    hp10,
                    hp007,
                    aggregate_dose,
                    clean_status,
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
        hp10_counts: float | None = None,
        hp007_counts: float | None = None,
        counts: float | None = None,
        time_bg: datetime | str | None = None,
        status_bg: str = BACKGROUND_STATUS,
    ) -> int:
        """Store raw post-erasure counts and update the dosimeter BL."""
        clean_id = normalize_dosimeter_id(dosimeter_id)
        if self.get_dosimeter(clean_id) is None:
            raise ValueError("Dosímetro não cadastrado")
        clean_status = str(status_bg).strip()
        if clean_status.casefold() != BACKGROUND_STATUS.casefold():
            raise ValueError(f"status_bg deve ser '{BACKGROUND_STATUS}'")
        if hp10_counts is None and hp007_counts is None and counts is not None:
            hp10_counts = counts
            hp007_counts = counts
        if hp10_counts is None or hp007_counts is None:
            raise ValueError("Informe Hp(10) e Hp(0,07)")
        hp10 = _non_negative_number(hp10_counts, "Contagens Hp(10)")
        hp007 = _non_negative_number(hp007_counts, "Contagens Hp(0,07)")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO historico_branco (
                    test_session_id, time_bg, dosimeter_id,
                    hp10_counts, hp007_counts, counts, status_bg, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"manual-background-{uuid4().hex}",
                    normalize_datetime(time_bg),
                    clean_id,
                    hp10,
                    hp007,
                    max(hp10, hp007),
                    BACKGROUND_STATUS,
                    utc_now(),
                ),
            )
            connection.execute(
                """
                UPDATE dosimeters
                SET bl_hp10 = ?, bl_hp007 = ?, updated_at = ?
                WHERE dosimeter_id = ?
                """,
                (hp10, hp007, utc_now(), clean_id),
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
        dose_channel: str = "HP10",
    ) -> float:
        """Return the latest raw baseline counts or the configured default."""
        fallback = _non_negative_number(default, "BL padrão")
        record = self.get_latest_background(dosimeter_id, at_time=at_time)
        if record is None:
            return fallback
        channel = str(dose_channel).strip().upper()
        if channel not in VALID_DOSE_CHANNELS:
            raise ValueError("dose_channel deve ser HP10 ou HP007")
        field = "hp007_counts" if channel == "HP007" else "hp10_counts"
        value = record.get(field)
        return float(record["counts"] if value is None else value)

    def calculate_net_personal_dose(
        self,
        dosimeter_id: str,
        reader_id: str,
        *,
        raw_signal: float,
        measured_at: datetime | str | None = None,
        default_baseline: float = 0.0,
        dose_channel: str = "HP10",
    ) -> dict[str, float]:
        """Apply the registered calibration after subtracting raw BL counts."""
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
        signal = _non_negative_number(raw_signal, "Contagens brutas")
        baseline = self.get_background_value(
            dosimeter["dosimeter_id"],
            at_time=measurement_time,
            default=default_baseline,
            dose_channel=dose_channel,
        )
        channel = str(dose_channel).strip().upper()
        if channel not in VALID_DOSE_CHANNELS:
            raise ValueError("dose_channel deve ser HP10 ou HP007")
        ecc = float(
            dosimeter["ecc_hp007"]
            if channel == "HP007"
            else dosimeter["ecc_hp10"]
        )
        rcf = float(reader["rcf"])
        return {
            "dose_msv": max(0.0, signal - baseline) * rcf * ecc,
            "baseline_counts": baseline,
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

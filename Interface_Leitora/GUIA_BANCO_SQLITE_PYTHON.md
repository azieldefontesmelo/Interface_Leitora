# Especificação do banco SQLite para o novo projeto Python

## 1. Objetivo

Este documento deve ser levado para o novo projeto e usado como especificação
para criar o banco de dados em **Python + SQLite**, sem Java, MySQL, Electron ou
dependências deste projeto.

O sistema deve permitir cadastrar novos dosímetros. O cadastro deve ter um
único fator de calibração chamado `ECC`, conforme a tela `Novo dosímetro`.

No histórico de medições, os campos antigos de leitura `Hp(10)` e `Hp(0,07)`
devem ser substituídos pelos quatro valores exibidos na nova interface:

| Texto na interface | Coluna no SQLite | Tipo |
|---|---|---|
| `Count (0.1s)` | `count_01s` | `INTEGER` |
| `Current (mA)` | `current_ma` | `REAL` |
| `Light (mV)` | `light_mv` | `REAL` |
| `Dose (mSv)` | `dose_msv` | `REAL` |

Exemplo da imagem:

```text
Count (0.1s): 1733
Current (mA): 45
Light (mV):   471
Dose (mSv):   474246
```

Os números devem ser gravados exatamente como forem recebidos. O banco não deve
dividir, multiplicar ou trocar a unidade automaticamente.

## 2. Requisitos

- Usar somente módulos da biblioteca padrão do Python.
- Usar `sqlite3` para o banco.
- Criar o arquivo `data/measurements.sqlite3` automaticamente.
- Criar as tabelas automaticamente na primeira execução.
- Permitir cadastrar, consultar, atualizar e desativar dosímetros.
- Permitir cadastrar, consultar, atualizar e desativar leitoras.
- Validar o ID do dosímetro como código de barras de exatamente 10 dígitos.
- Guardar um único `ECC`, data inicial, data final e estado ativo no cadastro
  do dosímetro.
- Guardar `Reader`, `RCF`, data inicial, data final e estado ativo no cadastro
  da leitora.
- Tratar identificadores como texto para preservar zeros à esquerda.
- Usar comandos SQL parametrizados; nunca montar valores do usuário diretamente
  dentro do SQL.
- Salvar datas em UTC no formato ISO 8601.
- Permitir cadastrar, consultar, atualizar e excluir leituras.
- Permitir filtrar por equipamento e intervalo de datas.
- Permitir filtrar o histórico pelo ID do dosímetro.
- Permitir exportar o resultado para CSV.
- Ativar chaves estrangeiras, modo WAL e tempo de espera para banco ocupado.
- Não criar campos HP no cadastro ou no histórico novo.

## 3. Estrutura recomendada

```text
novo_projeto/
├── app.py
├── database.py
├── data/
│   └── measurements.sqlite3
└── exports/
```

O arquivo `.sqlite3` e os arquivos exportados normalmente não devem ser
versionados. Sugestão para o `.gitignore`:

```gitignore
data/*.sqlite3
data/*.sqlite3-shm
data/*.sqlite3-wal
exports/*.csv
backups/*.sqlite3
```

## 4. Modelo do banco

### Tabela `dosimeters`

Guarda os dosímetros cadastrados pela janela `Novo dosímetro`.

| Campo da interface | Coluna | Tipo e regra |
|---|---|---|
| `ID do dosímetro` | `dosimeter_id` | `TEXT`, chave primária, exatamente 10 dígitos |
| `ECC` | `ecc` | `REAL`, padrão `1.0`, maior que zero |
| `Data inicial` | `begin_date` | `TEXT`, data ISO `AAAA-MM-DD` |
| `Data final` | `end_date` | `TEXT`, data ISO `AAAA-MM-DD` ou `NULL` |
| `Ativo` | `active` | `INTEGER`, `1` ativo e `0` inativo |
| — | `created_at` | `TEXT`, data/hora UTC |
| — | `updated_at` | `TEXT`, data/hora UTC |

Regras do cadastro:

- `begin_date` é obrigatório;
- `end_date` pode ficar vazia; quando preenchida, não pode ser anterior a `begin_date`;
- o ID não pode se repetir;
- o ECC é um fator de calibração e inicialmente pode valer `1.0`;
- a interface pode mostrar `1,0000`, mas o Python deve gravar `1.0`;
- um dosímetro com histórico não deve ser apagado: deve ser desativado;
- uma medição só pode ser associada a um dosímetro previamente cadastrado e
  ativo.

### Tabela `readers`

Guarda as leitoras cadastradas. O `reader_id` é texto e pode conter letras,
números e zeros à esquerda.

| Campo da interface | Coluna | Tipo e regra |
|---|---|---|
| `Reader` | `reader_id` | `TEXT`, chave primária |
| `RCF` | `rcf` | `REAL`, padrão `1.0`, maior que zero |
| `Active` | `active` | `INTEGER`, `1` ativo e `0` inativo |
| `Begin Date` | `begin_date` | `TEXT`, data ISO `AAAA-MM-DD` |
| `End Date` | `end_date` | `TEXT`, opcional |
| — | `created_at` | `TEXT`, data/hora UTC |
| — | `updated_at` | `TEXT`, data/hora UTC |

Regras do cadastro:

- `reader_id` é obrigatório e não pode se repetir;
- `RCF` é um único fator e deve ser maior que zero;
- `begin_date` é obrigatória;
- `end_date` pode ficar vazia, representando validade sem data final;
- quando preenchida, `end_date` não pode ser anterior a `begin_date`;
- uma leitora com histórico deve ser desativada em vez de apagada;
- uma medição só pode usar uma leitora previamente cadastrada, ativa e dentro
  do período de validade.

### Tabela `measurements`

Guarda o histórico. Cada linha representa um conjunto completo dos quatro
valores da tela.

| Coluna | Tipo | Regra |
|---|---|---|
| `id` | `INTEGER` | chave primária automática |
| `measured_at` | `TEXT` | data/hora UTC |
| `reader_id` | `TEXT` | equipamento que realizou a leitura |
| `dosimeter_id` | `TEXT` | dosímetro cadastrado que foi medido |
| `count_01s` | `INTEGER` | `Count (0.1s)`, maior ou igual a zero |
| `current_ma` | `REAL` | `Current (mA)`, maior ou igual a zero |
| `light_mv` | `REAL` | `Light (mV)`, maior ou igual a zero |
| `dose_msv` | `REAL` | `Dose (mSv)`, maior ou igual a zero |
| `status` | `TEXT` | padrão `OK` |
| `notes` | `TEXT` | observação opcional |
| `created_at` | `TEXT` | data/hora UTC de inclusão |
| `updated_at` | `TEXT` | última alteração em UTC |

Relacionamento:

```text
readers (1) ──────────────── (N) measurements (N) ──────────────── (1) dosimeters
 reader_id                        reader_id       dosimeter_id          dosimeter_id
```

## 5. Implementação completa de `database.py`

Copiar o código abaixo para o novo projeto:

```python
from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "measurements.sqlite3"


SCHEMA = """
CREATE TABLE IF NOT EXISTS dosimeters (
    dosimeter_id TEXT PRIMARY KEY
                 CHECK (
                     length(dosimeter_id) = 10
                     AND dosimeter_id NOT GLOB '*[^0-9]*'
                 ),
    ecc          REAL NOT NULL DEFAULT 1.0 CHECK (ecc > 0),
    begin_date   TEXT NOT NULL,
    end_date     TEXT,
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    CHECK (end_date IS NULL OR end_date >= begin_date)
);

CREATE TABLE IF NOT EXISTS readers (
    reader_id  TEXT PRIMARY KEY CHECK (length(trim(reader_id)) > 0),
    rcf        REAL NOT NULL DEFAULT 1.0 CHECK (rcf > 0),
    active     INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    begin_date TEXT NOT NULL,
    end_date   TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (end_date IS NULL OR end_date >= begin_date)
);

CREATE TABLE IF NOT EXISTS measurements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    measured_at TEXT NOT NULL,
    reader_id   TEXT NOT NULL,
    dosimeter_id TEXT NOT NULL,
    count_01s   INTEGER NOT NULL CHECK (count_01s >= 0),
    current_ma  REAL NOT NULL CHECK (current_ma >= 0),
    light_mv    REAL NOT NULL CHECK (light_mv >= 0),
    dose_msv    REAL NOT NULL CHECK (dose_msv >= 0),
    status      TEXT NOT NULL DEFAULT 'OK',
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_measurements_reader_date
    ON measurements(reader_id, measured_at);

CREATE INDEX IF NOT EXISTS idx_measurements_dosimeter_date
    ON measurements(dosimeter_id, measured_at);
"""


def utc_now() -> str:
    """Retorna data/hora UTC no formato ISO 8601."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def normalize_datetime(value: datetime | str | None) -> str:
    if value is None:
        return utc_now()
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def normalize_date(value: date | str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(value).isoformat()


def normalize_dosimeter_id(value: str) -> str:
    clean_id = value.strip()
    if len(clean_id) != 10 or not clean_id.isdigit():
        raise ValueError(
            "dosimeter_id deve ser um código de barras com exatamente 10 dígitos"
        )
    return clean_id


def normalize_reader_id(value: str) -> str:
    clean_id = value.strip()
    if not clean_id:
        raise ValueError("reader_id não pode ficar vazio")
    if len(clean_id) > 64:
        raise ValueError("reader_id deve ter no máximo 64 caracteres")
    return clean_id


class Database:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.create_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
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
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)

    def register_dosimeter(
        self,
        dosimeter_id: str,
        *,
        ecc: float = 1.0,
        begin_date: date | str,
        end_date: date | str | None = None,
        active: bool = True,
    ) -> None:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        if ecc <= 0:
            raise ValueError("ECC deve ser maior que zero")

        begin = normalize_date(begin_date)
        end = normalize_date(end_date) if end_date not in (None, "") else None
        if end is not None and end < begin:
            raise ValueError("a data final não pode ser anterior à data inicial")

        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO dosimeters (
                    dosimeter_id, ecc,
                    begin_date, end_date, active,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_id,
                    float(ecc),
                    begin,
                    end,
                    int(active),
                    now,
                    now,
                ),
            )

    def get_dosimeter(
        self,
        dosimeter_id: str,
    ) -> dict[str, Any] | None:
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
            parameters.append(int(active))

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM dosimeters
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
        begin_date: date | str,
        end_date: date | str | None = None,
        active: bool,
    ) -> bool:
        clean_id = normalize_dosimeter_id(dosimeter_id)
        if ecc <= 0:
            raise ValueError("ECC deve ser maior que zero")

        begin = normalize_date(begin_date)
        end = normalize_date(end_date) if end_date not in (None, "") else None
        if end is not None and end < begin:
            raise ValueError("a data final não pode ser anterior à data inicial")

        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE dosimeters
                SET ecc = ?,
                    begin_date = ?,
                    end_date = ?,
                    active = ?,
                    updated_at = ?
                WHERE dosimeter_id = ?
                """,
                (
                    float(ecc),
                    begin,
                    end,
                    int(active),
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
                (int(active), utc_now(), clean_id),
            )
            return cursor.rowcount == 1

    def delete_dosimeter(self, dosimeter_id: str) -> bool:
        """Exclui apenas dosímetros sem histórico de medições."""
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
        begin_date: date | str,
        end_date: date | str | None = None,
        active: bool = True,
    ) -> None:
        clean_id = normalize_reader_id(reader_id)
        if rcf <= 0:
            raise ValueError("RCF deve ser maior que zero")

        begin = normalize_date(begin_date)
        end = normalize_date(end_date) if end_date is not None else None
        if end is not None and end < begin:
            raise ValueError("a data final não pode ser anterior à data inicial")

        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO readers (
                    reader_id, rcf, active, begin_date, end_date,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_id,
                    float(rcf),
                    int(active),
                    begin,
                    end,
                    now,
                    now,
                ),
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
            parameters.append(int(active))

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM readers
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
        begin_date: date | str,
        end_date: date | str | None,
        active: bool,
    ) -> bool:
        clean_id = normalize_reader_id(reader_id)
        if rcf <= 0:
            raise ValueError("RCF deve ser maior que zero")

        begin = normalize_date(begin_date)
        end = normalize_date(end_date) if end_date is not None else None
        if end is not None and end < begin:
            raise ValueError("a data final não pode ser anterior à data inicial")

        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE readers
                SET rcf = ?,
                    active = ?,
                    begin_date = ?,
                    end_date = ?,
                    updated_at = ?
                WHERE reader_id = ?
                """,
                (
                    float(rcf),
                    int(active),
                    begin,
                    end,
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
                (int(active), utc_now(), clean_id),
            )
            return cursor.rowcount == 1

    def delete_reader(self, reader_id: str) -> bool:
        """Exclui apenas leitoras sem histórico de medições."""
        clean_id = normalize_reader_id(reader_id)
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM readers WHERE reader_id = ?",
                (clean_id,),
            )
            return cursor.rowcount == 1

    def add_measurement(
        self,
        reader_id: str,
        dosimeter_id: str,
        *,
        count_01s: int,
        current_ma: float,
        light_mv: float,
        dose_msv: float,
        measured_at: datetime | str | None = None,
        status: str = "OK",
        notes: str | None = None,
    ) -> int:
        if isinstance(count_01s, bool) or not isinstance(count_01s, int):
            raise TypeError("count_01s deve ser um número inteiro")
        values = (count_01s, current_ma, light_mv, dose_msv)
        if any(value < 0 for value in values):
            raise ValueError("os valores da leitura não podem ser negativos")

        clean_reader_id = normalize_reader_id(reader_id)
        clean_dosimeter_id = normalize_dosimeter_id(dosimeter_id)
        measurement_time = normalize_datetime(measured_at)
        measurement_date = measurement_time[:10]
        now = utc_now()
        with self.connect() as connection:
            reader = connection.execute(
                """
                SELECT active, begin_date, end_date
                FROM readers
                WHERE reader_id = ?
                """,
                (clean_reader_id,),
            ).fetchone()
            if reader is None:
                raise ValueError("leitora não cadastrada")
            if not reader["active"]:
                raise ValueError("leitora inativa")
            if measurement_date < reader["begin_date"]:
                raise ValueError("leitora fora do período de validade")
            if (
                reader["end_date"] is not None
                and measurement_date > reader["end_date"]
            ):
                raise ValueError("leitora fora do período de validade")

            dosimeter = connection.execute(
                """
                SELECT active, begin_date, end_date
                FROM dosimeters
                WHERE dosimeter_id = ?
                """,
                (clean_dosimeter_id,),
            ).fetchone()
            if dosimeter is None:
                raise ValueError("dosímetro não cadastrado")
            if not dosimeter["active"]:
                raise ValueError("dosímetro inativo")
            if dosimeter["begin_date"] > measurement_date or (
                dosimeter["end_date"] is not None
                and measurement_date > dosimeter["end_date"]
            ):
                raise ValueError("dosímetro fora do período de validade")

            cursor = connection.execute(
                """
                INSERT INTO measurements (
                    measured_at, reader_id, dosimeter_id,
                    count_01s, current_ma,
                    light_mv, dose_msv, status, notes,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    measurement_time,
                    clean_reader_id,
                    clean_dosimeter_id,
                    count_01s,
                    float(current_ma),
                    float(light_mv),
                    float(dose_msv),
                    status.strip() or "OK",
                    notes,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def get_measurement(self, measurement_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM measurements WHERE id = ?",
                (measurement_id,),
            ).fetchone()
        return dict(row) if row else None

    def search_measurements(
        self,
        *,
        reader_id: str | None = None,
        dosimeter_id: str | None = None,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 10_000:
            raise ValueError("limit deve estar entre 1 e 10000")

        clauses: list[str] = []
        parameters: list[Any] = []

        if reader_id:
            clauses.append("reader_id = ?")
            parameters.append(normalize_reader_id(reader_id))
        if dosimeter_id:
            clauses.append("dosimeter_id = ?")
            parameters.append(normalize_dosimeter_id(dosimeter_id))
        if date_from:
            clauses.append("measured_at >= ?")
            parameters.append(normalize_datetime(date_from))
        if date_to:
            clauses.append("measured_at <= ?")
            parameters.append(normalize_datetime(date_to))

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT *
            FROM measurements
            {where}
            ORDER BY measured_at DESC, id DESC
            LIMIT ?
        """
        parameters.append(limit)

        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    def update_measurement(
        self,
        measurement_id: int,
        **changes: Any,
    ) -> bool:
        allowed_fields = {
            "measured_at",
            "reader_id",
            "dosimeter_id",
            "count_01s",
            "current_ma",
            "light_mv",
            "dose_msv",
            "status",
            "notes",
        }
        unknown = set(changes) - allowed_fields
        if unknown:
            raise ValueError(f"campos inválidos: {sorted(unknown)}")
        if not changes:
            return False

        if "measured_at" in changes:
            changes["measured_at"] = normalize_datetime(changes["measured_at"])
        if "dosimeter_id" in changes:
            changes["dosimeter_id"] = normalize_dosimeter_id(
                changes["dosimeter_id"]
            )
        if "reader_id" in changes:
            changes["reader_id"] = normalize_reader_id(changes["reader_id"])
        if "count_01s" in changes:
            count = changes["count_01s"]
            if isinstance(count, bool) or not isinstance(count, int):
                raise TypeError("count_01s deve ser um número inteiro")
        numeric_fields = ("count_01s", "current_ma", "light_mv", "dose_msv")
        if any(
            field in changes and changes[field] < 0
            for field in numeric_fields
        ):
            raise ValueError("os valores da leitura não podem ser negativos")

        changes["updated_at"] = utc_now()
        assignments = ", ".join(f"{field} = ?" for field in changes)
        parameters = [*changes.values(), measurement_id]

        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE measurements SET {assignments} WHERE id = ?",
                parameters,
            )
            return cursor.rowcount == 1

    def delete_measurement(self, measurement_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM measurements WHERE id = ?",
                (measurement_id,),
            )
            return cursor.rowcount == 1

    def export_csv(
        self,
        destination: str | Path,
        rows: list[dict[str, Any]] | None = None,
    ) -> Path:
        data = rows if rows is not None else self.search_measurements()
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        columns = [
            "id",
            "measured_at",
            "reader_id",
            "dosimeter_id",
            "count_01s",
            "current_ma",
            "light_mv",
            "dose_msv",
            "status",
            "notes",
        ]
        with output.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=columns,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(data)
        return output

    def backup(self, destination: str | Path) -> Path:
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(self.db_path)
        target = sqlite3.connect(output)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return output
```

## 6. Exemplo de uso

```python
import sqlite3

from database import Database


db = Database()

# Cadastro feito pela janela "Novo dosímetro".
try:
    db.register_dosimeter(
        "8570310483",
        ecc=1.0,
        begin_date="2026-07-30",
        end_date="2030-12-31",
        active=True,
    )
except sqlite3.IntegrityError as error:
    print(f"Dosímetro já cadastrado ou inválido: {error}")

# Deve ser executado somente uma vez para cada leitora.
try:
    db.register_reader(
        "3001A01",
        rcf=1.0,
        begin_date="2026-07-29",
        end_date=None,
        active=True,
    )
except sqlite3.IntegrityError as error:
    print(f"Leitora já cadastrada ou inválida: {error}")

measurement_id = db.add_measurement(
    "3001A01",
    "8570310483",
    count_01s=1733,
    current_ma=45,
    light_mv=471,
    dose_msv=474246,
    status="OK",
)

print(db.get_measurement(measurement_id))

rows = db.search_measurements(reader_id="3001A01")
db.export_csv("exports/measurements.csv", rows)
db.backup("backups/measurements-backup.sqlite3")
```

O resultado esperado da leitura é equivalente a:

```python
{
    "reader_id": "3001A01",
    "dosimeter_id": "8570310483",
    "count_01s": 1733,
    "current_ma": 45.0,
    "light_mv": 471.0,
    "dose_msv": 474246.0,
    "status": "OK",
}
```

O dicionário real também terá `id`, datas e `notes`.

## 7. Uso na interface

### Janela `Novo dosímetro`

Os campos devem ser ligados ao método `register_dosimeter()` sem alterar os
nomes internos definidos nesta especificação:

```python
dosimeter_form_to_database = {
    "ID do dosímetro": "dosimeter_id",
    "ECC": "ecc",
    "Data inicial": "begin_date",
    "Data final": "end_date",
    "Ativo": "active",
}
```

Exemplo do botão `Salvar`:

```python
db.register_dosimeter(
    dosimeter_id=id_field.strip(),
    ecc=float(ecc_field.replace(",", ".")),
    begin_date=begin_date_iso,
    end_date=end_date_iso,
    active=active_switch,
)
```

A interface pode receber datas como `dd/mm/aaaa`, mas antes de chamar o banco
deve convertê-las para `aaaa-mm-dd`. Se o ID já existir, `sqlite3` lançará
`IntegrityError`; a interface deve informar `Dosímetro já cadastrado`.

### Cadastro da leitora

O formulário da leitora deve usar este mapeamento:

```python
reader_form_to_database = {
    "Reader": "reader_id",
    "RCF": "rcf",
    "Active": "active",
    "Begin Date": "begin_date",
    "End Date": "end_date",
}
```

Exemplo do botão `Salvar`:

```python
db.register_reader(
    reader_id=reader_id_field.strip(),
    rcf=float(rcf_field.replace(",", ".")),
    active=active_switch,
    begin_date=begin_date_iso,
    end_date=end_date_iso or None,
)
```

O valor mostrado como `1.0000000` deve ser gravado como número `1.0`. A data
final vazia deve ser enviada como `None`, não como texto vazio.

Se o `reader_id` já existir, a interface deve informar
`Leitora já cadastrada`. Para edição, usar `update_reader()`; para retirar a
leitora de uso sem perder o histórico, usar `set_reader_active()`.

### Histórico de medições

Os textos da interface podem continuar com espaços, parênteses e unidades. Os
nomes internos do Python e do SQLite devem ficar sem espaços:

```python
interface_to_database = {
    "Count (0.1s)": "count_01s",
    "Current (mA)": "current_ma",
    "Light (mV)": "light_mv",
    "Dose (mSv)": "dose_msv",
}
```

Ao receber uma amostra completa do equipamento:

```python
db.add_measurement(
    reader_id=current_reader_id,
    dosimeter_id=current_dosimeter_id,
    count_01s=int(count_value),
    current_ma=float(current_value),
    light_mv=float(light_value),
    dose_msv=float(dose_value),
)
```

Não gravar uma linha separada para cada cartão da tela. Os quatro valores
pertencem à mesma leitura e devem ficar na mesma linha.

## 8. Datas e filtros

O banco salva UTC. Para buscar um dia inteiro, informe o início e o fim com
fuso horário:

```python
rows = db.search_measurements(
    reader_id="3001A01",
    dosimeter_id="8570310483",
    date_from="2026-07-30T00:00:00-03:00",
    date_to="2026-07-30T23:59:59.999-03:00",
)
```

Para mostrar a data no horário local, converta somente na interface. Não altere
o valor persistido no banco.

## 9. Migração do banco antigo

O banco novo possui somente um `ECC`. Se o banco antigo tiver dois fatores ECC,
eles não devem ser combinados por média ou renomeados automaticamente. A
migração precisa usar uma regra de conversão validada pelo responsável técnico.

Somente os resultados antigos de medição `Hp(10)` e `Hp(0,07)` não têm
correspondência automática com `Count`, `Current`, `Light` e `Dose`. Não
renomear duas colunas antigas e inventar valores para as outras duas.

Se for necessário importar dados antigos, definir antes uma fórmula ou regra
de conversão validada pelo responsável técnico. Sem essa regra, manter o banco
antigo apenas como histórico e iniciar o novo banco vazio.

## 10. Critérios de aceite

O banco estará pronto quando todos estes itens passarem:

1. A primeira execução cria `data/measurements.sqlite3`.
2. As tabelas `dosimeters`, `readers` e `measurements` são criadas sem
   intervenção manual.
3. O dosímetro `8570310483` pode ser cadastrado com um ECC, datas e estado
   ativo.
4. IDs que não tenham exatamente 10 dígitos são rejeitados.
5. Um ID de dosímetro repetido é rejeitado.
6. O cadastro contém somente um campo chamado `ECC`.
7. A leitora `3001A01` pode ser cadastrada com `RCF`, datas e estado ativo.
8. Um `reader_id` repetido ou um `RCF` menor ou igual a zero é rejeitado.
9. É possível atualizar e desativar uma leitora sem apagar seu histórico.
10. O exemplo `1733`, `45`, `471`, `474246` pode ser gravado e lido sem mudança.
11. Reiniciar o programa não apaga os registros.
12. É possível pesquisar por leitora, dosímetro e intervalo de datas.
13. É possível atualizar e excluir uma leitura pelo `id`.
14. A exportação CSV contém as quatro novas grandezas e suas unidades são
   conhecidas pela interface.
15. O esquema novo não contém campos de `Hp(10)` ou `Hp(0,07)`.
16. Dosímetro inativo, não cadastrado ou fora da validade não aceita medição.
17. Leitora inativa, não cadastrada ou fora da validade não aceita medição.
18. Erros durante uma gravação causam `rollback`, sem deixar registros parciais.

## 11. Observações importantes

- `sqlite3` já acompanha o Python; não é necessário instalar um servidor de
  banco ou pacote via `pip`.
- SQLite permite várias leituras simultâneas, mas apenas uma escrita por vez.
  Para uma aplicação local isso normalmente é suficiente.
- Não compartilhar o arquivo `.sqlite3` diretamente por pasta de rede enquanto
  estiver aberto.
- Fazer backup com o método `backup()`, não apenas copiar o arquivo durante uma
  gravação.
- Se a aplicação receber vírgula decimal da interface, converter antes de
  gravar: `float(texto.replace(",", "."))`.
- Se futuramente for necessário guardar a unidade configurável, criar uma nova
  versão do esquema. Neste modelo, as unidades são fixas: `0.1s`, `mA`, `mV` e
  `mSv`.

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path


INVALID_WINDOWS_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def scanner_text(value: str) -> str:
    """Remove scanner framing whitespace/control characters, preserving digits."""
    return "".join(
        character
        for character in str(value)
        if not character.isspace() and ord(character) >= 32
    )


def safe_test_filename(value: str) -> str:
    name = str(value).strip()
    if not name:
        raise ValueError("Digite um nome para o arquivo")
    if Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("O nome do arquivo não pode conter um caminho")
    if "/" in name or "\\" in name or INVALID_WINDOWS_FILENAME.search(name):
        raise ValueError("O nome do arquivo contém caracteres inválidos")
    if name.endswith((" ", ".")):
        raise ValueError("O nome do arquivo não pode terminar em espaço ou ponto")
    if not name.lower().endswith(".txt"):
        name += ".txt"
    stem = Path(name).stem.upper()
    if stem in WINDOWS_RESERVED_NAMES:
        raise ValueError("O nome do arquivo é reservado pelo sistema")
    if len(name) > 240:
        raise ValueError("O nome do arquivo é muito longo")
    return name


def dosimeter_filename(
    dosimeter_id: str,
    moment: datetime | None = None,
    *,
    dose_channel: str | None = None,
    reading_type: str | None = None,
) -> str:
    moment = moment or datetime.now()
    suffixes = []
    if reading_type:
        suffixes.append("linha-base" if reading_type == "BACKGROUND" else "integral")
    if dose_channel:
        suffixes.append(str(dose_channel).strip().lower())
    suffix = f"_{'_'.join(suffixes)}" if suffixes else ""
    return safe_test_filename(
        f"{dosimeter_id}{suffix}_"
        f"{moment.strftime('%Y-%m-%d_%H-%M-%S-%f')}.txt"
    )


def parse_number(value: str | float | int, field_name: str, *, positive: bool) -> float:
    try:
        number = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} deve ser numérico") from error
    if not math.isfinite(number):
        raise ValueError(f"{field_name} deve ser finito")
    if positive and number <= 0:
        raise ValueError(f"{field_name} deve ser maior que zero")
    if not positive and number < 0:
        raise ValueError(f"{field_name} não pode ser negativo")
    return number


def calculate_dose(
    total: float,
    *,
    baseline: float,
    rcf: float,
    ecc: float,
    fang: float,
    fenerg: float,
) -> float:
    return max(0.0, (total - baseline) * rcf * ecc * fang * fenerg)

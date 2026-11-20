import json
from pathlib import Path

from pensionpal.core.config import settings
from pensionpal.schemas import EPFORecord

DATA_FILE = Path(settings.data_file)


def get_all_records() -> list[EPFORecord]:
    with DATA_FILE.open("r", encoding="utf-8") as file:
        records_data = json.load(file)

    return [EPFORecord.model_validate(record) for record in records_data]

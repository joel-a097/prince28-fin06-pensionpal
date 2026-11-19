from pydantic import BaseModel


class EPFORecord(BaseModel):
    id: str
    doc_type: str
    number: str
    date: str
    topic: str
    condition: str
    form: str
    effective_from: str

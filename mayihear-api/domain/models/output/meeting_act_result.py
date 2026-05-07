from pydantic import BaseModel, field_validator
from typing import List, Optional

from domain.models.output.token_usage import TokenUsage


class TopicItem(BaseModel):
    titulo: str
    avances: List[str] = []
    bloqueantes: List[str] = []
    aprendizajes: List[str] = []


class AcuerdoItem(BaseModel):
    accion: Optional[str] = None
    responsable: Optional[str] = None


class MeetingActResult(BaseModel):
    nombre_reunion: str = ""
    fecha: str = ""
    participantes: List[str] = []
    resumen_ejecutivo: str = ""
    temas: List[TopicItem] = []
    acuerdos: List[AcuerdoItem] = []
    riesgos: List[str] = []
    pendientes_reunion_anterior: List[str] = []
    proxima_reunion: Optional[str] = None
    is_freeform: bool = False
    free_form_text: Optional[str] = None
    usage: Optional[TokenUsage] = None
    processing_time_seconds: Optional[float] = None

    @field_validator('acuerdos', mode='before')
    @classmethod
    def filter_empty_acuerdos(cls, v):
        if isinstance(v, list):
            return [a for a in v if isinstance(a, dict) and a.get('accion')]
        return v

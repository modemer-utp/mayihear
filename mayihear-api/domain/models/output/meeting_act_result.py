from pydantic import BaseModel
from typing import List, Optional

from domain.models.output.token_usage import TokenUsage


class TopicItem(BaseModel):
    titulo: str
    avances: List[str] = []
    bloqueantes: List[str] = []
    aprendizajes: List[str] = []


class AcuerdoItem(BaseModel):
    accion: str
    responsable: Optional[str] = None


class MeetingActResult(BaseModel):
    nombre_reunion: str
    fecha: str
    participantes: List[str] = []
    resumen_ejecutivo: str
    temas: List[TopicItem] = []
    acuerdos: List[AcuerdoItem] = []
    riesgos: List[str] = []
    pendientes_reunion_anterior: List[str] = []
    proxima_reunion: Optional[str] = None
    usage: Optional[TokenUsage] = None
    processing_time_seconds: Optional[float] = None

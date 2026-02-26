from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from application.handlers.generate_word import build_word_document
from application.services.meeting_act_service import MeetingActService
from domain.models.input.meeting_act_request import MeetingActRequest
from domain.models.output.meeting_act_result import MeetingActResult

router = APIRouter(prefix="/meeting-act", tags=["meeting-act"])
service = MeetingActService()

WORD_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.post("/generate", response_model=MeetingActResult)
async def generate_meeting_act(request: MeetingActRequest):
    return service.generate(request)


@router.post("/word")
async def generate_word(act: MeetingActResult):
    buffer = build_word_document(act)
    filename = f"acta_{act.fecha.replace('/', '-')}.docx" if act.fecha else "acta.docx"
    return StreamingResponse(
        buffer,
        media_type=WORD_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

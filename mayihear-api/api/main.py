from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.controllers import (
    transcription_controller, insights_controller,
    meeting_act_controller, monday_controller, settings_controller,
    chat_controller, profiles_controller
)
from infrastructure.database import init_db
from infrastructure.utilities import usage_logger


def create_app() -> FastAPI:
    init_db()

    app = FastAPI(
        title="MayiHear API",
        version="0.2.0",
        description="Meeting transcription and insights — UTP desktop"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"]
    )

    app.include_router(transcription_controller.router)
    app.include_router(insights_controller.router)
    app.include_router(meeting_act_controller.router)
    app.include_router(monday_controller.router)
    app.include_router(settings_controller.router)
    app.include_router(chat_controller.router)
    app.include_router(profiles_controller.router)

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok"}

    @app.get("/usage", tags=["usage"])
    def get_usage():
        return usage_logger.read_all()

    return app


app = create_app()

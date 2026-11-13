import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.agent.service import AgentService
from backend.api.operations import OperationManager
from backend.api.routes import build_router
from backend.core.errors import ApplicationError
from backend.copart.service import CopartService, create_copart_service


logger = logging.getLogger(__name__)


def create_app(
    copart_service: CopartService | None = None,
    agent_service: AgentService | None = None,
    operation_manager: OperationManager | None = None,
) -> FastAPI:
    load_dotenv()
    if copart_service is None:
        copart_service = create_copart_service()
    agent_service = agent_service or AgentService(copart_service)
    operation_manager = operation_manager or OperationManager()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await operation_manager.shutdown()

    app = FastAPI(
        title="Copart Vehicle Assistant API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.copart_service = copart_service
    app.state.agent_service = agent_service
    app.state.operation_manager = operation_manager

    origins = [
        origin.strip()
        for origin in os.getenv(
            "FRONTEND_ORIGINS",
            "http://localhost:3000,http://localhost:5173",
        ).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        _ = request
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.public_data(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        _ = request
        return JSONResponse(
            status_code=422,
            content={
                "code": "INVALID_REQUEST",
                "message": "The request body is invalid.",
                "retryable": False,
                "details": {"errors": exc.errors()},
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("Unhandled API error on %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "code": "INTERNAL_ERROR",
                "message": "The request could not be completed. Please try again.",
                "retryable": True,
            },
        )

    app.include_router(build_router(agent_service, operation_manager))
    return app

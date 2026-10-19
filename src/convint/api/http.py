"""HTTP transport. A thin wrapper over TurnEngine - all logic lives in the app
layer, so this file and the MCP one stay interchangeable."""

from __future__ import annotations

from .contract import CONTRACT_VERSION, TurnRequest, TurnResponse


def build_app(engine=None):
    """`engine=None` builds the server-configured engine (CONVINT_ASSESSOR /
    CONVINT_MODEL, see app/engine_factory.py)."""
    from fastapi import FastAPI, HTTPException

    from ..app.engine_factory import build_engine

    engine = engine or build_engine()
    app = FastAPI(title="convint", version=CONTRACT_VERSION)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "contract_version": CONTRACT_VERSION}

    @app.get("/v1/contract")
    def contract() -> dict:
        """Consumers fetch the schema they are pinned against."""
        return {
            "contract_version": CONTRACT_VERSION,
            "request": TurnRequest.model_json_schema(),
            "response": TurnResponse.model_json_schema(),
        }

    @app.post("/v1/turn", response_model=TurnResponse)
    def turn(request: TurnRequest) -> TurnResponse:
        major = request.contract_version.split(".")[0]
        if major != CONTRACT_VERSION.split(".")[0]:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"contract major version mismatch: client {request.contract_version}, "
                    f"server {CONTRACT_VERSION}"
                ),
            )
        return engine.run(request)

    return app


def serve(host: str = "127.0.0.1", port: int = 8000, engine=None, *,
          assessor: str | None = None, model: str | None = None) -> None:  # pragma: no cover
    import uvicorn

    from ..app.engine_factory import build_engine

    engine = engine or build_engine(assessor=assessor, model=model)
    uvicorn.run(build_app(engine), host=host, port=port)

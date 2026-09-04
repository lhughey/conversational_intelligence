"""HTTP transport. A thin wrapper over TurnEngine - all logic lives in the app
layer, so this file and the MCP one stay interchangeable."""

from __future__ import annotations

from .contract import CONTRACT_VERSION, TurnRequest, TurnResponse


def build_app(engine=None):
    from fastapi import FastAPI, HTTPException

    from ..app.turn_engine import TurnEngine

    engine = engine or TurnEngine()
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


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run(build_app(), host=host, port=port)

import contextlib
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from .send_email import send_email_via_smtp
from .therapist_search import therapist_search


mcp = FastMCP(
    "mh-skills-mcp",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


@mcp.tool()
def therapist_search_tool(
    location_text: str,
    radius_km: float = 5,
    specialty: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    normalized_specialty = specialty.strip() if isinstance(specialty, str) else None
    if normalized_specialty == "":
        normalized_specialty = None
    return therapist_search(
        location_text=location_text,
        radius_km=max(1.0, min(radius_km, 50.0)),
        specialty=normalized_specialty,
        limit=max(1, min(limit, 20)),
        nominatim_base_url=os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"),
        overpass_base_url=os.getenv("OVERPASS_BASE_URL", "https://overpass-api.de"),
        user_agent=os.getenv("THERAPIST_SEARCH_USER_AGENT", "mh-skills-coach-mcp/0.1"),
    )


@mcp.tool()
def send_email_tool(
    to: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
) -> dict[str, str | None]:
    message_id = send_email_via_smtp(
        to=to,
        subject=subject,
        body=body,
        reply_to=reply_to,
    )
    return {"message_id": message_id}


async def health(_: Request) -> Response:
    return JSONResponse({"status": "ok", "server": "mh-skills-mcp"})


@contextlib.asynccontextmanager
async def lifespan(_: Starlette):
    async with mcp.session_manager.run():
        yield


app = Starlette(
    routes=[
        Route("/health", endpoint=health, methods=["GET"]),
        Mount("/mcp", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)

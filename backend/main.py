from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.auth import require_api_key
from backend.config import get_settings

from backend.routers import athletes, snapshots, posts, zoomph, web_analytics, trueblue, reports, brand, ambassadors, network_screen, campus_channels, applications

# The interactive docs and OpenAPI schema expose the full route map and auth
# model, so they are served outside production only.
_public_docs = get_settings().environment != "production"
app = FastAPI(
    title="NILTV Dashboard API",
    version="1.0.0",
    docs_url="/docs" if _public_docs else None,
    redoc_url="/redoc" if _public_docs else None,
    openapi_url="/openapi.json" if _public_docs else None,
)

# The public signup form on niltv.com posts to /api/applications/ from the
# browser, so the site origins are allowed too. Every other route still needs
# X-API-Key, which the site never has.
_public_origins = [o.strip() for o in get_settings().public_cors_origins.split(",") if o.strip()]
# Outside production a developer's Next.js dev server (localhost:3000) and the
# dev Amplify branch may call the API directly from the browser.
_dev_origins = [] if get_settings().is_production else [
    "http://localhost:3000", "http://127.0.0.1:3000",
    "https://dashboard-dev.niltv.com", "https://dashboard-dev.truebluetv.com",
]
# The dashboard moved to dashboard.niltv.com; the truebluetv.com host stays
# listed until it is retired.
_dashboard_origins = ["https://dashboard.niltv.com", "https://dashboard.truebluetv.com"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[*_dashboard_origins, *_public_origins, *_dev_origins],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(athletes.router, prefix="/api/athletes", tags=["athletes"])
app.include_router(snapshots.router, prefix="/api/snapshots", tags=["snapshots"])
app.include_router(posts.router, prefix="/api/posts", tags=["posts"])
app.include_router(zoomph.router, prefix="/api/zoomph", tags=["zoomph"])
app.include_router(web_analytics.router, prefix="/api/web-analytics", tags=["web-analytics"])
app.include_router(trueblue.router, prefix="/api/trueblue", tags=["trueblue"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(brand.router, prefix="/api/brand", tags=["brand"])
app.include_router(ambassadors.router, prefix="/api/ambassadors", tags=["ambassadors"])
app.include_router(network_screen.router, prefix="/api/network-screen", tags=["network-screen"])
app.include_router(campus_channels.router, prefix="/api/campus-channels", tags=["campus-channels"])
# Public first: /webhooks/... must win over the admin /{application_id} routes.
app.include_router(applications.public_router, prefix="/api/applications", tags=["applications"])
app.include_router(applications.router, prefix="/api/applications", tags=["applications"])


@app.get("/api/health")
def health():
    s = get_settings()
    return {"status": "ok", "environment": s.environment, "auth": "disabled" if s.auth_disabled else "api-key"}


@app.get("/api/health/auth", dependencies=[Depends(require_api_key)])
def health_auth():
    """Same as /api/health but behind the key. The dashboard's own /api/health
    calls this with the key baked into its build, so a deploy whose key does
    not match this service shows up as unhealthy instead of as a 500 on every
    page."""
    return {"status": "ok", "environment": get_settings().environment, "auth": "ok"}

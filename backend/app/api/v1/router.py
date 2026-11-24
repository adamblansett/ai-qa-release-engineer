from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.overview import router as overview_router
from app.audit.router import router as audit_router
from app.ci_triage.router import router as ci_triage_router
from app.regression.router import router as regression_router
from app.release_gate.router import router as release_gate_router
from app.seed.router import router as seed_router
from app.testgen.router import router as testgen_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(overview_router)
api_v1_router.include_router(seed_router)
api_v1_router.include_router(testgen_router)
api_v1_router.include_router(ci_triage_router)
api_v1_router.include_router(regression_router)
api_v1_router.include_router(release_gate_router)
api_v1_router.include_router(audit_router)

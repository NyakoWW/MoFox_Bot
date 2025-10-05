from fastapi import APIRouter
from src.api.system_router import router as system_router

# 导出统一的 API 路由
router = APIRouter()
router.include_router(system_router, prefix="/api")

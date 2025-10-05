import psutil
from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.get("/system/stats")
async def get_system_stats():
    """
    获取系统CPU和内存使用率。
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory_info = psutil.virtual_memory()
        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_info.percent
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
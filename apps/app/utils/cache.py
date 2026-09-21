from fastapi_cache import FastAPICache
from apps.app.core.cache_builder import CacheNotFoundError
from apps.app.utils.logger import Logger
import asyncio

async def delete_cache_key(cache_key):
    try:
        backend = FastAPICache.get_backend()
        redis_client = getattr(backend, 'redis', None)
        print("redis_client:", redis_client)
        if redis_client:
           
            exists_before = await redis_client.exists(cache_key)

            if not exists_before:
                raise CacheNotFoundError(f"Cache key not found: {cache_key}")
            
            await redis_client.delete(cache_key)
            Logger.warning(f"[Cache] Deleted cache key: {cache_key}")

    except Exception as e:
        Logger.error(f"[Cache] Failed to delete cache key {cache_key}: {e}")



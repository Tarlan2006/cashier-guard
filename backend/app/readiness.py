import asyncio
import shutil
from urllib.parse import urlparse

from . import pipeline


async def inspect_readiness(config):
    checks = {}
    ffmpeg = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    checks["ffmpeg"] = {"ready": ffmpeg, "detail": "FFmpeg и ffprobe найдены." if ffmpeg else "Установите FFmpeg и ffprobe на сервере."}
    if config.mode == "demo":
        for name in ("rules", "ml1", "ml2"):
            checks[name] = {"ready": True, "detail": "Демонстрационный режим: рабочий компонент не используется."}
    else:
        try:
            rules = pipeline.load_rules(config.rules_path)
            checks["rules"] = {"ready": bool(rules), "detail": f"Проверено правил: {len(rules)}."}
        except Exception:
            checks["rules"] = {"ready": False, "detail": "Каталог правил отсутствует, пуст или не соответствует контракту."}

        async def reachable(name, address):
            try:
                url = urlparse(address)
                if url.scheme not in {"http", "https"} or not url.hostname:
                    raise ValueError("Invalid ML URL")
                _, writer = await asyncio.wait_for(asyncio.open_connection(url.hostname, url.port or (443 if url.scheme == "https" else 80)), 2.0)
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), 0.5)
                checks[name] = {"ready": True, "check": "tcp", "model_verified": False, "detail": "TCP-порт доступен; загрузка модели и корректность ответов ещё не подтверждены."}
            except Exception:
                checks[name] = {"ready": False, "check": "tcp", "model_verified": False, "detail": "Нет соединения с ML-сервисом. Проверьте адрес и запуск сервиса."}
        await asyncio.gather(reachable("ml1", config.ml1_url), reachable("ml2", config.ml2_url))
    return {"ready": all(check["ready"] for check in checks.values()), "processing_verified": False, "mode": config.mode, "checks": checks}

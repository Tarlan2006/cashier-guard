"""Start the prepared local stack; never install models or substitute matching."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
HTTP = build_opener(ProxyHandler({}))


def local_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in {"", "/"}):
        raise ValueError("ML URL должен быть локальным HTTP-адресом без ключей и параметров.")
    return value.rstrip("/")


def command(value):
    try:
        result = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError("COMMAND_JSON должен быть JSON-массивом аргументов, без shell.") from None
    if not isinstance(result, list) or not result or any(not isinstance(x, str) or not x or "\0" in x for x in result):
        raise ValueError("COMMAND_JSON должен быть непустым массивом строк.")
    return result


def health(url):
    try:
        with HTTP.open(url, timeout=1) as response:
            data = json.loads(response.read(64 * 1024))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def stop(children):
    # Only process groups created by this launcher; never stop reused services.
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 15
    for child in children:
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
        # A child may have exited while leaving a model/FFmpeg descendant alive.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


def launch(env, *, build=True, check=False, timeout=180):
    if os.name != "posix":
        raise ValueError("Этот launcher предназначен для Linux/macOS. На Windows используйте Linux/WSL.")
    if not env.get("API_KEY", "").strip() or env["API_KEY"] == "replace-with-your-own-key":
        raise ValueError("Настройте личный API_KEY в .env; значение не выводится.")
    urls = {name: local_url(env.get(name + "_URL", f"http://127.0.0.1:{port}"))
            for name, port in (("ML1", 8001), ("ML2", 8002))}
    commands = {name: command(env[name + "_COMMAND_JSON"]) for name in urls if env.get(name + "_COMMAND_JSON")}
    port = int(env.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT должен быть от 1 до 65535.")
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise ValueError(f"Порт {port} занят. Существующий процесс не остановлен.") from None
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary, path=env.get("PATH")):
            raise ValueError(f"Не найден {binary}; установите FFmpeg >= 5.0 с libx264.")
    for name, url in urls.items():
        if name not in commands and health(url + "/health") is None:
            raise ValueError(f"{name} недоступен. Задайте {name}_COMMAND_JSON и {name}_WORKDIR в .env либо запустите сервис по {name}_URL. Заглушка не подставляется.")
    if build:
        if not (ROOT / "frontend/node_modules").is_dir() or not shutil.which("npm", path=env.get("PATH")):
            raise ValueError("Сначала выполните ./scripts/setup.sh (нужны Node.js и npm).")
        subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", env=env, check=True)
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise ValueError("Нет собранного сайта: выполните npm run build в frontend.")
    child_env = {**env, "PIPELINE_MODE": "live", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                 "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1", "PYTHONUNBUFFERED": "1"}
    log_dir = ROOT / "work/stack"
    log_dir.mkdir(parents=True, exist_ok=True)
    children, logs = [], []

    def start(name, argv, cwd):
        log = (log_dir / f"{name.lower()}.log").open("wb")
        logs.append(log)
        child = subprocess.Popen(argv, cwd=cwd, env=child_env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        children.append(child)

    def wait(url):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("Сервис завершился при запуске. См. work/stack/*.log.")
            result = health(url)
            if result is not None:
                return result
            time.sleep(0.2)
        raise RuntimeError("Истекло ожидание сервиса. См. work/stack/*.log.")

    try:
        for name, argv in commands.items():
            cwd = Path(env.get(name + "_WORKDIR", str(ROOT / ("ml2" if name == "ML1" else ".")))).expanduser()
            if not cwd.is_absolute():
                cwd = ROOT / cwd
            start(name, argv, cwd)
        for name, url in urls.items():
            result = wait(url + "/health")
            if result.get("stub") is True:
                raise RuntimeError(f"{name} сообщает stub=true. Для запуска жюри требуется настоящий сервис.")
            if result.get("transport_fixture") is True:
                print(f"ТЕСТ ТРАНСПОРТА: {name} — синтетический тестовый сервис, без настоящего ML.", flush=True)
            if name == "ML1" and result.get("analysis_status") == "no_rules":
                print("ВНИМАНИЕ: ML1 сообщает no_rules; пустой ответ не доказывает отсутствие нарушений.", flush=True)
        start("backend", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                          "--port", str(port), "--workers", "1", "--no-access-log"], ROOT / "backend")
        base = f"http://127.0.0.1:{port}"
        wait(base + "/api/v1/health")
        readiness = wait(base + "/api/v1/ready")
        if readiness.get("ready") is not True or readiness.get("mode") != "live":
            raise RuntimeError("Backend не готов к live-анализу. Проверьте RULES_PATH, FFmpeg и ML; см. /api/v1/ready.")
        print(f"Сайт и API: {base}; режим live. Ключ задайте в настройках сайта. Ctrl+C останавливает запущенные здесь процессы.", flush=True)
        if check:
            return
        while True:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("Один из сервисов завершился. См. work/stack/*.log.")
            time.sleep(0.5)
    finally:
        stop(children)
        for log in logs:
            log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--skip-build", action="store_true", help="Use an already built frontend, without Node.js at runtime")
    parser.add_argument("--check", action="store_true", help="Check startup/readiness and stop the processes started here")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error("--timeout must be 1..600 seconds")
    load_dotenv(args.env_file)
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        launch(os.environ.copy(), build=not args.skip_build, check=args.check, timeout=args.timeout)
        return 0
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        # Avoid printing command argv or environment values from a failed child.
        print(str(error) if isinstance(error, (ValueError, RuntimeError)) else "Ошибка запуска; см. work/stack/*.log.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

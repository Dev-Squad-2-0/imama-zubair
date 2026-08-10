"""Single startup entrypoint for the RealEstate Hub agent.

Normal API startup:
    python main.py

Local live voice session:
    python main.py --voice

Readiness/configuration check:
    python main.py --check
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"


def _prepare_environment() -> None:
    """Load the root .env and make src/ importable."""
    if not SRC.exists():
        raise RuntimeError(f"src folder not found: {SRC}")

    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        # Docker Compose/env_file may already provide environment variables.
        pass


def _start_api(args: argparse.Namespace) -> None:
    """Start the production FastAPI application."""
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "uvicorn is not installed. Run: pip install -r requirements.txt"
        ) from exc

    host = args.host or os.getenv("HOST", "0.0.0.0")
    port = args.port or int(os.getenv("PORT", "8000"))
    workers = args.workers or int(os.getenv("WEB_CONCURRENCY", "1"))

    print("=" * 68)
    print("RealEstate Hub Agent")
    print("=" * 68)
    print("Mode        : FastAPI")
    print(f"Environment : {os.getenv('APP_ENV', 'development')}")
    print(f"Address     : http://{host}:{port}")
    print(f"Docs        : http://127.0.0.1:{port}/docs")
    print(f"Health      : http://127.0.0.1:{port}/health/ready")
    print("=" * 68)

    # app_dir keeps deployment_api.py importable even when reload/workers
    # cause Uvicorn to create a child process.
    uvicorn.run(
        "deployment_api:app",
        host=host,
        port=port,
        workers=1 if args.reload else workers,
        reload=args.reload,
        app_dir=str(SRC),
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
    )


def _start_voice(args: argparse.Namespace) -> None:
    """Start the local microphone voice-agent session."""
    try:
        from live_voice_pipeline import run_live_session
    except ImportError as exc:
        raise RuntimeError(
            f"Could not import the live voice pipeline: {exc}"
        ) from exc

    caller_id = args.caller_id or os.getenv("TEST_CALLER_ID")
    session_id = args.session or "live-caller"

    print("=" * 68)
    print("RealEstate Hub Agent")
    print("=" * 68)
    print("Mode        : Live Voice")
    print(f"Session     : {session_id}")
    print(f"Caller ID   : {caller_id or '(not set)'}")
    print(f"Barge-in    : {'disabled' if args.no_barge_in else 'enabled'}")
    print("=" * 68)

    run_live_session(
        session_id,
        caller_id=caller_id,
        enable_barge_in=not args.no_barge_in,
    )


def _run_check() -> int:
    """Run the same readiness checks used by the production API."""
    try:
        from deployment_api import health_details
    except ImportError as exc:
        print(f"Could not load deployment API: {exc}")
        return 1

    details = health_details()

    print("=" * 68)
    print("RealEstate Hub Deployment Check")
    print("=" * 68)
    print(json.dumps(details, indent=2, ensure_ascii=False))
    print("=" * 68)

    return 0 if details.get("healthy") else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start the RealEstate Hub AI agent system."
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--voice",
        action="store_true",
        help="Start the local Deepgram -> LangGraph -> Fish Audio voice session.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Run readiness checks and exit.",
    )

    # API options
    parser.add_argument(
        "--host",
        help="FastAPI bind host. Default: HOST env or 0.0.0.0",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="FastAPI port. Default: PORT env or 8000",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="Uvicorn worker count. Default: WEB_CONCURRENCY env or 1",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable Uvicorn auto-reload for local development.",
    )

    # Voice options
    parser.add_argument(
        "--session",
        default="live-caller",
        help="Voice session ID.",
    )
    parser.add_argument(
        "--caller-id",
        help="Caller phone. Falls back to TEST_CALLER_ID.",
    )
    parser.add_argument(
        "--no-barge-in",
        action="store_true",
        help="Disable voice interruption/barge-in.",
    )

    return parser


def main() -> int:
    _prepare_environment()
    args = _build_parser().parse_args()

    try:
        if args.check:
            return _run_check()

        if args.voice:
            _start_voice(args)
        else:
            _start_api(args)

        return 0

    except KeyboardInterrupt:
        print("\nShutting down.")
        return 0

    except Exception as exc:
        print(f"\nStartup failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

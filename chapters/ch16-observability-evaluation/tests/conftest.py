"""第16章のテスト用の部品。他の章の同名モジュール(service・agent_service など)と衝突しない読み込み。"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

# テスト中は、トレースを OpenAI へ送らない
os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-real")

SRC = Path(__file__).parent.parent / "src"
ROOT = SRC.parent.parent.parent
CH15_SRC = ROOT / "chapters/ch15-aws-deploy/src"
CH13_SRC = ROOT / "chapters/ch13-postgresql/src"


def import_chapter_modules() -> SimpleNamespace:
    """実際のコンテナと同じ並び: service・observability は第16章、agent_service は第15章、他は第13章。"""
    names = ["agent_service", "service", "observability", "api", "api.main", "db", "repository", "catalog"]
    saved = {n: sys.modules.pop(n) for n in names if n in sys.modules}
    saved_path = list(sys.path)
    sys.path[:0] = [str(SRC), str(CH15_SRC), str(CH13_SRC)]
    try:
        import agent_service, observability, service  # noqa: E401
        from api import main as api_main
        return SimpleNamespace(agent_service=agent_service, observability=observability, service=service, api_main=api_main)
    finally:
        for n in names:
            sys.modules.pop(n, None)
        sys.modules.update(saved)
        sys.path[:] = saved_path


M = import_chapter_modules()
sys.path.insert(0, str(SRC))  # evaluation パッケージ用

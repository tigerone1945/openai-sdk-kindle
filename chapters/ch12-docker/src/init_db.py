"""初回だけ sales.db を作る。2回目以降は何もしない(状態を消さない)。

第9章の取り込みスクリプトは、実行のたびにDBを作り直す(review_requests も消える)。
コンテナは起動のたびにこの初期化が走りうるため、「無ければ作る」に包む。
"""
import importlib.util
import os
import sys
from pathlib import Path

DB_PATH = Path(os.getenv("SALES_DB_PATH", "data/sales.db"))
SEED_CSV = Path(os.getenv("SEED_CSV_PATH", "/app/seed/ai_agent_practice_sales.csv"))
NORMALIZE = Path(__file__).parent / "scripts" / "normalize_sales_db.py"


def load_normalize():
    spec = importlib.util.spec_from_file_location("normalize_sales_db", NORMALIZE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if DB_PATH.exists():
        print(f"{DB_PATH} は既にあります。何もしません。")
        return 0

    normalize = load_normalize()

    # 途中で止まっても、中途半端なDBが残らないよう、別名で作ってから置き換える。
    partial = DB_PATH.with_suffix(".db.partial")
    partial.unlink(missing_ok=True)
    normalize.CSV_PATH = SEED_CSV
    normalize.DB_PATH = partial
    normalize.main()
    os.replace(partial, DB_PATH)
    print(f"{DB_PATH} を作成しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

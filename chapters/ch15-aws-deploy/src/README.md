# ch15 src

- `terraform/`: AWS の構成(第14章 + ALB・IAM・Secrets Manager・サービス検出・ECS のタスクとサービス)
- `agent_service.py` / `service.py` / `migrations/0003_state.sql` / `Dockerfile.api`: v2(状態を RDS へ)。他のファイル(db・repository・api など)は第13章のものを、Dockerfile が取り込む
- `experiments/`: v1(第13章のコードそのまま)の実験用

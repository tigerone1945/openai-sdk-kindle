"""イメージの層・履歴・設定に、秘密の文字列が入っていないかを調べる。

使い方(秘密は、コマンドラインではなく環境変数で渡す。シェルの履歴に残さないため):
    SECRET_TO_FIND="$(grep ^OPENAI_API_KEY= .env | cut -d= -f2-)" \
        uv run python chapters/ch12-docker/scripts/scan_image_for_secret.py ai-sales-agent-api:local

秘密の値そのものは表示しない。見つかれば終了コード 1。
"""
import io
import os
import subprocess
import sys
import tarfile
import tempfile


def contains_in_layers(tar_path: str, needle: bytes) -> tuple[int, int]:
    """(見つかった数, 中身まで調べたレイヤー数)を返す。"""
    hits = 0
    layers = 0
    with tarfile.open(tar_path) as image:
        for member in image:
            if not member.isfile():
                continue
            data = image.extractfile(member).read()
            hits += needle in data
            # レイヤーは、(gzip などで圧縮された)tar。圧縮形式を自動判定して、中身のファイルまで調べる。
            try:
                layer = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
            except tarfile.TarError:
                continue  # レイヤーではないファイル(設定のJSONなど)
            layers += 1
            with layer:
                for entry in layer:
                    if entry.isfile() and entry.size < 200_000_000:
                        hits += needle in layer.extractfile(entry).read()
    return hits, layers


def main() -> int:
    image = sys.argv[1]
    secret = os.environ["SECRET_TO_FIND"].strip().strip("\"'")
    if len(secret) < 8:
        sys.exit("SECRET_TO_FIND が短すぎます(誤検出を避けるため8文字以上)")

    with tempfile.TemporaryDirectory() as tmp:
        tar_path = os.path.join(tmp, "image.tar")
        subprocess.run(["docker", "save", "-o", tar_path, image], check=True)
        layer_hits, layers = contains_in_layers(tar_path, secret.encode())

    # 検査器が何も開けていないのに「0件」と言わないための、自己点検。
    if layers == 0:
        sys.exit("レイヤーを1つも開けませんでした。検査できていません。")

    history = subprocess.run(["docker", "history", "--no-trunc", image], capture_output=True, text=True, check=True).stdout
    config = subprocess.run(["docker", "inspect", image], capture_output=True, text=True, check=True).stdout

    print(f"{image}: 層{layers}個を検査し、見つかった数={layer_hits}, 履歴={secret in history}, 設定={secret in config}")
    return 1 if (layer_hits or secret in history or secret in config) else 0


if __name__ == "__main__":
    sys.exit(main())

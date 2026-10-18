#!/usr/bin/env bash
# Terraform の state を置く S3 バケットを、あなた自身の AWS アカウントに作る(1 回だけ。terraform destroy では消えない)。
# 「state を置く場所」自体は Terraform で作れない(卵と鶏)ので、AWS CLI で作る。
#
# 使い方:
#   scripts/create_state_bucket.sh [バケット名] [--yes]
#     バケット名を省略すると、"openai-sdk-kindle-tfstate-<あなたのAWSアカウントID>" を使う。
#     環境変数 STATE_BUCKET でも指定できる。--yes を付けないと、何も作らずに内容を表示するだけ。
# バケット名は全 AWS で一意。小文字・数字・ハイフン・ドット、3〜63 文字(例: yamada-tfstate-20261018)。
set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-1}"
BUCKET="${STATE_BUCKET:-}"
YES=0
for arg in "$@"; do
  case "$arg" in
    --yes) YES=1 ;;
    -*) echo "不明なオプション: $arg" >&2; exit 2 ;;
    *) BUCKET="$arg" ;;
  esac
done

if [[ -z "$BUCKET" ]]; then
  ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
  BUCKET="openai-sdk-kindle-tfstate-${ACCOUNT_ID}"
fi

# S3 のバケット名の規則(小文字・数字・ハイフン・ドット、3〜63 文字、先頭と末尾は英数字)
if ! [[ "$BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]; then
  echo "バケット名が S3 の規則に合いません: $BUCKET" >&2
  exit 2
fi

if [[ "$YES" != "1" ]]; then
  echo "作成するバケット: s3://${BUCKET} (${REGION})"
  echo "  バージョニング有効 / パブリックアクセスを全ブロック / SSE-S3 暗号化 / TLS 以外を拒否"
  echo "実行するには --yes を付ける"
  exit 0
fi

if [[ "$REGION" == "us-east-1" ]]; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
else
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
    --create-bucket-configuration "LocationConstraint=${REGION}"
fi

aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-bucket-policy --bucket "$BUCKET" --policy "$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Sid":"DenyInsecureTransport","Effect":"Deny","Principal":"*",
 "Action":"s3:*","Resource":["arn:aws:s3:::${BUCKET}","arn:aws:s3:::${BUCKET}/*"],
 "Condition":{"Bool":{"aws:SecureTransport":"false"}}}]}
JSON
)"

aws s3api put-bucket-tagging --bucket "$BUCKET" \
  --tagging 'TagSet=[{Key=Project,Value=ai-agent-practice},{Key=Purpose,Value=terraform-state}]'

echo "作成した: s3://${BUCKET}"
echo "次: export TF_STATE_BUCKET=${BUCKET}  (README の手順で backend.hcl を作る)"

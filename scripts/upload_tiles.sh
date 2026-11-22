#!/usr/bin/env bash
# Upload tile archives to the Cloudflare R2 bucket (credentials in .env, see .env.example).
#
#   scripts/upload_tiles.sh                      # site/data/topo.pmtiles
#   scripts/upload_tiles.sh path/a.pmtiles ...   # any other archives
#
# Uses boto3 through uv (R2 speaks the S3 API), so there is nothing to install or configure.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "no .env: copy .env.example and fill it in" >&2; exit 1; }
set -a; . ./.env; set +a
: "${R2_BUCKET:?}" "${R2_ENDPOINT:?}" "${R2_ACCESS_KEY_ID:?}" "${R2_SECRET_ACCESS_KEY:?}"
[ $# -gt 0 ] || set -- site/data/topo.pmtiles

uv run --quiet --with boto3 python - "$@" <<'PY'
import os, sys
from pathlib import Path
import boto3
from boto3.s3.transfer import TransferConfig

s3 = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT"], region_name="auto",
                  aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"])
bucket = os.environ["R2_BUCKET"]
for name in sys.argv[1:]:
    p = Path(name)
    print(f" · {p.name}: {p.stat().st_size / 1e6:.1f} MB ...", flush=True)
    s3.upload_file(str(p), bucket, p.name,
                   Config=TransferConfig(multipart_chunksize=32 * 1024 * 1024, max_concurrency=6),
                   ExtraArgs={"ContentType": "application/octet-stream"})
for o in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
    print(f"   {o['Size']:>12}  {o['Key']}")
PY

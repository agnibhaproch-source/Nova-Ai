#!/bin/sh
# Prepares the S3 bucket on the local S3-compatible server (RustFS): creates it, lets browsers
# upload/download with presigned URLs from the app's origin(s), and optionally turns on
# versioning. Idempotent; runs as a one-off (storage-init) in docker-compose.
# Env: S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET, S3_CORS_ORIGINS (comma-separated), S3_VERSIONING.
set -eu
export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" AWS_DEFAULT_REGION="${S3_REGION:-us-east-1}"
s3() { aws --endpoint-url "${S3_INTERNAL_ENDPOINT:-http://storage:9000}" s3api "$@"; }

s3 head-bucket --bucket "$S3_BUCKET" 2>/dev/null || s3 create-bucket --bucket "$S3_BUCKET" >/dev/null

origins=$(printf '%s' "${S3_CORS_ORIGINS:-http://localhost:3000}" | sed 's/[[:space:]]//g; s/,/","/g')
s3 put-bucket-cors --bucket "$S3_BUCKET" --cors-configuration \
  "{\"CORSRules\":[{\"AllowedOrigins\":[\"$origins\"],\"AllowedMethods\":[\"GET\",\"PUT\",\"POST\",\"HEAD\"],\"AllowedHeaders\":[\"*\"],\"ExposeHeaders\":[\"ETag\"],\"MaxAgeSeconds\":3600}]}"

if [ "${S3_VERSIONING:-false}" = "true" ]; then
  s3 put-bucket-versioning --bucket "$S3_BUCKET" --versioning-configuration Status=Enabled
fi
echo "bucket $S3_BUCKET ready (CORS: ${S3_CORS_ORIGINS:-http://localhost:3000}; versioning: ${S3_VERSIONING:-false})"

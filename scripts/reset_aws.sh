#!/usr/bin/env bash
set -euo pipefail

BUCKET_NAME="${BUCKET_NAME:-b3-datalake}"
LAMBDA_NAME="${LAMBDA_NAME:-start-etl}"
GLUE_JOB_NAME="${GLUE_JOB_NAME:-b3-etl-job}"
GLUE_CRAWLER_NAME="${GLUE_CRAWLER_NAME:-b3-refined-crawler}"
GLUE_DATABASE="${GLUE_DATABASE:-default}"
REGION="${AWS_REGION:-sa-east-1}"

if [[ "${CONFIRM_AWS_RESET:-}" != "YES" ]]; then
  echo "ERRO: para apagar recursos na AWS, rode com CONFIRM_AWS_RESET=YES"
  exit 1
fi

echo "==> Limpando recursos na AWS"

# Remove notificação do bucket (se existir)
aws s3api put-bucket-notification-configuration \
  --bucket "${BUCKET_NAME}" \
  --notification-configuration '{}' --region "${REGION}" || true

# Remove Lambda
aws lambda delete-function --function-name "${LAMBDA_NAME}" --region "${REGION}" || true

# Remove Glue Job e Crawler
aws glue delete-crawler --name "${GLUE_CRAWLER_NAME}" --region "${REGION}" || true
aws glue delete-job --job-name "${GLUE_JOB_NAME}" --region "${REGION}" || true

# Remove tabelas do Glue Catalog no DB (se existir)
TABLES=$(aws glue get-tables --database-name "${GLUE_DATABASE}" \
  --query "TableList[].Name" --output text 2>/dev/null || true)
if [[ -n "${TABLES}" ]]; then
  for t in ${TABLES}; do
    aws glue delete-table --database-name "${GLUE_DATABASE}" --name "${t}" --region "${REGION}" || true
  done
fi

# Remove bucket
aws s3 rb "s3://${BUCKET_NAME}" --force --region "${REGION}" || true

echo "==> Reset concluido."

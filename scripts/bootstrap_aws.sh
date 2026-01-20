#!/usr/bin/env bash
set -euo pipefail

# Carrega .env automaticamente (se existir)
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

REGION="${AWS_REGION:-us-east-1}"
BUCKET="${BUCKET:-b3-datalake}"
GLUE_JOB_NAME="${GLUE_JOB_NAME:-b3-etl-job}"
GLUE_ROLE_ARN="${GLUE_ROLE_ARN:?Defina GLUE_ROLE_ARN}"
LAMBDA_ROLE_ARN="${LAMBDA_ROLE_ARN:?Defina LAMBDA_ROLE_ARN}"
GLUE_DB_NAME="${GLUE_DB_NAME:-default}"
CRAWLER_NAME="${CRAWLER_NAME:-b3-refined-crawler}"

echo "==> Criando bucket ${BUCKET} (se nao existir)"
if ! aws s3api head-bucket --bucket "${BUCKET}" >/dev/null 2>&1; then
  if [[ "${REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${BUCKET}" >/dev/null
  else
    aws s3api create-bucket \
      --bucket "${BUCKET}" \
      --create-bucket-configuration LocationConstraint="${REGION}" >/dev/null
  fi
fi

echo "==> Enviando script do Glue para o S3"
aws s3 cp etl/etl_job.py "s3://${BUCKET}/jobs/etl_job.py"

echo "==> Garantindo banco ${GLUE_DB_NAME}"
aws glue create-database --database-input "Name=${GLUE_DB_NAME}" >/dev/null 2>&1 || true

echo "==> Criando/atualizando Glue Job ${GLUE_JOB_NAME}"
if ! aws glue create-job \
  --name "${GLUE_JOB_NAME}" \
  --role "${GLUE_ROLE_ARN}" \
  --default-arguments "{\"--BUCKET\":\"${BUCKET}\"}" \
  --command "Name=glueetl,ScriptLocation=s3://${BUCKET}/jobs/etl_job.py,PythonVersion=3" \
  --glue-version "4.0" \
  --region "${REGION}"; then
  aws glue update-job \
    --job-name "${GLUE_JOB_NAME}" \
    --job-update "{\"Role\":\"${GLUE_ROLE_ARN}\",\"DefaultArguments\":{\"--BUCKET\":\"${BUCKET}\"},\"Command\":{\"Name\":\"glueetl\",\"ScriptLocation\":\"s3://${BUCKET}/jobs/etl_job.py\",\"PythonVersion\":\"3\"},\"GlueVersion\":\"4.0\"}" \
    --region "${REGION}"
fi

echo "==> Criando/atualizando Crawler ${CRAWLER_NAME}"
if ! aws glue create-crawler \
  --name "${CRAWLER_NAME}" \
  --role "${GLUE_ROLE_ARN}" \
  --database-name "${GLUE_DB_NAME}" \
  --targets "S3Targets=[{Path=\"s3://${BUCKET}/refined/\"}]" \
  --region "${REGION}"; then
  aws glue update-crawler \
    --name "${CRAWLER_NAME}" \
    --role "${GLUE_ROLE_ARN}" \
    --database-name "${GLUE_DB_NAME}" \
    --targets "S3Targets=[{Path=\"s3://${BUCKET}/refined/\"}]" \
    --region "${REGION}"
fi

echo "==> Empacotando Lambda start-etl"
(cd lambdas/start-etl && zip -r -q function.zip handler.py)

echo "==> Criando/atualizando Lambda start-etl"
if ! aws lambda create-function \
  --function-name start-etl \
  --runtime python3.10 \
  --handler handler.lambda_handler \
  --role "${LAMBDA_ROLE_ARN}" \
  --zip-file fileb://lambdas/start-etl/function.zip \
  --timeout 120 \
  --environment "Variables={GLUE_JOB_NAME=${GLUE_JOB_NAME},CRAWLER_NAME=${CRAWLER_NAME},WAIT_FOR_JOB=true,JOB_POLL_SECONDS=3,JOB_MAX_WAIT_SECONDS=120}" \
  --region "${REGION}"; then
  aws lambda update-function-code \
    --function-name start-etl \
    --zip-file fileb://lambdas/start-etl/function.zip \
    --region "${REGION}"
fi

aws lambda update-function-configuration \
  --function-name start-etl \
  --timeout 120 \
  --environment "Variables={GLUE_JOB_NAME=${GLUE_JOB_NAME},CRAWLER_NAME=${CRAWLER_NAME},WAIT_FOR_JOB=true,JOB_POLL_SECONDS=3,JOB_MAX_WAIT_SECONDS=120}" \
  --region "${REGION}"

LAMBDA_ARN=$(aws lambda get-function --function-name start-etl --query "Configuration.FunctionArn" --output text --region "${REGION}")

echo "==> Permitindo S3 invocar a Lambda"
aws lambda add-permission \
  --function-name start-etl \
  --statement-id s3invoke \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn "arn:aws:s3:::${BUCKET}" \
  --region "${REGION}" || true

echo "==> Configurando evento do S3 para disparar a Lambda"
aws s3api put-bucket-notification-configuration \
  --bucket "${BUCKET}" \
  --notification-configuration "{\"LambdaFunctionConfigurations\":[{\"LambdaFunctionArn\":\"${LAMBDA_ARN}\",\"Events\":[\"s3:ObjectCreated:*\"],\"Filter\":{\"Key\":{\"FilterRules\":[{\"Name\":\"prefix\",\"Value\":\"raw/\"}]}}}]}" \
  --region "${REGION}"

echo "OK"

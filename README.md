# tc2-b3-market-data-pipeline

## Visao geral
Pipeline AWS para coletar dados diarios da B3, gravar em S3 (parquet particionado),
disparar Lambda -> Glue Job -> Crawler e consultar via Athena.

## Estrutura do projeto

- `scraper/scraper_upload.py` — Scraper e upload para `s3://b3-datalake/raw/...`
- `etl/etl_job.py` — Glue Job (A/B/C: agregacao, renomeio, calculo temporal)
- `lambdas/start-etl/handler.py` — Lambda que inicia o Glue Job e o Crawler
- `scripts/bootstrap_aws.sh` — Provisiona bucket, Glue Job, Crawler e Lambda
- `scripts/reset_aws.sh` — Limpa recursos na AWS (reset total, com confirmacao)

Obs: o unico ETL valido do Glue e o `etl/etl_job.py`.

## Checklist atendido

- Scrap diario de dados da B3 (granularidade diaria)
- Dados brutos em parquet com particao diaria (`raw/ano=.../mes=.../dia=...`)
- Bucket aciona Lambda e Lambda chama Glue
- Glue Job com A/B/C (agregacao, renomeio, calculo temporal)
- Dados refinados em parquet em `refined/ativo=.../data=...`
- Catalogo e tabela no Glue Catalog via Crawler
- Consulta via Athena usando o Glue Catalog

## Como executar (AWS)

1) Configure credenciais e regiao da AWS:
   - `aws configure` ou variaveis `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`

2) Provisionar tudo (defina as roles):
   - `export GLUE_ROLE_ARN=arn:aws:iam::<conta>:role/<glue-role>`
   - `export LAMBDA_ROLE_ARN=arn:aws:iam::<conta>:role/<lambda-role>`
   - `./scripts/bootstrap_aws.sh`

3) Rodar o scraper (grava em `raw/` e dispara a Lambda via S3):
   - `python scraper/scraper_upload.py`

4) Verificar o Glue Job:
   - `aws glue get-job-runs --job-name b3-etl-job --max-results 1`

5) Verificar o refined no S3:
   - `aws s3 ls s3://b3-datalake/refined/ --recursive`

## Queries do Athena (exemplos)

```
SHOW DATABASES;
SHOW TABLES IN default;
DESCRIBE <nome_da_tabela>;
SELECT * FROM <nome_da_tabela> LIMIT 50;
```

## Reset total (se precisar recomeçar)

```
CONFIRM_AWS_RESET=YES ./scripts/reset_aws.sh
```

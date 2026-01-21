# m2-b3-market-data-pipeline

Projeto do Tech Challenge do módulo 2 como parte da Pós Tech em Machine Learning da FIAP.

## Indice

- [Visao geral](#visao-geral)
- [Arquitetura (fluxo)](#arquitetura-fluxo)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Permissoes AWS (IAM)](#permissoes-aws-iam)
- [Checklist atendido](#checklist-atendido)
- [Video de Apresentacao](#video-de-apresentacao)
- [Pre-requisitos](#pre-requisitos)
- [Passo a passo (para funcionar)](#passo-a-passo-para-funcionar)
- [Como executar (AWS)](#como-executar-aws)
- [Queries do Athena (exemplos)](#queries-do-athena-exemplos)
- [Troubleshooting](#troubleshooting)
- [Reset total (se precisar recomecar)](#reset-total-se-precisar-recomecar)

## Visao geral
Pipeline AWS para coletar dados diarios da B3, gravar em S3 (parquet particionado),
disparar Lambda -> Glue Job -> Crawler e consultar via Athena.

## Arquitetura (fluxo)

```mermaid
flowchart LR
  Scraper["Scraper (scraper_upload.py)"] -->|Parquet raw/| S3Raw["S3 raw/"]
  S3Raw -->|S3 ObjectCreated| Lambda["Lambda start-etl"]
  Lambda -->|StartJobRun| GlueJob["Glue Job (etl_job.py)"]
  GlueJob -->|Escreve Parquet refined/| S3Refined["S3 refined/"]
  GlueJob -->|StartCrawler| Crawler["Glue Crawler"]
  Crawler -->|Cataloga tabela| Catalog["Glue Data Catalog"]
  Athena["Athena"] -->|SQL| Catalog
  Athena -->|Lê dados| S3Refined
```

## Estrutura do projeto

- `scraper/scraper_upload.py` — Scraper e upload para `s3://b3-datalake/raw/...`
- `etl/etl_job.py` — Glue Job (A/B/C: agregacao, renomeio, calculo temporal)
- `lambdas/start-etl/handler.py` — Lambda que inicia o Glue Job e o Crawler
- `scripts/bootstrap_aws.sh` — Provisiona bucket, Glue Job, Crawler e Lambda
- `scripts/reset_aws.sh` — Limpa recursos na AWS (reset total, com confirmacao)

Obs: o unico ETL valido do Glue e o `etl/etl_job.py`.

### Detalhes do ETL (`etl/etl_job.py`)

O ETL realiza tres transformacoes principais (A/B/C):

- **A) Agregacao numerica**: Calcula media de `close_price` e soma total de `trade_volume` por ativo
- **B) Renomeio de colunas**: Padroniza nomes (`Close` → `close_price`, `Volume` → `trade_volume`, `Date` → `date`)
- **C) Calculo temporal**: Adiciona media movel de 7 dias (`mm_7d`) para cada ativo

O resultado e gravado em `refined/ativo=<ativo>/data=<data>/result.parquet` com particionamento Hive.

## Permissoes AWS (IAM)

Resumo das permissoes minimas para tudo funcionar. Ajuste `<account>`, `<region>`,
`<bucket>` e nomes conforme seu ambiente.

### 1) Role do Glue (GLUE_ROLE_ARN)

Anexe a policy gerenciada `service-role/AWSGlueServiceRole` e adicione acesso ao S3:

```
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::<bucket>"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": [
        "arn:aws:s3:::<bucket>/raw/*",
        "arn:aws:s3:::<bucket>/refined/*",
        "arn:aws:s3:::<bucket>/jobs/*"
      ]
    }
  ]
}
```

### 2) Role da Lambda (LAMBDA_ROLE_ARN)

Anexe a policy gerenciada `AWSLambdaBasicExecutionRole` e permita iniciar Glue:

```
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "glue:StartJobRun",
        "glue:GetJobRun",
        "glue:GetJobRuns",
        "glue:StartCrawler"
      ],
      "Resource": [
        "arn:aws:glue:<region>:<account>:job/<glue_job_name>",
        "arn:aws:glue:<region>:<account>:crawler/<crawler_name>"
      ]
    }
  ]
}
```

### 3) Usuario/role que roda `scripts/bootstrap_aws.sh`

Precisa criar recursos e passar roles:

```
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:HeadBucket",
        "s3:ListBucket",
        "s3:PutBucketNotification",
        "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::<bucket>",
        "arn:aws:s3:::<bucket>/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "glue:CreateDatabase",
        "glue:CreateJob",
        "glue:UpdateJob",
        "glue:CreateCrawler",
        "glue:UpdateCrawler"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "lambda:CreateFunction",
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration",
        "lambda:GetFunction",
        "lambda:AddPermission"
      ],
      "Resource": "arn:aws:lambda:<region>:<account>:function:start-etl"
    },
    {
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::<account>:role/<glue-role>",
        "arn:aws:iam::<account>:role/<lambda-role>"
      ]
    }
  ]
}
```

### 4) Para consultar via Athena (opcional)

O usuario que roda queries no Athena precisa, no minimo:
- `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults`
- `glue:GetDatabase`, `glue:GetTables`, `glue:GetTable`
- `s3:GetObject` no `refined/` e no bucket de resultados do Athena

## Checklist atendido

- Scrap diario de dados da B3 (granularidade diaria)
- Dados brutos em parquet com particao diaria (`raw/ano=.../mes=.../dia=...`)
- Bucket aciona Lambda e Lambda chama Glue
- Glue Job com A/B/C (agregacao, renomeio, calculo temporal)
- Dados refinados em parquet em `refined/ativo=.../data=...`
- Catalogo e tabela no Glue Catalog via Crawler
- Consulta via Athena usando o Glue Catalog

## Video de Apresentacao

[Link do Video de Apresentacao](https://youtu.be/hab50ssBfpQ)

>Video demonstrando a arquitetura e o funcionamento da pipeline AWS._

## Pre-requisitos

- Python 3.10 ou superior
- AWS CLI instalado e configurado ([guia de instalacao](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html))
- Conta AWS com permissoes para criar recursos (S3, Glue, Lambda, IAM)
- Roles IAM criadas (Glue e Lambda) com as permissoes da secao [Permissoes AWS (IAM)](#permissoes-aws-iam)

## Passo a passo (para funcionar)

1) Crie o bucket S3 e as roles IAM (Glue e Lambda) com as permissoes da secao acima.

2) Crie e ative um ambiente virtual Python:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # No Windows: .venv\Scripts\activate
   ```

3) Instale dependencias do projeto:
   ```bash
   pip install -r requirements.txt
   ```
   Principais libs: `boto3` (AWS SDK), `pandas`, `yfinance`, `pyarrow`

4) Configure o `pyrightconfig.json` (opcional, para Pyright):
   O projeto ja inclui `pyrightconfig.json` apontando para `.venv`. Se precisar criar:
   ```json
   {
     "venvPath": ".",
     "venv": ".venv"
   }
   ```

5) Preencha o `.env` na raiz (ou exporte as variaveis) com `AWS_REGION`, `BUCKET`,
   `GLUE_ROLE_ARN`, `LAMBDA_ROLE_ARN` e o `ATIVO` desejado.

6) Execute `./scripts/bootstrap_aws.sh` para criar Glue Job, Crawler e Lambda.

7) Rode `python scraper/scraper_upload.py` para baixar e enviar o parquet ao S3.

8) Confira a execucao do Glue Job e a tabela no Glue Catalog (Crawler).

9) Consulte os dados refinados no Athena.

## Como executar (AWS)

Opcional: crie um arquivo `.env` na raiz (os scripts carregam automaticamente):

```
AWS_REGION=us-east-1
BUCKET=b3-datalake
GLUE_JOB_NAME=b3-etl-job
GLUE_DB_NAME=default
CRAWLER_NAME=b3-refined-crawler
GLUE_ROLE_ARN=arn:aws:iam::<conta>:role/<glue-role>
LAMBDA_ROLE_ARN=arn:aws:iam::<conta>:role/<lambda-role>
# Defina um ativo (ex: VALE3) ou um ticker completo (ex: VALE3.SA)
ATIVO=VALE3
# TICKER=VALE3.SA
```

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

Apos o Crawler executar, a tabela estara disponivel no Glue Catalog. Exemplos:

```sql
-- Listar databases
SHOW DATABASES;

-- Listar tabelas no database default
SHOW TABLES IN default;

-- Descrever estrutura da tabela
DESCRIBE <nome_da_tabela>;

-- Consultar dados (substitua <nome_da_tabela> pelo nome real)
SELECT * FROM <nome_da_tabela> LIMIT 50;

-- Exemplo: consultar por ativo
SELECT * FROM <nome_da_tabela> WHERE ativo = 'VALE3' ORDER BY date DESC;

-- Exemplo: consultar media movel
SELECT ativo, date, close_price, mm_7d 
FROM <nome_da_tabela> 
WHERE ativo = 'VALE3' 
ORDER BY date DESC 
LIMIT 30;
```

**Nota**: O nome da tabela e gerado automaticamente pelo Crawler baseado no caminho S3. Verifique no console do Glue Data Catalog.

## Troubleshooting

### Lambda nao e disparada quando arquivo e enviado ao S3

- Verifique se a notificacao do S3 esta configurada: `aws s3api get-bucket-notification-configuration --bucket <bucket>`
- Confirme que a Lambda tem permissao para ser invocada pelo S3 (o `bootstrap_aws.sh` faz isso automaticamente)
- Verifique os logs da Lambda no CloudWatch

### Glue Job falha

- Verifique os logs do Glue Job no CloudWatch Logs
- Confirme que a role do Glue tem acesso ao S3 (raw/, refined/, jobs/)
- Verifique se o script `etl_job.py` esta no S3: `aws s3 ls s3://<bucket>/jobs/`

### Crawler nao cria tabela

- Verifique se o Crawler executou com sucesso: `aws glue get-crawler --name <crawler-name>`
- Confirme que existem dados em `refined/`: `aws s3 ls s3://<bucket>/refined/ --recursive`
- Verifique os logs do Crawler no CloudWatch

### Erro de permissoes IAM

- Revise todas as policies das roles conforme a secao [Permissoes AWS (IAM)](#permissoes-aws-iam)
- Confirme que o usuario que roda `bootstrap_aws.sh` tem `iam:PassRole` nas roles

### Scraper nao encontra dados

- Verifique se o ticker esta correto (ex: `VALE3.SA` para acoes brasileiras)
- Confirme que o `ATIVO` ou `TICKER` esta definido no `.env`
- Verifique a conexao com a internet e acesso ao Yahoo Finance

## Reset total (se precisar recomecar)

```
CONFIRM_AWS_RESET=YES ./scripts/reset_aws.sh
```

**Atencao**: Este comando remove todos os recursos criados (bucket, Glue Job, Crawler, Lambda). Os dados no S3 serao perdidos.

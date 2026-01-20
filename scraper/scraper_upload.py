from datetime import datetime
import os

import boto3  # pyright: ignore[reportMissingImports]
import pandas as pd  # pyright: ignore[reportMissingImports]
import yfinance as yf  # pyright: ignore[reportMissingImports]
import pyarrow as pa  # pyright: ignore[reportMissingImports]
import pyarrow.parquet as pq  # pyright: ignore[reportMissingImports]

# Carrega .env automaticamente (se existir)
if os.path.isfile(".env"):
    try:
        with open(".env", "r", encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)
    except OSError:
        pass

BUCKET = os.getenv("BUCKET", "b3-datalake")
REGION = os.getenv("AWS_REGION", "us-east-1")

ATIVO_ENV = os.getenv("ATIVO")
TICKER = os.getenv("TICKER") or (f"{ATIVO_ENV}.SA" if ATIVO_ENV else "VALE3.SA")
ATIVO = ATIVO_ENV or TICKER.split(".")[0]

def main():
    # 1) Baixa dados diários
    df = yf.download(TICKER, period="30d", interval="1d")
    if df is None:
        raise RuntimeError("Falha ao baixar dados do Yahoo Finance.")
    df.reset_index(inplace=True)
    df["ativo"] = ATIVO

    # 2) Partição diária (hoje)
    now = datetime.now()
    ano = now.strftime("%Y")
    mes = now.strftime("%m")
    dia = now.strftime("%d")

    s3_key = f"raw/ano={ano}/mes={mes}/dia={dia}/{ATIVO.lower()}.parquet"
    local_file = "/tmp/raw.parquet"

    # 3) Escreve Parquet
    table = pa.Table.from_pandas(df)
    pq.write_table(table, local_file)

    # 4) Envia para o S3 (AWS)
    s3 = boto3.client(
        "s3",
        region_name=REGION,
    )

    s3.upload_file(local_file, BUCKET, s3_key)

    print("✅ Upload OK")
    print("Bucket:", BUCKET)
    print("Key:", s3_key)
    print("Linhas:", len(df))

if __name__ == "__main__":
    main()
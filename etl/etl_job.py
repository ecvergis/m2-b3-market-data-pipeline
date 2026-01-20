import os
import sys
from datetime import datetime

import boto3  # pyright: ignore[reportMissingImports]
import pandas as pd  # pyright: ignore[reportMissingImports]
import pyarrow as pa  # pyright: ignore[reportMissingImports]
import pyarrow.parquet as pq  # pyright: ignore[reportMissingImports]


# ===== CONFIG =====
def _parse_job_args() -> dict[str, str]:
    args = {}
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg.startswith("--") and "=" in arg:
            key, value = arg[2:].split("=", 1)
            args[key] = value
        elif arg.startswith("--"):
            key = arg[2:]
            if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
                args[key] = sys.argv[i + 1]
                i += 1
        i += 1
    return args


JOB_ARGS = _parse_job_args()
BUCKET = JOB_ARGS.get("BUCKET") or os.getenv("BUCKET", "b3-datalake")
REGION = os.getenv("AWS_REGION", "sa-east-1")

ATIVO = JOB_ARGS.get("ATIVO") or os.getenv("ATIVO")
DATA_PROCESSAMENTO = datetime.now().strftime("%Y-%m-%d")

# ==================


def _coalesce_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    if not df.columns.duplicated().any():
        return df
    seen: set[str] = set()
    ordered_cols: list[str] = []
    for col in df.columns:
        if col not in seen:
            ordered_cols.append(col)
            seen.add(col)

    data = {}
    for col in ordered_cols:
        cols = df.loc[:, df.columns == col]
        if cols.shape[1] == 1:
            data[col] = cols.iloc[:, 0]
        else:
            # Pega o primeiro valor nao-nulo entre colunas duplicadas.
            data[col] = cols.bfill(axis=1).iloc[:, 0]
    return pd.DataFrame(data)


def normalize_raw_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns.to_list()]
    return _coalesce_duplicate_columns(df)


def read_raw_parquet() -> pd.DataFrame | None:
    """
    Lê todos os arquivos parquet do raw/ (exemplo simples).
    """
    s3 = boto3.client(
        "s3",
        region_name=REGION,
    )

    objects = s3.list_objects_v2(
        Bucket=BUCKET,
        Prefix="raw/"
    )

    dfs = []

    for obj in objects.get("Contents", []):
        key = obj["Key"]
        if key.endswith(".parquet"):
            print("Lendo:", key)
            s3.download_file(BUCKET, key, "/tmp/input.parquet")
            table = pq.read_table("/tmp/input.parquet")
            dfs.append(normalize_raw_df(table.to_pandas()))

    if not dfs:
        print("Nenhum parquet encontrado em raw/.")
        return None

    return pd.concat(dfs, ignore_index=True)


def transform(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # 1) Flatten de colunas MultiIndex vindas do yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns.to_list()]
        # Resultado: Date, Close, High, Low, Open, Volume, ativo

    # 2) Agora renomeia normalmente (B)
    df = df.rename(columns={
        "Close": "close_price",
        "Volume": "trade_volume",
        "Date": "date",
    })

    df = _coalesce_duplicate_columns(df)

    # Garantias
    if "ativo" not in df.columns:
        df["ativo"] = ATIVO

    # 3) C) cálculo temporal: média móvel 7 dias
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ativo", "date"])
    df["mm_7d"] = (
        df.groupby("ativo")["close_price"]
        .rolling(window=7).mean()
        .reset_index(level=0, drop=True)
    )

    # 4) A) agregação numérica
    agg = (
        df.groupby("ativo")
        .agg(
            avg_close_price=("close_price", "mean"),
            total_volume=("trade_volume", "sum"),
        )
        .reset_index()
    )

    return df.merge(agg, on="ativo", how="left")


def write_refined(df: pd.DataFrame):
    """
    Escreve parquet no refined/ particionado por ativo e data.
    """
    ativo_value = (
        df["ativo"].iloc[0]
        if "ativo" in df.columns and not df["ativo"].empty
        else ATIVO
    )
    path = f"refined/ativo={ativo_value}/data={DATA_PROCESSAMENTO}/result.parquet"

    # Evita colunas duplicadas: partições também viram colunas no Glue/Athena.
    drop_cols = [col for col in ("ativo", "data") if col in df.columns]
    df_to_write = df.drop(columns=drop_cols)

    table = pa.Table.from_pandas(df_to_write)
    pq.write_table(table, "/tmp/refined.parquet")

    s3 = boto3.client(
        "s3",
        region_name=REGION,
    )

    s3.upload_file("/tmp/refined.parquet", BUCKET, path)
    print("Gravado em:", path)


def main():
    print("ETL START")
    df_raw = read_raw_parquet()
    if df_raw is None or df_raw.empty:
        print("ETL END (sem dados)")
        return
    print("RAW COLUMNS:", list(df_raw.columns))
    print(df_raw.head(3))
    df_refined = transform(df_raw)
    write_refined(df_refined)
    print("ETL END")


if __name__ == "__main__":
    main()
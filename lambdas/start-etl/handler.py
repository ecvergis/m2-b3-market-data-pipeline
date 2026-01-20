"""Lambda que dispara Glue Job e Crawler a partir de eventos do S3."""

import json
import os
import time

import boto3  # pyright: ignore[reportMissingImports]

GLUE_JOB_NAME = os.getenv("GLUE_JOB_NAME", "b3-etl-job")
CRAWLER_NAME = os.getenv("CRAWLER_NAME", "b3-refined-crawler")
WAIT_FOR_JOB = os.getenv("WAIT_FOR_JOB", "true").lower() == "true"
JOB_POLL_SECONDS = int(os.getenv("JOB_POLL_SECONDS", "3"))
JOB_MAX_WAIT_SECONDS = int(os.getenv("JOB_MAX_WAIT_SECONDS", "120"))
REGION = os.getenv("AWS_REGION", "us-east-1")

def lambda_handler(event, context):
    """Inicia o Glue Job e, se configurado, aguarda e dispara o Crawler."""
    print("EVENT:", json.dumps(event))

    glue = boto3.client("glue", region_name=REGION)

    # Evita erro de concorrência: se já houver execução ativa, não inicia outra.
    runs = glue.get_job_runs(JobName=GLUE_JOB_NAME, MaxResults=5)
    for run in runs.get("JobRuns", []):
        state = run.get("JobRunState")
        if state in {"STARTING", "RUNNING", "STOPPING"}:
            print("Job já em execução:", state, run.get("Id"))
            return {"status": "glue_already_running", "run": run.get("Id"), "state": state}

    resp = glue.start_job_run(JobName=GLUE_JOB_NAME)
    print("Glue Job started:", resp)
    job_run_id = resp.get("JobRunId")

    if not WAIT_FOR_JOB or not job_run_id:
        return {"status": "glue_job_started", "run": job_run_id}

    # Espera o job terminar para disparar o crawler automaticamente.
    deadline = time.time() + JOB_MAX_WAIT_SECONDS
    state = "RUNNING"
    while time.time() < deadline and state in {"STARTING", "RUNNING", "STOPPING"}:
        job_run = glue.get_job_run(JobName=GLUE_JOB_NAME, RunId=job_run_id)
        state = job_run["JobRun"]["JobRunState"]
        print("JobRunState:", state)
        if state in {"SUCCEEDED", "FAILED", "STOPPED", "TIMEOUT"}:
            break
        time.sleep(JOB_POLL_SECONDS)

    if state == "SUCCEEDED":
        glue.start_crawler(Name=CRAWLER_NAME)
        print("Crawler started:", CRAWLER_NAME)
        return {"status": "glue_succeeded", "run": job_run_id, "crawler": CRAWLER_NAME}

    print("Glue did not succeed:", state)
    return {"status": "glue_not_succeeded", "run": job_run_id, "state": state}
from airflow import DAG
from airflow.decorators import task
from airflow.models import Variable
from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook
from airflow.utils.dates import days_ago
from airflow.exceptions import AirflowException
from datetime import timedelta
import requests
import logging

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'job_listings_etl_v2',
    default_args=default_args,
    description='ETL DAG for job listings using Adzuna API and historical data',
    schedule_interval='0 6 * * *',  # Cron expression for daily at 6 AM
    start_date=days_ago(1),
    catchup=False,
)

def return_snowflake_conn():
    hook = SnowflakeHook(snowflake_conn_id='snowflake_conn')
    return hook.get_conn().cursor()

### Extract tasks ###
@task
def extract_api():
    app_id = Variable.get('ADZUNA_APP_ID')
    app_key = Variable.get('ADZUNA_API_KEY')
    url = 'https://api.adzuna.com/v1/api/jobs/us/search/1'
    params = {
        'app_id': app_id,
        'app_key': app_key,
        'results_per_page': 100,
        'what': 'software engineer',
        'content-type': 'application/json'
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json().get('results', [])
    except Exception as e:
        logging.error(f"API request failed: {str(e)}")
        raise AirflowException(f"Failed to fetch data from API: {str(e)}")

@task
def extract_csv():
    query = "SELECT * FROM DEV.RAW_DATA.DEMO_HISTORICAL"
    try:
        cur = return_snowflake_conn()
        cur.execute(query)
        results = cur.fetchall()
        columns = [col[0] for col in cur.description]
        return [dict(zip(columns, row)) for row in results]
    except Exception as e:
        logging.error(f"Failed to extract data from Snowflake: {e}")
        raise AirflowException(f"Failed to extract historical data: {e}")

### Transform tasks ###
@task
def transform_api(raw_data):
    transformed_data = []
    for job in raw_data:
        try:
            transformed_data.append({
                'job_id': job.get('id', 'N/A'),
                'job_title': job.get('title', 'N/A'),
                'company': job.get('company', {}).get('display_name', 'N/A'),
                'location': job.get('location', {}).get('display_name', 'N/A'),
                'description': job.get('description', 'N/A')[:1000],
                'salary_min': job.get('salary_min', 0),
                'salary_max': job.get('salary_max', 0),
                'created_at': job.get('created', '1970-01-01'),
            })
        except Exception as e:
            logging.warning(f"Error transforming API data: {str(e)}")
    return transformed_data

@task
def transform_csv(raw_data):
    transformed_data = []
    for row in raw_data:
        try:
            salary_parts = row['JOB_SALARY'].replace('$', '').replace('K', '').split('-') if row.get('JOB_SALARY') else []
            transformed_data.append({
                'job_id': row['JOB_ID'],
                'job_title': row['JOB_TITLE'],
                'company': row['COMPANY'],
                'location': row['LOCATION'],
                'description': row['JOB_DESCRIPTION'][:1000],
                'salary_min': float(salary_parts[0]) * 1000 if salary_parts else None,
                'salary_max': float(salary_parts[1]) * 1000 if len(salary_parts) > 1 else None,
                'created_at': row['CREATED_DATE'],
            })
        except Exception as e:
            logging.warning(f"Error transforming record {row}: {e}")
    return transformed_data

### Load tasks ###
@task
def load_data(records, table_name):
    if not records:
        logging.warning(f"No records to load into {table_name}.")
        return
    staging_table = f"{table_name}_STAGING"
    try:
        cur = return_snowflake_conn()
        cur.execute("BEGIN TRANSACTION")
        cur.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (job_id STRING PRIMARY KEY, job_title STRING, company STRING, location STRING, description STRING, salary_min FLOAT, salary_max FLOAT, created_at TIMESTAMP_NTZ)")
        cur.execute(f"CREATE OR REPLACE TEMPORARY TABLE {staging_table} LIKE {table_name}")
        cur.executemany(f"INSERT INTO {staging_table} VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", [
            (r['job_id'], r['job_title'], r['company'], r['location'], r['description'], r['salary_min'], r['salary_max'], r['created_at'])
            for r in records
        ])
        cur.execute(f"""
        MERGE INTO {table_name} AS target
        USING {staging_table} AS source
        ON target.job_id = source.job_id
        WHEN MATCHED THEN UPDATE SET job_title = source.job_title, company = source.company, location = source.location, description = source.description, salary_min = source.salary_min, salary_max = source.salary_max, created_at = source.created_at
        WHEN NOT MATCHED THEN INSERT (job_id, job_title, company, location, description, salary_min, salary_max, created_at)
        VALUES (source.job_id, source.job_title, source.company, source.location, source.description, source.salary_min, source.salary_max, source.created_at)
        """)
        cur.execute("COMMIT")
    except Exception as e:
        cur.execute("ROLLBACK")
        logging.error(f"Failed to load data into {table_name}: {e}")
        raise AirflowException(f"Failed to load data into {table_name}: {e}")

### DAG Task Workflow ###
with dag:
    raw_api_data = extract_api()
    transformed_api_data = transform_api(raw_api_data)
    load_data(transformed_api_data, "DEV.RAW_DATA.JOB_LISTINGS")

    raw_csv_data = extract_csv()
    transformed_csv_data = transform_csv(raw_csv_data)
    load_data(transformed_csv_data, "DEV.RAW_DATA.HISTORICAL_DATA")

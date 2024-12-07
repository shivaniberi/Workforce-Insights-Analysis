SELECT
    JOB_ID,
    JOB_TITLE,
    COMPANY,
    LOCATION,
    DESCRIPTION,
    SALARY_MIN,
    SALARY_MAX,
    CAST(CREATED_AT AS DATE) AS CREATED_DATE -- Convert to DATE
FROM {{ source('raw_data', 'job_listings') }}


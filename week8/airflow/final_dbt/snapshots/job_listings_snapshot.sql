{% snapshot job_listings_snapshot %}

{{
  config(
    target_schema='snapshot',
    unique_key='JOB_ID',
    strategy='timestamp',
    updated_at='CREATED_AT'
  )
}}

SELECT * FROM {{ source('raw_data', 'job_listings') }}

{% endsnapshot %}


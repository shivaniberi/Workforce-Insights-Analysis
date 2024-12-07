{% snapshot test_snapshot %}

{{
  config(
    target_schema='snapshot',
    unique_key='id',
    strategy='timestamp',
    updated_at='updated_at'
  )
}}

SELECT 1 AS id, CURRENT_TIMESTAMP AS updated_at

{% endsnapshot %}


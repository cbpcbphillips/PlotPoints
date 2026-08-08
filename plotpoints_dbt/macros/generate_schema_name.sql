{#
  Use the model's +schema config as the schema name directly (uppercased), instead
  of dbt's default of prefixing it with the target schema. So staging models land in
  STAGING and marts in MART, not MART_staging / MART_mart.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}

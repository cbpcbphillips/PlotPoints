{#
  Cortex embedding call, with the model and its vector width in one place. The
  function name is dimension-suffixed (embed_text_768 / embed_text_1024), so the
  dimension has to be a var too, not just the model name — changing one without
  the other is a silent mismatch.

  Vars live in dbt_project.yml. Switching either re-embeds the whole catalog:
  media_embeddings matches on embedding_model, so a change misses every row.
#}
{% macro embed_text(text_col) -%}
    snowflake.cortex.embed_text_{{ var('embedding_dimension') }}(
        '{{ var('embedding_model') }}', {{ text_col }}
    )
{%- endmacro %}

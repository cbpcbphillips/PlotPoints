{#
  Deterministic surrogate key for a title, so composite (media_type, tmdb_id) can be
  tested for uniqueness and joined via a single column across dims/bridges/facts.
#}
{% macro media_key(media_type_col, tmdb_id_col) -%}
    md5({{ media_type_col }} || '-' || {{ tmdb_id_col }}::string)
{%- endmacro %}

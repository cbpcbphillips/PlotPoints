{#
  Remove a film's own title from free text before it is embedded.

  Why: embedding models weight repeated surface words heavily. With the title in the document
  and a character who shares its name in the overview ("Will Hunting" in Good Will Hunting),
  neighbours were films with "Hunting" in the title (Happy Hunting, MouseHunt) rather than films
  about the same thing. Measured on 104 seeds, title-word neighbours fell from 34% to 12%.

  full_pattern  the whole title as a regex (words joined by non-alphanumerics)  -> "the film"
  pair_pattern  alternation of adjacent word pairs of the title                  -> "the character"

  Case-sensitive on purpose: names keep the casing the title has ("Will Hunting"), and a
  case-insensitive match would mangle common phrases. Titles of a single word get no pattern from
  int_media_document, because a one-word title like "Her" would eat every "her" in the overview.
  NULL patterns leave the text untouched.
#}
{% macro strip_title(text_col, full_pattern, pair_pattern) -%}
    case
        when {{ text_col }} is null or {{ full_pattern }} is null then {{ text_col }}
        when {{ pair_pattern }} is null then
            regexp_replace({{ text_col }}, $$\b($$ || {{ full_pattern }} || $$)\b$$, 'the film')
        else
            regexp_replace(
                regexp_replace({{ text_col }}, $$\b($$ || {{ full_pattern }} || $$)\b$$, 'the film'),
                $$\b($$ || {{ pair_pattern }} || $$)\b$$,
                'the character'
            )
    end
{%- endmacro %}

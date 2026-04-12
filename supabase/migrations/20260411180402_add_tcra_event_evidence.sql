alter table public.tcra_eventos
    add column if not exists protocolo text not null default '';

alter table public.tcra_eventos
    add column if not exists documento_ref text not null default '';

create or replace function app_private.tcra_search_blob(p_record jsonb)
returns text
language sql
stable
set search_path = ''
as $$
    with normalized_eventos as (
        select
            case
                when jsonb_typeof(coalesce(p_record -> 'eventos', '[]'::jsonb)) = 'array'
                    then coalesce(p_record -> 'eventos', '[]'::jsonb)
                else '[]'::jsonb
            end as eventos_json
    ),
    event_texts as (
        select string_agg(
            concat_ws(
                ' ',
                coalesce(value ->> 'tipo_evento', ''),
                coalesce(value ->> 'descricao', ''),
                coalesce(value ->> 'status_resultante', ''),
                coalesce(value ->> 'protocolo', ''),
                coalesce(value ->> 'documento_ref', '')
            ),
            ' '
        ) as joined_events
        from normalized_eventos
        cross join jsonb_array_elements(eventos_json) as value
    )
    select app_private.normalize_search_text(
        concat_ws(
            ' ',
            coalesce(p_record ->> 'numero_processo', ''),
            coalesce(p_record ->> 'numero_tcra', ''),
            coalesce(p_record ->> 'local', ''),
            coalesce(p_record ->> 'endereco', ''),
            coalesce(p_record ->> 'bairro', ''),
            coalesce(p_record ->> 'orgao_acompanhamento', ''),
            coalesce(p_record ->> 'status', ''),
            coalesce(p_record ->> 'responsavel_execucao', ''),
            coalesce(p_record ->> 'mpsp_relacionado', ''),
            coalesce(p_record ->> 'inquerito_civil', ''),
            coalesce((select joined_events from event_texts), '')
        )
    );
$$;

create or replace function app_private.replace_tcra_eventos(
    p_tcra_uid text,
    p_eventos jsonb
)
returns integer
language plpgsql
set search_path = ''
as $$
declare
    v_inserted_count integer := 0;
    v_sequence integer;
    v_item jsonb;
    v_items jsonb := case
        when jsonb_typeof(coalesce(p_eventos, '[]'::jsonb)) = 'array'
            then coalesce(p_eventos, '[]'::jsonb)
        else '[]'::jsonb
    end;
begin
    delete from public.tcra_eventos
    where tcra_uid = p_tcra_uid;

    for v_item in
        select value
        from jsonb_array_elements(v_items) as value
    loop
        if trim(coalesce(v_item ->> 'data_evento', '')) = ''
           and trim(coalesce(v_item ->> 'tipo_evento', '')) = ''
           and trim(coalesce(v_item ->> 'descricao', '')) = ''
           and trim(coalesce(v_item ->> 'prazo_resultante', '')) = ''
           and trim(coalesce(v_item ->> 'status_resultante', '')) = ''
           and trim(coalesce(v_item ->> 'protocolo', '')) = ''
           and trim(coalesce(v_item ->> 'documento_ref', '')) = ''
        then
            continue;
        end if;

        v_inserted_count := v_inserted_count + 1;

        begin
            v_sequence := coalesce(
                nullif(trim(coalesce(v_item ->> 'sequence', '')), '')::integer,
                v_inserted_count
            );
        exception
            when invalid_text_representation then
                raise exception 'sequence invalida para evento de TCRA %.', p_tcra_uid;
        end;

        insert into public.tcra_eventos (
            tcra_uid,
            sequence,
            data_evento,
            tipo_evento,
            descricao,
            prazo_resultante,
            status_resultante,
            protocolo,
            documento_ref
        ) values (
            p_tcra_uid,
            v_sequence,
            app_private.json_text_to_date(v_item ->> 'data_evento'),
            coalesce(v_item ->> 'tipo_evento', ''),
            coalesce(v_item ->> 'descricao', ''),
            app_private.json_text_to_date(v_item ->> 'prazo_resultante'),
            coalesce(v_item ->> 'status_resultante', ''),
            coalesce(v_item ->> 'protocolo', ''),
            coalesce(v_item ->> 'documento_ref', '')
        );
    end loop;

    return v_inserted_count;
end;
$$;

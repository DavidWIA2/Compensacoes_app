create extension if not exists pgcrypto with schema extensions;

create or replace function app_private.json_text_to_date(p_value text)
returns date
language sql
immutable
set search_path = ''
as $$
    select nullif(trim(coalesce(p_value, '')), '')::date;
$$;

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
                coalesce(value ->> 'status_resultante', '')
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
            status_resultante
        ) values (
            p_tcra_uid,
            v_sequence,
            app_private.json_text_to_date(v_item ->> 'data_evento'),
            coalesce(v_item ->> 'tipo_evento', ''),
            coalesce(v_item ->> 'descricao', ''),
            app_private.json_text_to_date(v_item ->> 'prazo_resultante'),
            coalesce(v_item ->> 'status_resultante', '')
        );
    end loop;

    return v_inserted_count;
end;
$$;

create or replace function app_private.upsert_tcra_record(p_record jsonb)
returns table (
    uid text,
    event_count integer
)
language plpgsql
set search_path = ''
as $$
declare
    v_uid text := coalesce(
        nullif(trim(coalesce(p_record ->> 'uid', '')), ''),
        replace(gen_random_uuid()::text, '-', '')
    );
    v_numero_tcra text := trim(coalesce(p_record ->> 'numero_tcra', ''));
    v_numero_processo text := trim(coalesce(p_record ->> 'numero_processo', ''));
    v_local text := trim(coalesce(p_record ->> 'local', ''));
begin
    if v_numero_tcra <> ''
       and exists (
            select 1
            from public.tcras
            where lower(numero_tcra) = lower(v_numero_tcra)
              and lower(public.tcras.uid) <> lower(v_uid)
       )
    then
        raise exception 'Ja existe TCRA remoto com numero %.', v_numero_tcra;
    end if;

    if v_numero_processo <> ''
       and v_local <> ''
       and exists (
            select 1
            from public.tcras
            where lower(numero_processo) = lower(v_numero_processo)
              and lower(local) = lower(v_local)
              and lower(public.tcras.uid) <> lower(v_uid)
       )
    then
        raise exception 'Ja existe TCRA remoto para processo % e local %.', v_numero_processo, v_local;
    end if;

    insert into public.tcras (
        uid,
        numero_processo,
        numero_tcra,
        local,
        endereco,
        bairro,
        orgao_acompanhamento,
        status,
        data_assinatura,
        prazo_final,
        periodicidade_relatorio_meses,
        data_ultimo_relatorio,
        data_proximo_relatorio,
        area_m2,
        numero_mudas_previsto,
        servicos_exigidos,
        responsavel_execucao,
        observacoes,
        mpsp_relacionado,
        inquerito_civil,
        search_blob_norm
    ) values (
        v_uid,
        v_numero_processo,
        v_numero_tcra,
        v_local,
        coalesce(p_record ->> 'endereco', ''),
        coalesce(p_record ->> 'bairro', ''),
        coalesce(p_record ->> 'orgao_acompanhamento', ''),
        coalesce(p_record ->> 'status', ''),
        app_private.json_text_to_date(p_record ->> 'data_assinatura'),
        app_private.json_text_to_date(p_record ->> 'prazo_final'),
        nullif(trim(coalesce(p_record ->> 'periodicidade_relatorio_meses', '')), '')::integer,
        app_private.json_text_to_date(p_record ->> 'data_ultimo_relatorio'),
        app_private.json_text_to_date(p_record ->> 'data_proximo_relatorio'),
        nullif(trim(coalesce(p_record ->> 'area_m2', '')), '')::double precision,
        nullif(trim(coalesce(p_record ->> 'numero_mudas_previsto', '')), '')::integer,
        coalesce(p_record ->> 'servicos_exigidos', ''),
        coalesce(p_record ->> 'responsavel_execucao', ''),
        coalesce(p_record ->> 'observacoes', ''),
        coalesce(p_record ->> 'mpsp_relacionado', ''),
        coalesce(p_record ->> 'inquerito_civil', ''),
        app_private.tcra_search_blob(p_record)
    )
    on conflict (uid) do update
    set
        numero_processo = excluded.numero_processo,
        numero_tcra = excluded.numero_tcra,
        local = excluded.local,
        endereco = excluded.endereco,
        bairro = excluded.bairro,
        orgao_acompanhamento = excluded.orgao_acompanhamento,
        status = excluded.status,
        data_assinatura = excluded.data_assinatura,
        prazo_final = excluded.prazo_final,
        periodicidade_relatorio_meses = excluded.periodicidade_relatorio_meses,
        data_ultimo_relatorio = excluded.data_ultimo_relatorio,
        data_proximo_relatorio = excluded.data_proximo_relatorio,
        area_m2 = excluded.area_m2,
        numero_mudas_previsto = excluded.numero_mudas_previsto,
        servicos_exigidos = excluded.servicos_exigidos,
        responsavel_execucao = excluded.responsavel_execucao,
        observacoes = excluded.observacoes,
        mpsp_relacionado = excluded.mpsp_relacionado,
        inquerito_civil = excluded.inquerito_civil,
        search_blob_norm = excluded.search_blob_norm;

    event_count := app_private.replace_tcra_eventos(
        v_uid,
        coalesce(p_record -> 'eventos', '[]'::jsonb)
    );
    uid := v_uid;
    return next;
end;
$$;

create or replace function app_private.count_tcra_eventos()
returns integer
language sql
stable
set search_path = ''
as $$
    select count(*)::integer from public.tcra_eventos;
$$;

create or replace function app_private.append_tcra_audit_event(
    p_workbook_path text,
    p_action text,
    p_summary text,
    p_metadata jsonb,
    p_before jsonb,
    p_after jsonb
)
returns text
language plpgsql
set search_path = ''
as $$
declare
    v_event_id text := replace(gen_random_uuid()::text, '-', '');
    v_workbook_id bigint;
    v_workbook_path text := trim(coalesce(p_workbook_path, 'session://banco-local'));
begin
    select public.workbooks.id
    into v_workbook_id
    from public.workbooks
    where public.workbooks.workbook_path = v_workbook_path
    limit 1;

    insert into public.audit_events (
        event_id,
        workbook_id,
        workbook_path,
        timestamp,
        action,
        summary,
        backup_path,
        metadata_json,
        before_json,
        after_json
    ) values (
        v_event_id,
        v_workbook_id,
        v_workbook_path,
        timezone('utc', now()),
        trim(coalesce(p_action, '')),
        trim(coalesce(p_summary, '')),
        '',
        coalesce(p_metadata, '{}'::jsonb),
        p_before,
        p_after
    );

    return v_event_id;
end;
$$;

revoke all on function app_private.json_text_to_date(text) from public;
revoke all on function app_private.tcra_search_blob(jsonb) from public;
revoke all on function app_private.replace_tcra_eventos(text, jsonb) from public;
revoke all on function app_private.upsert_tcra_record(jsonb) from public;
revoke all on function app_private.count_tcra_eventos() from public;
revoke all on function app_private.append_tcra_audit_event(text, text, text, jsonb, jsonb, jsonb) from public;

grant execute on function app_private.json_text_to_date(text) to authenticated;
grant execute on function app_private.tcra_search_blob(jsonb) to authenticated;
grant execute on function app_private.replace_tcra_eventos(text, jsonb) to authenticated;
grant execute on function app_private.upsert_tcra_record(jsonb) to authenticated;
grant execute on function app_private.count_tcra_eventos() to authenticated;
grant execute on function app_private.append_tcra_audit_event(text, text, text, jsonb, jsonb, jsonb) to authenticated;

create or replace function public.rpc_save_tcra_record(
    p_record jsonb,
    p_action text default 'TCRA_SAVE',
    p_summary text default '',
    p_workbook_path text default 'session://banco-local',
    p_metadata jsonb default '{}'::jsonb,
    p_before jsonb default null,
    p_after jsonb default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_uid text;
    v_event_count integer;
    v_tcra_count integer;
    v_tcra_event_count integer;
    v_audit_event_id text;
begin
    if not app_private.can_write_app_data() then
        raise exception 'Usuario autenticado sem permissao de escrita na base oficial.';
    end if;

    select uid, event_count
    into v_uid, v_event_count
    from app_private.upsert_tcra_record(coalesce(p_record, '{}'::jsonb));

    select count(*)::integer into v_tcra_count from public.tcras;
    v_tcra_event_count := app_private.count_tcra_eventos();

    v_audit_event_id := app_private.append_tcra_audit_event(
        p_workbook_path,
        p_action,
        p_summary,
        coalesce(p_metadata, '{}'::jsonb),
        p_before,
        coalesce(p_after, p_record)
    );

    return jsonb_build_object(
        'uid', v_uid,
        'tcra_count', v_tcra_count,
        'tcra_event_count', v_tcra_event_count,
        'imported_count', 0,
        'audit_event_id', v_audit_event_id
    );
end;
$$;

create or replace function public.rpc_delete_tcra_record(
    p_uid text,
    p_action text default 'TCRA_DELETE',
    p_summary text default '',
    p_workbook_path text default 'session://banco-local',
    p_metadata jsonb default '{}'::jsonb,
    p_before jsonb default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_uid text := trim(coalesce(p_uid, ''));
    v_tcra_count integer;
    v_tcra_event_count integer;
    v_audit_event_id text;
begin
    if not app_private.can_write_app_data() then
        raise exception 'Usuario autenticado sem permissao de escrita na base oficial.';
    end if;

    if v_uid = '' then
        raise exception 'UID do TCRA nao informado para exclusao remota.';
    end if;

    if not exists (select 1 from public.tcras where uid = v_uid) then
        raise exception 'TCRA remoto nao encontrado para uid %.', v_uid;
    end if;

    delete from public.tcras
    where uid = v_uid;

    select count(*)::integer into v_tcra_count from public.tcras;
    v_tcra_event_count := app_private.count_tcra_eventos();

    v_audit_event_id := app_private.append_tcra_audit_event(
        p_workbook_path,
        p_action,
        p_summary,
        coalesce(p_metadata, '{}'::jsonb),
        p_before,
        null
    );

    return jsonb_build_object(
        'uid', v_uid,
        'tcra_count', v_tcra_count,
        'tcra_event_count', v_tcra_event_count,
        'imported_count', 0,
        'audit_event_id', v_audit_event_id
    );
end;
$$;

create or replace function public.rpc_save_tcra_records(
    p_records jsonb,
    p_action text default 'TCRA_BULK_SAVE',
    p_summary text default '',
    p_workbook_path text default 'session://banco-local',
    p_metadata jsonb default '{}'::jsonb,
    p_before jsonb default null,
    p_after jsonb default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_item jsonb;
    v_uid text;
    v_event_count integer;
    v_saved_count integer := 0;
    v_tcra_count integer;
    v_tcra_event_count integer;
    v_audit_event_id text;
begin
    if not app_private.can_write_app_data() then
        raise exception 'Usuario autenticado sem permissao de escrita na base oficial.';
    end if;

    if jsonb_typeof(coalesce(p_records, '[]'::jsonb)) <> 'array' then
        raise exception 'O payload de TCRAs precisa ser uma lista JSON.';
    end if;

    for v_item in
        select value
        from jsonb_array_elements(coalesce(p_records, '[]'::jsonb)) as value
    loop
        select uid, event_count
        into v_uid, v_event_count
        from app_private.upsert_tcra_record(v_item);
        v_saved_count := v_saved_count + 1;
    end loop;

    select count(*)::integer into v_tcra_count from public.tcras;
    v_tcra_event_count := app_private.count_tcra_eventos();

    v_audit_event_id := app_private.append_tcra_audit_event(
        p_workbook_path,
        p_action,
        p_summary,
        coalesce(p_metadata, '{}'::jsonb),
        p_before,
        p_after
    );

    return jsonb_build_object(
        'uid', '',
        'tcra_count', v_tcra_count,
        'tcra_event_count', v_tcra_event_count,
        'imported_count', v_saved_count,
        'audit_event_id', v_audit_event_id
    );
end;
$$;

create or replace function public.rpc_replace_tcras_snapshot(
    p_records jsonb,
    p_action text default 'TCRA_IMPORT',
    p_summary text default '',
    p_workbook_path text default 'session://banco-local',
    p_metadata jsonb default '{}'::jsonb,
    p_before jsonb default null,
    p_after jsonb default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_item jsonb;
    v_uid text;
    v_event_count integer;
    v_imported_count integer := 0;
    v_tcra_count integer;
    v_tcra_event_count integer;
    v_audit_event_id text;
begin
    if not app_private.can_write_app_data() then
        raise exception 'Usuario autenticado sem permissao de escrita na base oficial.';
    end if;

    if jsonb_typeof(coalesce(p_records, '[]'::jsonb)) <> 'array' then
        raise exception 'O payload de importacao de TCRAs precisa ser uma lista JSON.';
    end if;

    delete from public.tcras;

    for v_item in
        select value
        from jsonb_array_elements(coalesce(p_records, '[]'::jsonb)) as value
    loop
        select uid, event_count
        into v_uid, v_event_count
        from app_private.upsert_tcra_record(v_item);
        v_imported_count := v_imported_count + 1;
    end loop;

    select count(*)::integer into v_tcra_count from public.tcras;
    v_tcra_event_count := app_private.count_tcra_eventos();

    v_audit_event_id := app_private.append_tcra_audit_event(
        p_workbook_path,
        p_action,
        p_summary,
        coalesce(p_metadata, '{}'::jsonb),
        p_before,
        p_after
    );

    return jsonb_build_object(
        'uid', '',
        'tcra_count', v_tcra_count,
        'tcra_event_count', v_tcra_event_count,
        'imported_count', v_imported_count,
        'audit_event_id', v_audit_event_id
    );
end;
$$;

revoke all on function public.rpc_save_tcra_record(jsonb, text, text, text, jsonb, jsonb, jsonb) from public;
revoke all on function public.rpc_delete_tcra_record(text, text, text, text, jsonb, jsonb) from public;
revoke all on function public.rpc_save_tcra_records(jsonb, text, text, text, jsonb, jsonb, jsonb) from public;
revoke all on function public.rpc_replace_tcras_snapshot(jsonb, text, text, text, jsonb, jsonb, jsonb) from public;

revoke all on function public.rpc_save_tcra_record(jsonb, text, text, text, jsonb, jsonb, jsonb) from anon;
revoke all on function public.rpc_delete_tcra_record(text, text, text, text, jsonb, jsonb) from anon;
revoke all on function public.rpc_save_tcra_records(jsonb, text, text, text, jsonb, jsonb, jsonb) from anon;
revoke all on function public.rpc_replace_tcras_snapshot(jsonb, text, text, text, jsonb, jsonb, jsonb) from anon;

grant execute on function public.rpc_save_tcra_record(jsonb, text, text, text, jsonb, jsonb, jsonb) to authenticated;
grant execute on function public.rpc_delete_tcra_record(text, text, text, text, jsonb, jsonb) to authenticated;
grant execute on function public.rpc_save_tcra_records(jsonb, text, text, text, jsonb, jsonb, jsonb) to authenticated;
grant execute on function public.rpc_replace_tcras_snapshot(jsonb, text, text, text, jsonb, jsonb, jsonb) to authenticated;

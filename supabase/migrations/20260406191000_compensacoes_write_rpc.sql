create extension if not exists pgcrypto with schema extensions;
create extension if not exists unaccent with schema extensions;

create or replace function app_private.normalize_search_text(p_value text)
returns text
language sql
immutable
set search_path = ''
as $$
    select lower(trim(extensions.unaccent(coalesce(p_value, ''))));
$$;

create or replace function app_private.extract_year_from_text(p_value text)
returns text
language sql
immutable
set search_path = ''
as $$
    select coalesce(
        nullif(substring(coalesce(p_value, '') from '/(20[0-9]{2}|19[0-9]{2})'), ''),
        nullif(substring(coalesce(p_value, '') from '(20[0-9]{2}|19[0-9]{2})'), '')
    );
$$;

create or replace function app_private.record_search_blob(p_record jsonb)
returns text
language sql
stable
set search_path = ''
as $$
    with normalized_plantios as (
        select
            case
                when jsonb_typeof(coalesce(p_record -> 'plantios', '[]'::jsonb)) = 'array'
                    then coalesce(p_record -> 'plantios', '[]'::jsonb)
                else '[]'::jsonb
            end as plantios_json
    ),
    plantio_addresses as (
        select string_agg(trim(coalesce(value ->> 'endereco', '')), ' ') as joined_addresses
        from normalized_plantios
        cross join jsonb_array_elements(plantios_json) as value
    )
    select app_private.normalize_search_text(
        concat_ws(
            ' ',
            coalesce(p_record ->> 'oficio_processo', ''),
            coalesce(p_record ->> 'endereco', ''),
            coalesce(p_record ->> 'endereco_plantio', ''),
            coalesce((select joined_addresses from plantio_addresses), ''),
            coalesce(p_record ->> 'microbacia', ''),
            coalesce(p_record ->> 'av_tec', ''),
            coalesce(p_record ->> 'caixa', ''),
            coalesce(p_record ->> 'eletronico', '')
        )
    );
$$;

create or replace function app_private.next_record_excel_row(p_workbook_id bigint)
returns integer
language sql
stable
set search_path = ''
as $$
    select coalesce(max(public.records.excel_row), 1) + 1
    from public.records
    where workbook_id = p_workbook_id;
$$;

create or replace function app_private.replace_record_plantios(
    p_record_id bigint,
    p_plantios jsonb
)
returns integer
language plpgsql
set search_path = ''
as $$
declare
    v_inserted_count integer := 0;
    v_item jsonb;
    v_items jsonb := case
        when jsonb_typeof(coalesce(p_plantios, '[]'::jsonb)) = 'array'
            then coalesce(p_plantios, '[]'::jsonb)
        else '[]'::jsonb
    end;
begin
    delete from public.plantios
    where record_id = p_record_id;

    for v_item in
        select value
        from jsonb_array_elements(v_items) as value
    loop
        if trim(coalesce(v_item ->> 'endereco', '')) = ''
           and trim(coalesce(v_item ->> 'qtd_mudas', '')) = ''
           and trim(coalesce(v_item ->> 'latitude', '')) = ''
           and trim(coalesce(v_item ->> 'longitude', '')) = ''
        then
            continue;
        end if;

        v_inserted_count := v_inserted_count + 1;

        insert into public.plantios (
            record_id,
            sequence,
            endereco,
            qtd_mudas,
            latitude,
            longitude
        ) values (
            p_record_id,
            v_inserted_count,
            coalesce(v_item ->> 'endereco', ''),
            coalesce(v_item ->> 'qtd_mudas', ''),
            coalesce(v_item ->> 'latitude', ''),
            coalesce(v_item ->> 'longitude', '')
        );
    end loop;

    return v_inserted_count;
end;
$$;

create or replace function app_private.refresh_workbook_counters(p_workbook_id bigint)
returns table (
    workbook_path text,
    record_count integer,
    plantio_count integer
)
language plpgsql
set search_path = ''
as $$
begin
    update public.workbooks
    set
        last_synced_at = timezone('utc', now()),
        record_count = coalesce(
            (
                select count(*)
                from public.records
                where workbook_id = p_workbook_id
            ),
            0
        ),
        plantio_count = coalesce(
            (
                select count(*)
                from public.plantios
                join public.records on public.records.id = public.plantios.record_id
                where public.records.workbook_id = p_workbook_id
            ),
            0
        )
    where id = p_workbook_id
    returning
        public.workbooks.workbook_path,
        public.workbooks.record_count,
        public.workbooks.plantio_count
    into workbook_path, record_count, plantio_count;

    if workbook_path is null then
        raise exception 'Workbook remoto nao encontrado para id %.', p_workbook_id;
    end if;

    return next;
end;
$$;

create or replace function app_private.append_audit_event(
    p_workbook_id bigint,
    p_workbook_path text,
    p_action text,
    p_summary text,
    p_backup_path text,
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
begin
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
        p_workbook_id,
        p_workbook_path,
        timezone('utc', now()),
        trim(coalesce(p_action, '')),
        trim(coalesce(p_summary, '')),
        trim(coalesce(p_backup_path, '')),
        coalesce(p_metadata, '{}'::jsonb),
        p_before,
        p_after
    );

    return v_event_id;
end;
$$;

create or replace function app_private.upsert_compensacao_record(
    p_workbook_id bigint,
    p_record jsonb
)
returns table (
    record_id bigint,
    uid text,
    excel_row integer,
    plantio_count integer
)
language plpgsql
set search_path = ''
as $$
declare
    v_uid text := coalesce(
        nullif(trim(coalesce(p_record ->> 'uid', '')), ''),
        replace(gen_random_uuid()::text, '-', '')
    );
    v_requested_excel_row integer;
    v_existing_excel_row integer;
    v_effective_excel_row integer;
    v_record_id bigint;
begin
    begin
        v_requested_excel_row := nullif(trim(coalesce(p_record ->> 'excel_row', '')), '')::integer;
    exception
        when invalid_text_representation then
            raise exception 'excel_row invalido para uid %.', v_uid;
    end;

    select public.records.excel_row
    into v_existing_excel_row
    from public.records
    where public.records.workbook_id = p_workbook_id
      and lower(public.records.uid) = lower(v_uid)
    limit 1;

    v_effective_excel_row := coalesce(
        nullif(v_requested_excel_row, 0),
        nullif(v_existing_excel_row, 0),
        app_private.next_record_excel_row(p_workbook_id)
    );

    insert into public.records (
        workbook_id,
        uid,
        excel_row,
        oficio_processo,
        eletronico,
        caixa,
        av_tec,
        compensacao,
        endereco,
        microbacia,
        compensado,
        endereco_plantio,
        latitude_plantio,
        longitude_plantio,
        latitude,
        longitude,
        synced_at,
        oficio_year,
        tipo_key,
        microbacia_key,
        search_blob_norm
    ) values (
        p_workbook_id,
        v_uid,
        v_effective_excel_row,
        coalesce(p_record ->> 'oficio_processo', ''),
        coalesce(p_record ->> 'eletronico', ''),
        coalesce(p_record ->> 'caixa', ''),
        coalesce(p_record ->> 'av_tec', ''),
        coalesce(p_record ->> 'compensacao', ''),
        coalesce(p_record ->> 'endereco', ''),
        coalesce(p_record ->> 'microbacia', ''),
        coalesce(p_record ->> 'compensado', ''),
        coalesce(p_record ->> 'endereco_plantio', ''),
        coalesce(p_record ->> 'latitude_plantio', ''),
        coalesce(p_record ->> 'longitude_plantio', ''),
        coalesce(p_record ->> 'latitude', ''),
        coalesce(p_record ->> 'longitude', ''),
        timezone('utc', now()),
        coalesce(app_private.extract_year_from_text(p_record ->> 'oficio_processo'), ''),
        app_private.normalize_search_text(coalesce(p_record ->> 'eletronico', '')),
        app_private.normalize_search_text(coalesce(p_record ->> 'microbacia', '')),
        app_private.record_search_blob(p_record)
    )
    on conflict (workbook_id, lower(uid)) do update
    set
        excel_row = excluded.excel_row,
        oficio_processo = excluded.oficio_processo,
        eletronico = excluded.eletronico,
        caixa = excluded.caixa,
        av_tec = excluded.av_tec,
        compensacao = excluded.compensacao,
        endereco = excluded.endereco,
        microbacia = excluded.microbacia,
        compensado = excluded.compensado,
        endereco_plantio = excluded.endereco_plantio,
        latitude_plantio = excluded.latitude_plantio,
        longitude_plantio = excluded.longitude_plantio,
        latitude = excluded.latitude,
        longitude = excluded.longitude,
        synced_at = excluded.synced_at,
        oficio_year = excluded.oficio_year,
        tipo_key = excluded.tipo_key,
        microbacia_key = excluded.microbacia_key,
        search_blob_norm = excluded.search_blob_norm
    returning public.records.id, public.records.uid, public.records.excel_row
    into v_record_id, uid, excel_row;

    plantio_count := app_private.replace_record_plantios(
        v_record_id,
        coalesce(p_record -> 'plantios', '[]'::jsonb)
    );
    record_id := v_record_id;
    return next;
end;
$$;

revoke all on function app_private.normalize_search_text(text) from public;
revoke all on function app_private.extract_year_from_text(text) from public;
revoke all on function app_private.record_search_blob(jsonb) from public;
revoke all on function app_private.next_record_excel_row(bigint) from public;
revoke all on function app_private.replace_record_plantios(bigint, jsonb) from public;
revoke all on function app_private.refresh_workbook_counters(bigint) from public;
revoke all on function app_private.append_audit_event(bigint, text, text, text, text, jsonb, jsonb, jsonb) from public;
revoke all on function app_private.upsert_compensacao_record(bigint, jsonb) from public;

revoke all on function app_private.normalize_search_text(text) from anon;
revoke all on function app_private.extract_year_from_text(text) from anon;
revoke all on function app_private.record_search_blob(jsonb) from anon;
revoke all on function app_private.next_record_excel_row(bigint) from anon;
revoke all on function app_private.replace_record_plantios(bigint, jsonb) from anon;
revoke all on function app_private.refresh_workbook_counters(bigint) from anon;
revoke all on function app_private.append_audit_event(bigint, text, text, text, text, jsonb, jsonb, jsonb) from anon;
revoke all on function app_private.upsert_compensacao_record(bigint, jsonb) from anon;

grant execute on function app_private.normalize_search_text(text) to authenticated;
grant execute on function app_private.extract_year_from_text(text) to authenticated;
grant execute on function app_private.record_search_blob(jsonb) to authenticated;
grant execute on function app_private.next_record_excel_row(bigint) to authenticated;
grant execute on function app_private.replace_record_plantios(bigint, jsonb) to authenticated;
grant execute on function app_private.refresh_workbook_counters(bigint) to authenticated;
grant execute on function app_private.append_audit_event(bigint, text, text, text, text, jsonb, jsonb, jsonb) to authenticated;
grant execute on function app_private.upsert_compensacao_record(bigint, jsonb) to authenticated;

create or replace function public.rpc_save_compensacao_record(
    p_workbook_path text,
    p_record jsonb,
    p_action text default 'SAVE',
    p_summary text default '',
    p_backup_path text default '',
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
    v_workbook_id bigint;
    v_record_id bigint;
    v_uid text;
    v_excel_row integer;
    v_record_plantio_count integer;
    v_workbook_record_count integer;
    v_workbook_plantio_count integer;
    v_workbook_path text;
    v_audit_event_id text;
begin
    if not app_private.can_write_app_data() then
        raise exception 'Usuario autenticado sem permissao de escrita na base oficial.';
    end if;

    select public.workbooks.id
    into v_workbook_id
    from public.workbooks
    where public.workbooks.workbook_path = trim(coalesce(p_workbook_path, ''))
    limit 1;

    if v_workbook_id is null then
        raise exception 'Workbook remoto nao encontrado para %.', p_workbook_path;
    end if;

    select record_id, uid, excel_row, plantio_count
    into v_record_id, v_uid, v_excel_row, v_record_plantio_count
    from app_private.upsert_compensacao_record(v_workbook_id, coalesce(p_record, '{}'::jsonb));

    select workbook_path, record_count, plantio_count
    into v_workbook_path, v_workbook_record_count, v_workbook_plantio_count
    from app_private.refresh_workbook_counters(v_workbook_id);

    v_audit_event_id := app_private.append_audit_event(
        v_workbook_id,
        v_workbook_path,
        p_action,
        p_summary,
        p_backup_path,
        coalesce(p_metadata, '{}'::jsonb),
        p_before,
        coalesce(p_after, p_record)
    );

    return jsonb_build_object(
        'workbook_path', v_workbook_path,
        'uid', v_uid,
        'record_id', v_record_id,
        'excel_row', v_excel_row,
        'record_count', v_workbook_record_count,
        'plantio_count', v_workbook_plantio_count,
        'imported_count', 0,
        'audit_event_id', v_audit_event_id
    );
end;
$$;

create or replace function public.rpc_delete_compensacao_record(
    p_workbook_path text,
    p_uid text,
    p_action text default 'DELETE',
    p_summary text default '',
    p_backup_path text default '',
    p_metadata jsonb default '{}'::jsonb,
    p_before jsonb default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_workbook_id bigint;
    v_record_id bigint;
    v_deleted_uid text;
    v_deleted_excel_row integer;
    v_workbook_record_count integer;
    v_workbook_plantio_count integer;
    v_workbook_path text;
    v_audit_event_id text;
begin
    if not app_private.can_write_app_data() then
        raise exception 'Usuario autenticado sem permissao de escrita na base oficial.';
    end if;

    select public.workbooks.id
    into v_workbook_id
    from public.workbooks
    where public.workbooks.workbook_path = trim(coalesce(p_workbook_path, ''))
    limit 1;

    if v_workbook_id is null then
        raise exception 'Workbook remoto nao encontrado para %.', p_workbook_path;
    end if;

    select public.records.id
    into v_record_id
    from public.records
    where public.records.workbook_id = v_workbook_id
      and lower(public.records.uid) = lower(trim(coalesce(p_uid, '')))
    limit 1;

    if v_record_id is null then
        raise exception 'Registro remoto nao encontrado para uid %.', p_uid;
    end if;

    delete from public.records
    where public.records.id = v_record_id
    returning public.records.uid, public.records.excel_row
    into v_deleted_uid, v_deleted_excel_row;

    select workbook_path, record_count, plantio_count
    into v_workbook_path, v_workbook_record_count, v_workbook_plantio_count
    from app_private.refresh_workbook_counters(v_workbook_id);

    v_audit_event_id := app_private.append_audit_event(
        v_workbook_id,
        v_workbook_path,
        p_action,
        p_summary,
        p_backup_path,
        coalesce(p_metadata, '{}'::jsonb),
        p_before,
        null
    );

    return jsonb_build_object(
        'workbook_path', v_workbook_path,
        'uid', v_deleted_uid,
        'record_id', v_record_id,
        'excel_row', v_deleted_excel_row,
        'record_count', v_workbook_record_count,
        'plantio_count', v_workbook_plantio_count,
        'imported_count', 0,
        'audit_event_id', v_audit_event_id
    );
end;
$$;

create or replace function public.rpc_replace_compensacoes_snapshot(
    p_workbook_path text,
    p_records jsonb,
    p_action text default 'IMPORT',
    p_summary text default '',
    p_backup_path text default '',
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
    v_workbook_id bigint;
    v_workbook_record_count integer;
    v_workbook_plantio_count integer;
    v_workbook_path text;
    v_audit_event_id text;
    v_imported_count integer := 0;
    v_item jsonb;
begin
    if not app_private.can_write_app_data() then
        raise exception 'Usuario autenticado sem permissao de escrita na base oficial.';
    end if;

    select public.workbooks.id
    into v_workbook_id
    from public.workbooks
    where public.workbooks.workbook_path = trim(coalesce(p_workbook_path, ''))
    limit 1;

    if v_workbook_id is null then
        raise exception 'Workbook remoto nao encontrado para %.', p_workbook_path;
    end if;

    delete from public.records
    where public.records.workbook_id = v_workbook_id;

    if jsonb_typeof(coalesce(p_records, '[]'::jsonb)) <> 'array' then
        raise exception 'O payload de importacao precisa ser uma lista JSON de registros.';
    end if;

    for v_item in
        select value
        from jsonb_array_elements(coalesce(p_records, '[]'::jsonb)) as value
    loop
        perform *
        from app_private.upsert_compensacao_record(v_workbook_id, v_item);
        v_imported_count := v_imported_count + 1;
    end loop;

    select workbook_path, record_count, plantio_count
    into v_workbook_path, v_workbook_record_count, v_workbook_plantio_count
    from app_private.refresh_workbook_counters(v_workbook_id);

    v_audit_event_id := app_private.append_audit_event(
        v_workbook_id,
        v_workbook_path,
        p_action,
        p_summary,
        p_backup_path,
        coalesce(p_metadata, '{}'::jsonb),
        p_before,
        p_after
    );

    return jsonb_build_object(
        'workbook_path', v_workbook_path,
        'uid', '',
        'record_id', 0,
        'excel_row', 0,
        'record_count', v_workbook_record_count,
        'plantio_count', v_workbook_plantio_count,
        'imported_count', v_imported_count,
        'audit_event_id', v_audit_event_id
    );
end;
$$;

revoke all on function public.rpc_save_compensacao_record(text, jsonb, text, text, text, jsonb, jsonb, jsonb) from public;
revoke all on function public.rpc_delete_compensacao_record(text, text, text, text, text, jsonb, jsonb) from public;
revoke all on function public.rpc_replace_compensacoes_snapshot(text, jsonb, text, text, text, jsonb, jsonb, jsonb) from public;

revoke all on function public.rpc_save_compensacao_record(text, jsonb, text, text, text, jsonb, jsonb, jsonb) from anon;
revoke all on function public.rpc_delete_compensacao_record(text, text, text, text, text, jsonb, jsonb) from anon;
revoke all on function public.rpc_replace_compensacoes_snapshot(text, jsonb, text, text, text, jsonb, jsonb, jsonb) from anon;

grant execute on function public.rpc_save_compensacao_record(text, jsonb, text, text, text, jsonb, jsonb, jsonb) to authenticated;
grant execute on function public.rpc_delete_compensacao_record(text, text, text, text, text, jsonb, jsonb) to authenticated;
grant execute on function public.rpc_replace_compensacoes_snapshot(text, jsonb, text, text, text, jsonb, jsonb, jsonb) to authenticated;

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
#variable_conflict use_column
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

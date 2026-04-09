alter table public.records
    add column if not exists updated_at timestamptz not null default timezone('utc', now());

drop trigger if exists trg_records_touch_updated_at on public.records;
create trigger trg_records_touch_updated_at
before update on public.records
for each row
execute function public.touch_updated_at();

drop function if exists public.rpc_save_compensacao_record(text, jsonb, text, text, text, jsonb, jsonb, jsonb);
drop function if exists public.rpc_save_compensacao_record(text, jsonb, text, text, text, text, jsonb, jsonb, jsonb);

create or replace function public.rpc_save_compensacao_record(
    p_workbook_path text,
    p_record jsonb,
    p_action text default 'SAVE',
    p_summary text default '',
    p_backup_path text default '',
    p_expected_updated_at text default null,
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
    v_record_updated_at timestamptz;
    v_record_plantio_count integer;
    v_workbook_record_count integer;
    v_workbook_plantio_count integer;
    v_workbook_path text;
    v_audit_event_id text;
    v_lookup_uid text := nullif(trim(coalesce(p_record ->> 'uid', '')), '');
    v_existing_record_id bigint;
    v_existing_updated_at timestamptz;
    v_expected_updated_at timestamptz;
begin
    if not app_private.can_write_app_data() then
        raise exception 'Usuario autenticado sem permissao de escrita na base oficial.';
    end if;

    if nullif(trim(coalesce(p_expected_updated_at, '')), '') is not null then
        begin
            v_expected_updated_at := trim(coalesce(p_expected_updated_at, ''))::timestamptz;
        exception
            when invalid_text_representation then
                raise exception 'p_expected_updated_at invalido para o registro remoto.';
        end;
    end if;

    select public.workbooks.id
    into v_workbook_id
    from public.workbooks
    where public.workbooks.workbook_path = trim(coalesce(p_workbook_path, ''))
    limit 1;

    if v_workbook_id is null then
        raise exception 'Workbook remoto nao encontrado para %.', p_workbook_path;
    end if;

    if v_lookup_uid is not null then
        select public.records.id, public.records.updated_at
        into v_existing_record_id, v_existing_updated_at
        from public.records
        where public.records.workbook_id = v_workbook_id
          and lower(public.records.uid) = lower(v_lookup_uid)
        limit 1;
    end if;

    if v_existing_record_id is not null then
        if v_expected_updated_at is null then
            raise exception 'compensacao_record_conflict: o registro remoto precisa ser recarregado antes da edicao.';
        end if;
        if v_existing_updated_at is distinct from v_expected_updated_at then
            raise exception 'compensacao_record_conflict: o registro remoto foi alterado por outra sessao.';
        end if;
    end if;

    select record_id, uid, excel_row, plantio_count
    into v_record_id, v_uid, v_excel_row, v_record_plantio_count
    from app_private.upsert_compensacao_record(v_workbook_id, coalesce(p_record, '{}'::jsonb));

    select public.records.updated_at
    into v_record_updated_at
    from public.records
    where public.records.id = v_record_id
    limit 1;

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
        'updated_at', coalesce(v_record_updated_at::text, ''),
        'record_count', v_workbook_record_count,
        'plantio_count', v_workbook_plantio_count,
        'imported_count', 0,
        'audit_event_id', v_audit_event_id
    );
end;
$$;

drop function if exists public.rpc_delete_compensacao_record(text, text, text, text, text, jsonb, jsonb);
drop function if exists public.rpc_delete_compensacao_record(text, text, text, text, text, text, jsonb, jsonb);

create or replace function public.rpc_delete_compensacao_record(
    p_workbook_path text,
    p_uid text,
    p_action text default 'DELETE',
    p_summary text default '',
    p_backup_path text default '',
    p_expected_updated_at text default null,
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
    v_deleted_updated_at timestamptz;
    v_workbook_record_count integer;
    v_workbook_plantio_count integer;
    v_workbook_path text;
    v_audit_event_id text;
    v_expected_updated_at timestamptz;
begin
    if not app_private.can_write_app_data() then
        raise exception 'Usuario autenticado sem permissao de escrita na base oficial.';
    end if;

    if nullif(trim(coalesce(p_expected_updated_at, '')), '') is not null then
        begin
            v_expected_updated_at := trim(coalesce(p_expected_updated_at, ''))::timestamptz;
        exception
            when invalid_text_representation then
                raise exception 'p_expected_updated_at invalido para o registro remoto.';
        end;
    end if;

    select public.workbooks.id
    into v_workbook_id
    from public.workbooks
    where public.workbooks.workbook_path = trim(coalesce(p_workbook_path, ''))
    limit 1;

    if v_workbook_id is null then
        raise exception 'Workbook remoto nao encontrado para %.', p_workbook_path;
    end if;

    select public.records.id, public.records.uid, public.records.excel_row, public.records.updated_at
    into v_record_id, v_deleted_uid, v_deleted_excel_row, v_deleted_updated_at
    from public.records
    where public.records.workbook_id = v_workbook_id
      and lower(public.records.uid) = lower(trim(coalesce(p_uid, '')))
    limit 1;

    if v_record_id is null then
        raise exception 'Registro remoto nao encontrado para uid %.', p_uid;
    end if;

    if v_expected_updated_at is null then
        raise exception 'compensacao_record_conflict: o registro remoto precisa ser recarregado antes da exclusao.';
    end if;
    if v_deleted_updated_at is distinct from v_expected_updated_at then
        raise exception 'compensacao_record_conflict: o registro remoto foi alterado por outra sessao.';
    end if;

    delete from public.records
    where public.records.id = v_record_id;

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
        'updated_at', coalesce(v_deleted_updated_at::text, ''),
        'record_count', v_workbook_record_count,
        'plantio_count', v_workbook_plantio_count,
        'imported_count', 0,
        'audit_event_id', v_audit_event_id
    );
end;
$$;

revoke all on function public.rpc_save_compensacao_record(text, jsonb, text, text, text, text, jsonb, jsonb, jsonb) from public;
revoke all on function public.rpc_delete_compensacao_record(text, text, text, text, text, text, jsonb, jsonb) from public;

revoke all on function public.rpc_save_compensacao_record(text, jsonb, text, text, text, text, jsonb, jsonb, jsonb) from anon;
revoke all on function public.rpc_delete_compensacao_record(text, text, text, text, text, text, jsonb, jsonb) from anon;

grant execute on function public.rpc_save_compensacao_record(text, jsonb, text, text, text, text, jsonb, jsonb, jsonb) to authenticated;
grant execute on function public.rpc_delete_compensacao_record(text, text, text, text, text, text, jsonb, jsonb) to authenticated;

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
    on conflict on constraint tcras_pkey do update
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

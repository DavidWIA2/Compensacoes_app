create or replace function app_private.rpc_admin_update_user(
    p_user_id uuid,
    p_email text,
    p_display_name text default ''
)
returns public.profiles
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_actor_id uuid := auth.uid();
    v_email text := lower(trim(coalesce(p_email, '')));
    v_display_name text := trim(coalesce(p_display_name, ''));
    v_profile public.profiles%rowtype;
begin
    if v_actor_id is null then
        raise exception 'Sessao autenticada ausente.' using errcode = '42501';
    end if;

    if app_private.current_app_role() <> 'admin' then
        raise exception 'Acesso restrito a administradores ativos.' using errcode = '42501';
    end if;

    if p_user_id is null then
        raise exception 'Usuario alvo ausente.' using errcode = '22023';
    end if;

    if v_email = '' or position('@' in v_email) = 0 then
        raise exception 'Informe um email valido.' using errcode = '22023';
    end if;

    select *
    into v_profile
    from public.profiles
    where id = p_user_id;

    if not found then
        raise exception 'Usuario nao encontrado.' using errcode = 'P0002';
    end if;

    begin
        update auth.users
        set
            email = v_email,
            raw_user_meta_data = coalesce(raw_user_meta_data, '{}'::jsonb)
                || jsonb_build_object(
                    'full_name', v_display_name,
                    'name', v_display_name
                ),
            email_confirmed_at = coalesce(email_confirmed_at, timezone('utc', now())),
            updated_at = timezone('utc', now())
        where id = p_user_id;
    exception
        when unique_violation then
            raise exception 'Ja existe uma conta com este email.' using errcode = '23505';
    end;

    if not found then
        raise exception 'Usuario nao encontrado.' using errcode = 'P0002';
    end if;

    update public.profiles
    set
        email = v_email,
        display_name = v_display_name,
        updated_at = timezone('utc', now())
    where id = p_user_id
    returning *
    into v_profile;

    return v_profile;
end;
$$;

revoke all on function app_private.rpc_admin_update_user(uuid, text, text) from public;
revoke all on function app_private.rpc_admin_update_user(uuid, text, text) from anon;
revoke all on function app_private.rpc_admin_update_user(uuid, text, text) from authenticated;
grant execute on function app_private.rpc_admin_update_user(uuid, text, text) to authenticated;

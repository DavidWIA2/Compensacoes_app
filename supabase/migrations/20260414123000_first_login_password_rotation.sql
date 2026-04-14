alter table public.profiles
add column if not exists must_change_password boolean not null default false;

create or replace function app_private.handle_auth_user_upsert()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_display_name text := coalesce(
        new.raw_user_meta_data ->> 'full_name',
        new.raw_user_meta_data ->> 'name',
        ''
    );
    v_existing_profiles integer := 0;
    v_password_changed boolean := false;
    v_should_update_password_flag boolean := false;
    v_must_change_password boolean := false;
begin
    if tg_op = 'INSERT' then
        select count(*)
        into v_existing_profiles
        from public.profiles;

        v_should_update_password_flag := true;
        v_must_change_password := v_existing_profiles > 0;
    elsif tg_op = 'UPDATE' then
        v_password_changed := new.encrypted_password is distinct from old.encrypted_password;
        v_should_update_password_flag := v_password_changed;
        if v_password_changed then
            v_must_change_password := auth.uid() is null or auth.uid() <> new.id;
        end if;
    end if;

    insert into public.profiles as profiles (id, email, display_name, must_change_password)
    values (
        new.id,
        coalesce(new.email, ''),
        v_display_name,
        v_must_change_password
    )
    on conflict (id) do update
    set
        email = excluded.email,
        display_name = case
            when excluded.display_name <> '' then excluded.display_name
            else profiles.display_name
        end,
        must_change_password = case
            when v_should_update_password_flag then excluded.must_change_password
            else profiles.must_change_password
        end,
        updated_at = timezone('utc', now());

    return new;
end;
$$;

drop trigger if exists on_auth_user_upsert on auth.users;
create trigger on_auth_user_upsert
after insert or update of email, raw_user_meta_data, encrypted_password on auth.users
for each row
execute function app_private.handle_auth_user_upsert();

create or replace function app_private.rpc_complete_password_change()
returns public.profiles
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_user_id uuid := auth.uid();
    v_profile public.profiles%rowtype;
begin
    if v_user_id is null then
        raise exception 'Sessao autenticada ausente.' using errcode = '42501';
    end if;

    update public.profiles
    set
        must_change_password = false,
        updated_at = timezone('utc', now())
    where id = v_user_id
    returning *
    into v_profile;

    if not found then
        raise exception 'Usuario nao encontrado.' using errcode = 'P0002';
    end if;

    return v_profile;
end;
$$;

revoke all on function app_private.rpc_complete_password_change() from public;
revoke all on function app_private.rpc_complete_password_change() from anon;
revoke all on function app_private.rpc_complete_password_change() from authenticated;
grant execute on function app_private.rpc_complete_password_change() to authenticated;

create schema if not exists app_private;

revoke all on schema app_private from public;
revoke all on schema app_private from anon;
revoke all on schema app_private from authenticated;

create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    email text not null default '',
    display_name text not null default '',
    role text not null default 'editor' check (role in ('viewer', 'editor', 'admin')),
    is_active boolean not null default false,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = timezone('utc', now());
    return new;
end;
$$;

create or replace function app_private.handle_auth_user_upsert()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.profiles as profiles (id, email, display_name)
    values (
        new.id,
        coalesce(new.email, ''),
        coalesce(
            new.raw_user_meta_data ->> 'full_name',
            new.raw_user_meta_data ->> 'name',
            ''
        )
    )
    on conflict (id) do update
    set
        email = excluded.email,
        display_name = case
            when excluded.display_name <> '' then excluded.display_name
            else profiles.display_name
        end,
        updated_at = timezone('utc', now());

    return new;
end;
$$;

drop trigger if exists trg_profiles_touch_updated_at on public.profiles;
create trigger trg_profiles_touch_updated_at
before update on public.profiles
for each row
execute function public.touch_updated_at();

drop trigger if exists on_auth_user_upsert on auth.users;
create trigger on_auth_user_upsert
after insert or update of email, raw_user_meta_data on auth.users
for each row
execute function app_private.handle_auth_user_upsert();

insert into public.profiles as profiles (id, email, display_name)
select
    users.id,
    coalesce(users.email, ''),
    coalesce(
        users.raw_user_meta_data ->> 'full_name',
        users.raw_user_meta_data ->> 'name',
        ''
    )
from auth.users as users
on conflict (id) do update
set
    email = excluded.email,
    display_name = case
        when excluded.display_name <> '' then excluded.display_name
        else profiles.display_name
    end,
    updated_at = timezone('utc', now());

create or replace function app_private.is_active_app_user()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.profiles
        where id = auth.uid()
          and is_active = true
    );
$$;

create or replace function app_private.current_app_role()
returns text
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(
        (
            select role
            from public.profiles
            where id = auth.uid()
              and is_active = true
        ),
        'blocked'
    );
$$;

create or replace function app_private.can_write_app_data()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select app_private.current_app_role() in ('editor', 'admin');
$$;

revoke all on function app_private.handle_auth_user_upsert() from public;
revoke all on function app_private.handle_auth_user_upsert() from anon;
revoke all on function app_private.handle_auth_user_upsert() from authenticated;

revoke all on function app_private.is_active_app_user() from public;
revoke all on function app_private.current_app_role() from public;
revoke all on function app_private.can_write_app_data() from public;

grant execute on function app_private.is_active_app_user() to authenticated;
grant execute on function app_private.current_app_role() to authenticated;
grant execute on function app_private.can_write_app_data() to authenticated;

alter table public.profiles enable row level security;

drop policy if exists profiles_select_self on public.profiles;
create policy profiles_select_self
on public.profiles
for select
to authenticated
using ((select auth.uid()) = id);

drop policy if exists profiles_admin_manage on public.profiles;
create policy profiles_admin_manage
on public.profiles
for all
to authenticated
using (app_private.current_app_role() = 'admin')
with check (app_private.current_app_role() = 'admin');

drop policy if exists meta_select_active_users on public.meta;
create policy meta_select_active_users
on public.meta
for select
to authenticated
using (app_private.is_active_app_user());

drop policy if exists meta_write_active_users on public.meta;
create policy meta_write_active_users
on public.meta
for all
to authenticated
using (app_private.can_write_app_data())
with check (app_private.can_write_app_data());

drop policy if exists workbooks_select_active_users on public.workbooks;
create policy workbooks_select_active_users
on public.workbooks
for select
to authenticated
using (app_private.is_active_app_user());

drop policy if exists workbooks_write_active_users on public.workbooks;
create policy workbooks_write_active_users
on public.workbooks
for all
to authenticated
using (app_private.can_write_app_data())
with check (app_private.can_write_app_data());

drop policy if exists records_select_active_users on public.records;
create policy records_select_active_users
on public.records
for select
to authenticated
using (app_private.is_active_app_user());

drop policy if exists records_write_active_users on public.records;
create policy records_write_active_users
on public.records
for all
to authenticated
using (app_private.can_write_app_data())
with check (app_private.can_write_app_data());

drop policy if exists plantios_select_active_users on public.plantios;
create policy plantios_select_active_users
on public.plantios
for select
to authenticated
using (app_private.is_active_app_user());

drop policy if exists plantios_write_active_users on public.plantios;
create policy plantios_write_active_users
on public.plantios
for all
to authenticated
using (app_private.can_write_app_data())
with check (app_private.can_write_app_data());

drop policy if exists audit_events_select_active_users on public.audit_events;
create policy audit_events_select_active_users
on public.audit_events
for select
to authenticated
using (app_private.is_active_app_user());

drop policy if exists audit_events_write_active_users on public.audit_events;
create policy audit_events_write_active_users
on public.audit_events
for all
to authenticated
using (app_private.can_write_app_data())
with check (app_private.can_write_app_data());

drop policy if exists tcras_select_active_users on public.tcras;
create policy tcras_select_active_users
on public.tcras
for select
to authenticated
using (app_private.is_active_app_user());

drop policy if exists tcras_write_active_users on public.tcras;
create policy tcras_write_active_users
on public.tcras
for all
to authenticated
using (app_private.can_write_app_data())
with check (app_private.can_write_app_data());

drop policy if exists tcra_eventos_select_active_users on public.tcra_eventos;
create policy tcra_eventos_select_active_users
on public.tcra_eventos
for select
to authenticated
using (app_private.is_active_app_user());

drop policy if exists tcra_eventos_write_active_users on public.tcra_eventos;
create policy tcra_eventos_write_active_users
on public.tcra_eventos
for all
to authenticated
using (app_private.can_write_app_data())
with check (app_private.can_write_app_data());

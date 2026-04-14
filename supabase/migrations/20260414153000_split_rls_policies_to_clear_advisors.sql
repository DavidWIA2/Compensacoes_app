drop policy if exists profiles_select_self on public.profiles;
drop policy if exists profiles_admin_manage on public.profiles;

create policy profiles_select_self_or_admin
on public.profiles
for select
to authenticated
using (
  ((select auth.uid()) = id)
  or ((select app_private.current_app_role()) = 'admin')
);

create policy profiles_admin_insert
on public.profiles
for insert
to authenticated
with check ((select app_private.current_app_role()) = 'admin');

create policy profiles_admin_update
on public.profiles
for update
to authenticated
using ((select app_private.current_app_role()) = 'admin')
with check ((select app_private.current_app_role()) = 'admin');

create policy profiles_admin_delete
on public.profiles
for delete
to authenticated
using ((select app_private.current_app_role()) = 'admin');

drop policy if exists meta_write_active_users on public.meta;

create policy meta_insert_active_users
on public.meta
for insert
to authenticated
with check ((select app_private.can_write_app_data()));

create policy meta_update_active_users
on public.meta
for update
to authenticated
using ((select app_private.can_write_app_data()))
with check ((select app_private.can_write_app_data()));

create policy meta_delete_active_users
on public.meta
for delete
to authenticated
using ((select app_private.can_write_app_data()));

drop policy if exists workbooks_write_active_users on public.workbooks;

create policy workbooks_insert_active_users
on public.workbooks
for insert
to authenticated
with check ((select app_private.can_write_app_data()));

create policy workbooks_update_active_users
on public.workbooks
for update
to authenticated
using ((select app_private.can_write_app_data()))
with check ((select app_private.can_write_app_data()));

create policy workbooks_delete_active_users
on public.workbooks
for delete
to authenticated
using ((select app_private.can_write_app_data()));

drop policy if exists records_write_active_users on public.records;

create policy records_insert_active_users
on public.records
for insert
to authenticated
with check ((select app_private.can_write_app_data()));

create policy records_update_active_users
on public.records
for update
to authenticated
using ((select app_private.can_write_app_data()))
with check ((select app_private.can_write_app_data()));

create policy records_delete_active_users
on public.records
for delete
to authenticated
using ((select app_private.can_write_app_data()));

drop policy if exists plantios_write_active_users on public.plantios;

create policy plantios_insert_active_users
on public.plantios
for insert
to authenticated
with check ((select app_private.can_write_app_data()));

create policy plantios_update_active_users
on public.plantios
for update
to authenticated
using ((select app_private.can_write_app_data()))
with check ((select app_private.can_write_app_data()));

create policy plantios_delete_active_users
on public.plantios
for delete
to authenticated
using ((select app_private.can_write_app_data()));

drop policy if exists audit_events_write_active_users on public.audit_events;

create policy audit_events_insert_active_users
on public.audit_events
for insert
to authenticated
with check ((select app_private.can_write_app_data()));

create policy audit_events_update_active_users
on public.audit_events
for update
to authenticated
using ((select app_private.can_write_app_data()))
with check ((select app_private.can_write_app_data()));

create policy audit_events_delete_active_users
on public.audit_events
for delete
to authenticated
using ((select app_private.can_write_app_data()));

drop policy if exists tcras_write_active_users on public.tcras;

create policy tcras_insert_active_users
on public.tcras
for insert
to authenticated
with check ((select app_private.can_write_app_data()));

create policy tcras_update_active_users
on public.tcras
for update
to authenticated
using ((select app_private.can_write_app_data()))
with check ((select app_private.can_write_app_data()));

create policy tcras_delete_active_users
on public.tcras
for delete
to authenticated
using ((select app_private.can_write_app_data()));

drop policy if exists tcra_eventos_write_active_users on public.tcra_eventos;

create policy tcra_eventos_insert_active_users
on public.tcra_eventos
for insert
to authenticated
with check ((select app_private.can_write_app_data()));

create policy tcra_eventos_update_active_users
on public.tcra_eventos
for update
to authenticated
using ((select app_private.can_write_app_data()))
with check ((select app_private.can_write_app_data()));

create policy tcra_eventos_delete_active_users
on public.tcra_eventos
for delete
to authenticated
using ((select app_private.can_write_app_data()));

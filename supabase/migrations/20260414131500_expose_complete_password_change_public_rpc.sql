create or replace function public.rpc_complete_password_change()
returns public.profiles
language sql
security definer
set search_path = ''
as $$
    select app_private.rpc_complete_password_change();
$$;

revoke all on function public.rpc_complete_password_change() from public;
revoke all on function public.rpc_complete_password_change() from anon;
revoke all on function public.rpc_complete_password_change() from authenticated;
grant execute on function public.rpc_complete_password_change() to authenticated;

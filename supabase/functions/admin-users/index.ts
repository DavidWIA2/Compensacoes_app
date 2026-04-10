import "jsr:@supabase/functions-js/edge-runtime.d.ts";

import {
  activeAdminCount,
  corsHeaders,
  errorResponse,
  getCurrentAdmin,
  HttpError,
  jsonResponse,
  listProfileRows,
  normalizeRole,
  normalizeUserId,
  normalizeUserPayload,
  upsertProfile,
} from "../_shared/admin_helpers.ts";

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { service, user: currentUser } = await getCurrentAdmin(req);

    if (req.method === "GET") {
      return jsonResponse({
        users: await listProfileRows(service),
      });
    }

    if (req.method !== "POST") {
      throw new HttpError(405, "Metodo nao suportado.");
    }

    const payload = await req.json();
    const action = String(payload?.action ?? "").trim().toLowerCase();

    if (action === "create") {
      const newUser = normalizeUserPayload(payload);
      const { data: createdUserData, error: createError } = await service.auth.admin.createUser({
        email: newUser.email,
        password: newUser.password,
        email_confirm: true,
        user_metadata: {
          full_name: newUser.displayName,
          name: newUser.displayName,
        },
        app_metadata: {
          role: newUser.role,
        },
      });

      if (createError || !createdUserData.user) {
        throw new HttpError(400, `Falha ao cadastrar usuario: ${createError?.message ?? "sem usuario"}`);
      }

      let profile;
      try {
        profile = await upsertProfile(service, {
          id: createdUserData.user.id,
          email: newUser.email,
          display_name: newUser.displayName,
          role: newUser.role,
          is_active: newUser.isActive,
        });
      } catch (error) {
        await service.auth.admin.deleteUser(createdUserData.user.id);
        throw error;
      }

      return jsonResponse({ ok: true, user: profile });
    }

    if (action === "set_active") {
      const userId = normalizeUserId(payload?.user_id);
      const nextActive = Boolean(payload?.is_active);
      const { data: existing, error: existingError } = await service
        .from("profiles")
        .select("id, email, display_name, role, is_active, created_at, updated_at")
        .eq("id", userId)
        .maybeSingle();

      if (existingError) {
        throw new HttpError(500, `Falha ao localizar usuario: ${existingError.message}`);
      }
      if (!existing) {
        throw new HttpError(404, "Usuario nao encontrado.");
      }
      if (existing.id === currentUser.id && !nextActive) {
        throw new HttpError(400, "Voce nao pode desativar o proprio usuario.");
      }
      if (existing.role === "admin" && existing.is_active && !nextActive) {
        const adminCount = await activeAdminCount(service);
        if (adminCount <= 1) {
          throw new HttpError(400, "Nao e possivel desativar o ultimo administrador ativo.");
        }
      }

      const { error: updateError } = await service
        .from("profiles")
        .update({ is_active: nextActive })
        .eq("id", userId);

      if (updateError) {
        throw new HttpError(500, `Falha ao atualizar o status do usuario: ${updateError.message}`);
      }

      const refreshed = await upsertProfile(service, {
        id: existing.id,
        email: existing.email ?? "",
        display_name: existing.display_name ?? "",
        role: normalizeRole(existing.role),
        is_active: nextActive,
      });
      return jsonResponse({ ok: true, user: refreshed });
    }

    if (action === "set_role") {
      const userId = normalizeUserId(payload?.user_id);
      const nextRole = normalizeRole(payload?.role);

      const { data: existing, error: existingError } = await service
        .from("profiles")
        .select("id, email, display_name, role, is_active, created_at, updated_at")
        .eq("id", userId)
        .maybeSingle();

      if (existingError) {
        throw new HttpError(500, `Falha ao localizar usuario: ${existingError.message}`);
      }
      if (!existing) {
        throw new HttpError(404, "Usuario nao encontrado.");
      }
      if (existing.id === currentUser.id && normalizeRole(existing.role) !== nextRole) {
        throw new HttpError(400, "Voce nao pode alterar o perfil da propria conta por esta tela.");
      }
      if (existing.role === "admin" && existing.is_active && nextRole !== "admin") {
        const adminCount = await activeAdminCount(service);
        if (adminCount <= 1) {
          throw new HttpError(400, "Nao e possivel rebaixar o ultimo administrador ativo.");
        }
      }

      const refreshed = await upsertProfile(service, {
        id: existing.id,
        email: existing.email ?? "",
        display_name: existing.display_name ?? "",
        role: nextRole,
        is_active: Boolean(existing.is_active),
      });
      return jsonResponse({ ok: true, user: refreshed });
    }

    if (action === "delete") {
      const userId = normalizeUserId(payload?.user_id);
      if (userId === currentUser.id) {
        throw new HttpError(400, "Voce nao pode excluir o proprio usuario.");
      }

      const { data: existing, error: existingError } = await service
        .from("profiles")
        .select("id, role, is_active")
        .eq("id", userId)
        .maybeSingle();
      if (existingError) {
        throw new HttpError(500, `Falha ao localizar usuario para exclusao: ${existingError.message}`);
      }
      if (!existing) {
        throw new HttpError(404, "Usuario nao encontrado.");
      }
      if (existing.role === "admin" && existing.is_active) {
        const adminCount = await activeAdminCount(service);
        if (adminCount <= 1) {
          throw new HttpError(400, "Nao e possivel excluir o ultimo administrador ativo.");
        }
      }

      const { error: deleteError } = await service.auth.admin.deleteUser(userId);
      if (deleteError) {
        throw new HttpError(500, `Falha ao excluir usuario: ${deleteError.message}`);
      }
      return jsonResponse({ ok: true });
    }

    if (action === "reset_password") {
      const userId = normalizeUserId(payload?.user_id);
      const password = String(payload?.password ?? "");
      if (password.length < 8) {
        throw new HttpError(400, "A senha precisa ter pelo menos 8 caracteres.");
      }

      const { data: existing, error: existingError } = await service
        .from("profiles")
        .select("id, email, display_name, role, is_active, created_at, updated_at")
        .eq("id", userId)
        .maybeSingle();
      if (existingError) {
        throw new HttpError(500, `Falha ao localizar usuario: ${existingError.message}`);
      }
      if (!existing) {
        throw new HttpError(404, "Usuario nao encontrado.");
      }

      const { data: updatedUserData, error: updateError } = await service.auth.admin.updateUserById(userId, {
        password,
      });
      if (updateError || !updatedUserData.user) {
        throw new HttpError(500, `Falha ao redefinir a senha: ${updateError?.message ?? "sem usuario"}`);
      }

      const refreshed = await upsertProfile(service, {
        id: existing.id,
        email: existing.email ?? "",
        display_name: existing.display_name ?? "",
        role: normalizeRole(existing.role),
        is_active: Boolean(existing.is_active),
      });
      return jsonResponse({ ok: true, user: refreshed });
    }

    throw new HttpError(400, "Acao administrativa invalida.");
  } catch (error) {
    return errorResponse(error);
  }
});

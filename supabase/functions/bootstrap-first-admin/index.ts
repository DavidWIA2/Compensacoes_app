import "jsr:@supabase/functions-js/edge-runtime.d.ts";

import {
  corsHeaders,
  createServiceClient,
  ensureBootstrapAllowed,
  errorResponse,
  HttpError,
  jsonResponse,
  normalizeUserPayload,
  upsertProfile,
} from "../_shared/admin_helpers.ts";

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const service = createServiceClient();
    const profileCount = await ensureBootstrapAllowed(service);

    if (req.method === "GET") {
      return jsonResponse({
        allowed: profileCount === 0,
        profile_count: profileCount,
        message: profileCount === 0
          ? "Nenhum usuario configurado. O primeiro administrador pode ser criado."
          : "O bootstrap inicial ja foi concluido.",
      });
    }

    if (req.method !== "POST") {
      throw new HttpError(405, "Metodo nao suportado.");
    }

    if (profileCount > 0) {
      throw new HttpError(403, "O primeiro administrador ja foi criado neste ambiente.");
    }

    const payload = normalizeUserPayload(await req.json());
    const { data: createdUserData, error: createError } = await service.auth.admin.createUser({
      email: payload.email,
      password: payload.password,
      email_confirm: true,
      user_metadata: {
        full_name: payload.displayName,
        name: payload.displayName,
      },
      app_metadata: {
        role: "admin",
      },
    });

    if (createError || !createdUserData.user) {
      throw new HttpError(400, `Falha ao criar o primeiro administrador: ${createError?.message ?? "sem usuario"}`);
    }

    let profile;
    try {
      profile = await upsertProfile(service, {
        id: createdUserData.user.id,
        email: payload.email,
        display_name: payload.displayName,
        role: "admin",
        is_active: true,
      });
    } catch (error) {
      await service.auth.admin.deleteUser(createdUserData.user.id);
      throw error;
    }

    return jsonResponse({
      ok: true,
      user: profile,
    });
  } catch (error) {
    return errorResponse(error);
  }
});

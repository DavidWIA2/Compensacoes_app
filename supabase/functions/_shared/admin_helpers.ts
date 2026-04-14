import "jsr:@supabase/functions-js/edge-runtime.d.ts";

import { createClient, type User } from "npm:@supabase/supabase-js@2";

export const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

export type ProfileRow = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export const PASSWORD_POLICY_SUMMARY =
  "12+ caracteres, com letra maiuscula, minuscula, numero e simbolo";

export class HttpError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function requireEnv(name: string): string {
  const value = (Deno.env.get(name) ?? "").trim();
  if (!value) {
    throw new HttpError(500, `Variavel obrigatoria ausente: ${name}`);
  }
  return value;
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...corsHeaders,
      "Content-Type": "application/json",
    },
  });
}

export function errorResponse(error: unknown): Response {
  if (error instanceof HttpError) {
    return jsonResponse({ error: error.message }, error.status);
  }
  console.error("admin-function-error", error);
  return jsonResponse({ error: "Falha interna no backend administrativo." }, 500);
}

export function createServiceClient() {
  return createClient(
    requireEnv("SUPABASE_URL"),
    requireEnv("SUPABASE_SERVICE_ROLE_KEY"),
  );
}

export function getBearerToken(req: Request): string {
  const authHeader = req.headers.get("Authorization") ?? req.headers.get("authorization") ?? "";
  const normalized = authHeader.replace(/^Bearer\s+/i, "").trim();
  if (!normalized) {
    throw new HttpError(401, "Sessao autenticada ausente.");
  }
  return normalized;
}

export async function getCurrentAdmin(req: Request): Promise<{
  service: ReturnType<typeof createServiceClient>;
  user: User;
  profile: ProfileRow;
}> {
  const token = getBearerToken(req);
  const service = createServiceClient();

  const { data: userData, error: userError } = await service.auth.getUser(token);
  if (userError || !userData.user) {
    throw new HttpError(401, "Token de autenticacao invalido.");
  }

  const { data: profile, error: profileError } = await service
    .from("profiles")
    .select("id, email, display_name, role, is_active, created_at, updated_at")
    .eq("id", userData.user.id)
    .maybeSingle();

  if (profileError) {
    throw new HttpError(500, `Falha ao validar o perfil administrativo: ${profileError.message}`);
  }
  if (!profile || !profile.is_active || profile.role !== "admin") {
    throw new HttpError(403, "Acesso restrito a administradores ativos.");
  }

  return {
    service,
    user: userData.user,
    profile: profile as ProfileRow,
  };
}

export async function listProfileRows(service: ReturnType<typeof createServiceClient>): Promise<ProfileRow[]> {
  const { data, error } = await service
    .from("profiles")
    .select("id, email, display_name, role, is_active, created_at, updated_at")
    .order("created_at", { ascending: true });
  if (error) {
    throw new HttpError(500, `Falha ao listar usuarios: ${error.message}`);
  }
  return (data ?? []) as ProfileRow[];
}

export async function activeAdminCount(service: ReturnType<typeof createServiceClient>): Promise<number> {
  const { count, error } = await service
    .from("profiles")
    .select("id", { count: "exact", head: true })
    .eq("role", "admin")
    .eq("is_active", true);
  if (error) {
    throw new HttpError(500, `Falha ao contar administradores ativos: ${error.message}`);
  }
  return Number(count ?? 0);
}

export function normalizeRole(value: unknown): "viewer" | "editor" | "admin" {
  const normalized = String(value ?? "editor").trim().toLowerCase();
  if (normalized === "viewer" || normalized === "editor" || normalized === "admin") {
    return normalized;
  }
  throw new HttpError(400, "Perfil invalido. Use viewer, editor ou admin.");
}

export function passwordValidationError(password: string): string | null {
  const normalized = String(password ?? "");
  const requirements: string[] = [];

  if (normalized.length < 12) {
    requirements.push("pelo menos 12 caracteres");
  }
  if (!/[a-z]/.test(normalized)) {
    requirements.push("uma letra minuscula");
  }
  if (!/[A-Z]/.test(normalized)) {
    requirements.push("uma letra maiuscula");
  }
  if (!/[0-9]/.test(normalized)) {
    requirements.push("um numero");
  }
  if (!/[^A-Za-z0-9\s]/.test(normalized)) {
    requirements.push("um simbolo");
  }

  if (requirements.length === 0) {
    return null;
  }
  if (requirements.length === 1) {
    return `A senha precisa ter ${requirements[0]}.`;
  }
  const lastRequirement = requirements.at(-1) ?? "";
  return `A senha precisa ter ${requirements.slice(0, -1).join(", ")} e ${lastRequirement}.`;
}

export function normalizeUserPayload(payload: unknown): {
  email: string;
  password: string;
  displayName: string;
  role: "viewer" | "editor" | "admin";
  isActive: boolean;
} {
  const data = typeof payload === "object" && payload !== null ? payload as Record<string, unknown> : {};
  const email = String(data.email ?? "").trim().toLowerCase();
  const password = String(data.password ?? "");
  const displayName = String(data.display_name ?? "").trim();
  const role = normalizeRole(data.role ?? "editor");
  const isActive = Boolean(data.is_active ?? true);

  if (!email || !email.includes("@")) {
    throw new HttpError(400, "Informe um email valido.");
  }
  const passwordError = passwordValidationError(password);
  if (passwordError) {
    throw new HttpError(400, passwordError);
  }
  return { email, password, displayName, role, isActive };
}

export function normalizeUserUpdatePayload(payload: unknown): {
  email: string;
  displayName: string;
} {
  const data = typeof payload === "object" && payload !== null ? payload as Record<string, unknown> : {};
  const email = String(data.email ?? "").trim().toLowerCase();
  const displayName = String(data.display_name ?? "").trim();

  if (!email || !email.includes("@")) {
    throw new HttpError(400, "Informe um email valido.");
  }
  return { email, displayName };
}

export function normalizeUserId(value: unknown): string {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    throw new HttpError(400, "Usuario alvo ausente.");
  }
  return normalized;
}

export async function upsertProfile(
  service: ReturnType<typeof createServiceClient>,
  profile: {
    id: string;
    email: string;
    display_name: string;
    role: "viewer" | "editor" | "admin";
    is_active: boolean;
  },
): Promise<ProfileRow> {
  const { error } = await service.from("profiles").upsert(profile);
  if (error) {
    throw new HttpError(500, `Falha ao salvar o perfil do usuario: ${error.message}`);
  }

  const { data, error: selectError } = await service
    .from("profiles")
    .select("id, email, display_name, role, is_active, created_at, updated_at")
    .eq("id", profile.id)
    .single();

  if (selectError || !data) {
    throw new HttpError(500, "O perfil do usuario foi salvo, mas nao pode ser relido.");
  }
  return data as ProfileRow;
}

export async function ensureBootstrapAllowed(service: ReturnType<typeof createServiceClient>): Promise<number> {
  const { count, error } = await service.from("profiles").select("id", { count: "exact", head: true });
  if (error) {
    throw new HttpError(500, `Falha ao verificar bootstrap administrativo: ${error.message}`);
  }
  return Number(count ?? 0);
}

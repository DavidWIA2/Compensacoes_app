import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
};

const supabaseUrl = (Deno.env.get("SUPABASE_URL") ?? "https://yonvcnnkewzoqwnnmcdx.supabase.co").trim();
const supabasePublishableKey = (
  Deno.env.get("SUPABASE_PUBLISHABLE_KEY") ?? "sb_publishable_89kyRD3GfnaLBZmwnlkA_g_4a_k5_5R"
).trim();
const passwordPolicySummary =
  "12+ caracteres, com letra maiuscula, minuscula, numero e simbolo";

function renderPage(): string {
  return `<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Redefinir senha - Compensacoes</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f3f6fb;
      --card: #ffffff;
      --card-border: #d7ddea;
      --text: #162032;
      --muted: #5f6f8d;
      --primary: #1d66f2;
      --primary-strong: #1249b8;
      --success-bg: #e8f7ef;
      --success-text: #167547;
      --warning-bg: #fff3d9;
      --warning-text: #8a5c00;
      --error-bg: #fde8ea;
      --error-text: #a12234;
      --input-bg: #ffffff;
      --input-border: #c5d0e5;
      --shadow: 0 14px 34px rgba(16, 24, 40, 0.08);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #11161f;
        --card: #1a2230;
        --card-border: #2c3850;
        --text: #f4f7fb;
        --muted: #b0bdd5;
        --primary: #61a5ff;
        --primary-strong: #8bbcff;
        --success-bg: #143423;
        --success-text: #8fe1b0;
        --warning-bg: #3a2d0d;
        --warning-text: #ffd978;
        --error-bg: #43202a;
        --error-text: #ffb6c1;
        --input-bg: #111827;
        --input-border: #41506a;
        --shadow: 0 18px 36px rgba(0, 0, 0, 0.32);
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background:
        radial-gradient(circle at top, rgba(29, 102, 242, 0.10), transparent 32%),
        var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .card {
      width: min(520px, 100%);
      background: var(--card);
      border: 1px solid var(--card-border);
      border-radius: 18px;
      box-shadow: var(--shadow);
      padding: 28px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 1.8rem;
      line-height: 1.15;
    }
    p {
      margin: 0;
      line-height: 1.55;
      color: var(--muted);
    }
    .block {
      margin-top: 18px;
    }
    .status {
      display: none;
      border-radius: 12px;
      padding: 12px 14px;
      font-size: 0.96rem;
      line-height: 1.45;
    }
    .status.show { display: block; }
    .status.info { background: rgba(29, 102, 242, 0.10); color: var(--primary-strong); }
    .status.success { background: var(--success-bg); color: var(--success-text); }
    .status.warning { background: var(--warning-bg); color: var(--warning-text); }
    .status.error { background: var(--error-bg); color: var(--error-text); }
    label {
      display: block;
      margin-bottom: 6px;
      font-weight: 600;
      font-size: 0.95rem;
    }
    input {
      width: 100%;
      border-radius: 12px;
      border: 1px solid var(--input-border);
      background: var(--input-bg);
      color: var(--text);
      padding: 12px 14px;
      font-size: 1rem;
      outline: none;
    }
    input:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(29, 102, 242, 0.14);
    }
    button {
      border: none;
      border-radius: 12px;
      padding: 12px 16px;
      font-size: 1rem;
      font-weight: 700;
      cursor: pointer;
      background: var(--primary);
      color: white;
      width: 100%;
    }
    button:disabled {
      opacity: 0.65;
      cursor: default;
    }
    .muted {
      font-size: 0.92rem;
      color: var(--muted);
    }
    #reset-panel { display: none; }
    #reset-panel.show { display: block; }
    .field + .field { margin-top: 14px; }
  </style>
</head>
<body>
  <main class="card">
    <h1>Redefinir senha</h1>
    <p>Use esta tela para concluir a troca de senha do seu acesso corporativo ao app de Compensacoes.</p>

    <div id="status" class="status info show block">
      Validando o link de recuperacao...
    </div>

    <section id="reset-panel" class="block" aria-live="polite">
      <form id="reset-form">
        <div class="field">
          <label for="password">Nova senha</label>
          <input id="password" type="password" placeholder="Digite a nova senha" autocomplete="new-password" />
        </div>
        <div class="field">
          <label for="confirm-password">Confirmar nova senha</label>
          <input id="confirm-password" type="password" placeholder="Repita a nova senha" autocomplete="new-password" />
        </div>
        <div class="block muted">
          A senha precisa seguir: ${passwordPolicySummary}.
        </div>
        <div class="block">
          <button id="submit-button" type="submit">Atualizar senha</button>
        </div>
      </form>
    </section>
  </main>

  <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
  <script>
    const SUPABASE_URL = ${JSON.stringify(supabaseUrl)};
    const SUPABASE_PUBLISHABLE_KEY = ${JSON.stringify(supabasePublishableKey)};
    const statusEl = document.getElementById("status");
    const panelEl = document.getElementById("reset-panel");
    const formEl = document.getElementById("reset-form");
    const passwordEl = document.getElementById("password");
    const confirmPasswordEl = document.getElementById("confirm-password");
    const submitButton = document.getElementById("submit-button");

    function passwordValidationError(password) {
      const requirements = [];
      if (password.length < 12) {
        requirements.push("pelo menos 12 caracteres");
      }
      if (!/[a-z]/.test(password)) {
        requirements.push("uma letra minuscula");
      }
      if (!/[A-Z]/.test(password)) {
        requirements.push("uma letra maiuscula");
      }
      if (!/[0-9]/.test(password)) {
        requirements.push("um numero");
      }
      if (!/[^A-Za-z0-9\s]/.test(password)) {
        requirements.push("um simbolo");
      }
      if (requirements.length === 0) {
        return "";
      }
      if (requirements.length === 1) {
        return "A nova senha precisa ter " + requirements[0] + ".";
      }
      return (
        "A nova senha precisa ter " +
        requirements.slice(0, -1).join(", ") +
        " e " +
        requirements[requirements.length - 1] +
        "."
      );
    }

    function showStatus(kind, message) {
      statusEl.className = "status show block " + kind;
      statusEl.textContent = message;
    }

    function showPanel(visible) {
      panelEl.className = visible ? "block show" : "block";
    }

    const supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
      auth: {
        persistSession: false,
        autoRefreshToken: false,
        detectSessionInUrl: true,
      },
    });

    let recoveryReady = false;

    supabase.auth.onAuthStateChange((event, session) => {
      if (event === "PASSWORD_RECOVERY") {
        recoveryReady = true;
        showPanel(true);
        showStatus("info", "Link validado. Defina sua nova senha para concluir o acesso.");
      } else if (event === "SIGNED_OUT") {
        if (!recoveryReady) {
          showPanel(false);
        }
      } else if (session && !recoveryReady) {
        recoveryReady = true;
        showPanel(true);
        showStatus("info", "Sessao de recuperacao recebida. Defina sua nova senha.");
      }
    });

    async function initializeRecovery() {
      try {
        const { data, error } = await supabase.auth.getSession();
        if (error) {
          throw error;
        }
        if (data && data.session) {
          recoveryReady = true;
          showPanel(true);
          showStatus("info", "Sessao de recuperacao validada. Defina sua nova senha.");
          return;
        }
        showStatus(
          "warning",
          "Este link nao esta mais valido ou a recuperacao expirou. Solicite um novo e-mail pelo app ou peca ajuda a um administrador."
        );
      } catch (error) {
        showStatus(
          "error",
          "Nao foi possivel validar este link de recuperacao. Solicite um novo e-mail ou peca ajuda a um administrador."
        );
      }
    }

    formEl.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!recoveryReady) {
        showStatus("warning", "A recuperacao ainda nao foi validada. Aguarde a tela carregar.");
        return;
      }

      const password = passwordEl.value;
      const confirmPassword = confirmPasswordEl.value;

      const passwordError = passwordValidationError(password);
      if (passwordError) {
        showStatus("warning", passwordError);
        passwordEl.focus();
        return;
      }
      if (password !== confirmPassword) {
        showStatus("warning", "A confirmacao da senha nao confere.");
        confirmPasswordEl.focus();
        return;
      }

      submitButton.disabled = true;
      showStatus("info", "Atualizando sua senha...");
      try {
        const { error } = await supabase.auth.updateUser({ password });
        if (error) {
          throw error;
        }
        showStatus(
          "success",
          "Senha atualizada com sucesso. Voce ja pode voltar ao app e entrar com a nova senha."
        );
        showPanel(false);
        await supabase.auth.signOut();
      } catch (error) {
        const message = error && error.message ? error.message : "Falha ao atualizar a senha.";
        showStatus("error", message);
      } finally {
        submitButton.disabled = false;
      }
    });

    initializeRecovery();
  </script>
</body>
</html>`;
}

Deno.serve((_req: Request) => {
  return new Response(renderPage(), {
    headers: {
      ...corsHeaders,
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
});

// La ÚNICA URL que necesitas (El Webhook de n8n)
// url de test
//const N8N_WEBHOOK_URL = "http://localhost:5678/webhook-test/4ae97e52-38b7-46e4-bd13-ed5a4d65362c";
// url de producción
const N8N_WEBHOOK_URL = "http://localhost:5678/webhook/4ae97e52-38b7-46e4-bd13-ed5a4d65362c";
const statusDiv = document.getElementById("status");

// 1. Botón Actualizar Sesión -> Envía cookies_raw a n8n
document.getElementById("btnActualizarCookie").addEventListener("click", async () => {
  statusDiv.style.color = "#0284c7";
  statusDiv.innerText = "Capturando sesión de SECOP...";

  chrome.cookies.getAll({ domain: "community.secop.gov.co" }, async (cookies) => {
    if (!cookies || cookies.length === 0) {
      statusDiv.style.color = "#dc2626";
      statusDiv.innerText = "❌ No hay sesión activa en SECOP.";
      return;
    }

    const rawCookies = cookies.map(c => `${c.name}=${c.value}`).join("; ");

    try {
      const resp = await fetch(N8N_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cookies_raw: rawCookies })
      });

      if (resp.ok) {
        statusDiv.style.color = "#16a34a";
        statusDiv.innerText = "✅ ¡Sesión guardada en el sistema!";
      } else {
        statusDiv.style.color = "#dc2626";
        statusDiv.innerText = "❌ Error al guardar sesión.";
      }
    } catch (err) {
      statusDiv.style.color = "#dc2626";
      statusDiv.innerText = "❌ Error conectando con n8n.";
    }
  });
});

// 2. Botón Descargar -> Envía solo url a n8n
document.getElementById("btnDescargar").addEventListener("click", async () => {
  const url = document.getElementById("txtUrl").value.trim();

  if (!url) {
    statusDiv.style.color = "#dc2626";
    statusDiv.innerText = "❌ Ingresa una URL válida.";
    return;
  }

  statusDiv.style.color = "#0284c7";
  statusDiv.innerText = "Enviando orden de descarga a n8n...";

  try {
    const response = await fetch(N8N_WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url })
    });

    const data = await response.json();

    if (response.ok) {
      statusDiv.style.color = "#16a34a";
      statusDiv.innerText = `✅ ¡Éxito! Proceso finalizado.`;
      document.getElementById("txtUrl").value = "";
      document.getElementById("txtUrl").focus();
    } else {
      statusDiv.style.color = "#dc2626";
      statusDiv.innerText = `❌ Error en el proceso.`;
    }
  } catch (err) {
    statusDiv.style.color = "#dc2626";
    statusDiv.innerText = "❌ Error conectando con n8n.";
  }
});
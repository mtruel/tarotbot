const log = document.getElementById("console-log");
const form = document.getElementById("console-form");
const input = document.getElementById("console-input");
const csrf = form.querySelector('input[name="csrf"]').value;

function addMessage(kind, text, view) {
  const wrapper = document.createElement("div");
  wrapper.className = "console-message console-" + kind;
  const pre = document.createElement("pre");
  pre.textContent = text || "";
  wrapper.appendChild(pre);
  if (view) {
    wrapper.appendChild(renderView(view));
  }
  log.appendChild(wrapper);
  log.scrollTop = log.scrollHeight;
}

function renderView(view) {
  const container = document.createElement("div");
  container.className = "console-view";
  for (const item of view.items) {
    if (item.type === "button") {
      const button = document.createElement("button");
      button.textContent = item.label;
      button.disabled = item.disabled;
      button.addEventListener("click", () => {
        post({
          session_id: "debug",
          interaction: { message_id: view.message_id, item_id: item.id, values: [] },
        });
      });
      container.appendChild(button);
    } else if (item.type === "select") {
      const select = document.createElement("select");
      select.multiple = item.max_values > 1;
      select.size = Math.min(item.options.length, 6);
      for (const option of item.options) {
        const element = document.createElement("option");
        element.value = option.value;
        element.textContent = option.emoji ? option.emoji + " " + option.label : option.label;
        select.appendChild(element);
      }
      const button = document.createElement("button");
      button.textContent = "Valider " + (item.placeholder || "");
      button.addEventListener("click", () => {
        const values = Array.from(select.selectedOptions).map((option) => option.value);
        post({
          session_id: "debug",
          interaction: { message_id: view.message_id, item_id: item.id, values },
        });
      });
      container.appendChild(select);
      container.appendChild(button);
    }
  }
  return container;
}

async function post(payload) {
  const response = await fetch("/debug/command", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    addMessage("system", "Erreur " + response.status + " : " + (await response.text()));
    return;
  }
  const data = await response.json();
  for (const message of data.messages) {
    addMessage(message.kind, message.text, message.view);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  addMessage("user", text);
  input.value = "";
  await post({ session_id: "debug", text });
});

(() => {
  const form = document.getElementById("game-form");
  if (!form) return;

  const players = [...form.querySelectorAll('input[name="joueurs"]')];
  const taker = form.elements.namedItem("preneur");
  const partner = form.elements.namedItem("partenaire");
  const partnerField = document.getElementById("partner-field");
  const nativeRoles = document.getElementById("native-roles");
  const touchRoles = document.getElementById("touch-roles");
  const takerPicker = document.getElementById("taker-picker");
  const partnerPicker = document.getElementById("partner-picker");
  const takerSummary = document.getElementById("taker-summary");
  const partnerSummary = document.getElementById("partner-summary");
  const takerChoices = document.getElementById("taker-choices");
  const partnerChoices = document.getElementById("partner-choices");
  const misereChoices = form.querySelector('input[name="miseres"]')?.closest(".choice-grid");
  const count = document.getElementById("player-count");
  const defenders = document.getElementById("defenders");
  const search = document.getElementById("player-search");
  const searchLabel = document.getElementById("player-search-label");
  const noResults = document.getElementById("player-no-results");
  const preview = document.getElementById("score-preview");

  function normalize(value) {
    return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("fr");
  }

  function filterPlayers() {
    const query = normalize(search.value.trim());
    let visible = 0;
    for (const input of players) {
      const label = input.closest("label");
      label.hidden = Boolean(query) && !input.checked && !normalize(input.value).includes(query);
      if (!label.hidden) visible++;
    }
    noResults.hidden = visible !== 0;
  }

  function syncOptions(select, names, previous) {
    select.replaceChildren(select.options[0]);
    for (const name of names) select.add(new Option(name, name));
    select.value = names.includes(previous) ? previous : "";
  }

  function syncChoices(container, name, names, chosen, includeAlone = false) {
    container.replaceChildren();
    for (const value of includeAlone ? ["", ...names] : names) {
      const label = document.createElement("label");
      label.className = "choice";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = name;
      input.value = value;
      input.checked = value === chosen;
      const text = document.createElement("span");
      text.textContent = value || "Aucun · joue seul";
      label.append(input, text);
      container.append(label);
    }
  }

  function updateRoles() {
    const selected = players.filter((input) => input.checked).map((input) => input.value);
    count.textContent = `${selected.length} joueur${selected.length > 1 ? "s" : ""} sélectionné${selected.length > 1 ? "s" : ""} / 3 à 5`;
    count.classList.toggle("invalid", selected.length < 3 || selected.length > 5);
    for (const input of players) input.disabled = !input.checked && selected.length >= 5;

    const previousTaker = taker.value;
    const previousPartner = partner.value;
    syncOptions(taker, selected, previousTaker);
    const partners = selected.filter((name) => name !== taker.value);
    syncOptions(partner, selected.length === 5 ? partners : [], previousPartner);
    partner.disabled = selected.length !== 5;
    partnerField.hidden = partner.disabled;
    partnerPicker.hidden = partner.disabled;
    takerSummary.textContent = taker.value || "Choisir un joueur…";
    partnerSummary.textContent = partner.value || "Aucun · joue seul";
    syncChoices(takerChoices, "preneur_choice", selected, taker.value);
    syncChoices(partnerChoices, "partenaire_choice", partners, partner.value, true);

    if (misereChoices) {
      const checked = new Set(
        [...misereChoices.querySelectorAll('input[name="miseres"]:checked')].map((input) => input.value),
      );
      misereChoices.replaceChildren();
      for (const name of selected) {
        const label = document.createElement("label");
        label.className = "choice";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.name = "miseres";
        input.value = name;
        input.checked = checked.has(name);
        const span = document.createElement("span");
        span.textContent = name;
        label.append(input, span);
        misereChoices.append(label);
      }
    }

    const defense = selected.filter((name) => name !== taker.value && name !== partner.value);
    defenders.textContent = taker.value
      ? `Défenseurs : ${defense.length ? defense.join(", ") : "à choisir"}`
      : "Les autres joueurs sélectionnés seront défenseurs.";
    filterPlayers();
  }

  searchLabel.hidden = false;
  search.addEventListener("input", filterPlayers);
  for (const input of players) input.addEventListener("change", updateRoles);
  taker.addEventListener("change", updateRoles);
  partner.addEventListener("change", updateRoles);
  updateRoles();

  // Les select restent dans le formulaire pour la soumission et servent de repli sans JS.
  taker.required = false;
  nativeRoles.hidden = true;
  touchRoles.hidden = false;
  for (const [container, select, picker] of [
    [takerChoices, taker, takerPicker],
    [partnerChoices, partner, partnerPicker],
  ]) {
    container.addEventListener("change", (event) => {
      select.value = event.target.value;
      updateRoles();
      picker.open = false;
      picker.querySelector("summary").focus();
    });
  }

  if (preview) {
    const invalidate = (event) => {
      if (event.target.closest("#score-preview") || event.target === search) return;
      preview.remove();
    };
    form.addEventListener("input", invalidate);
    form.addEventListener("change", invalidate);
  }

  form.addEventListener("submit", (event) => {
    const selected = players.filter((input) => input.checked).length;
    if (selected < 3 || selected > 5) {
      event.preventDefault();
      count.textContent = "Choisis entre 3 et 5 joueurs pour continuer.";
      count.classList.add("invalid");
      search.focus();
    } else if (!taker.value) {
      event.preventDefault();
      takerPicker.open = true;
      takerPicker.querySelector("summary").focus();
    }
  });
})();

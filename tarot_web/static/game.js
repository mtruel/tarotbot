(() => {
  const form = document.getElementById("game-form");
  if (!form) return;

  const players = [...form.querySelectorAll('input[name="joueurs"]')];
  const taker = form.elements.namedItem("preneur");
  const partner = form.elements.namedItem("partenaire");
  const partnerField = document.getElementById("partner-field");
  const partnerSummary = document.getElementById("partner-summary");
  const takerPicker = document.getElementById("taker-picker");
  const takerSummary = document.getElementById("taker-summary");
  const takerChoices = document.getElementById("taker-choices");
  const partnerChoices = document.getElementById("partner-choices");
  const rolesEmpty = document.getElementById("roles-empty");
  const playersPicker = document.getElementById("players-picker");
  const playersSummary = document.getElementById("players-summary");
  const playersDone = document.getElementById("players-done");
  const count = document.getElementById("player-count");
  const playerError = document.getElementById("player-error");
  const search = document.getElementById("player-search");
  const noResults = document.getElementById("no-results");
  const defenders = document.getElementById("defenders");
  const miseres = [...document.querySelectorAll("#misere-choices [data-player]")];
  const misereEmpty = document.getElementById("misere-empty");
  const extras = document.getElementById("extras");
  const extrasSummary = document.getElementById("extras-summary");
  const targetHelp = document.getElementById("target-help");
  const points = document.getElementById("points_attaque");
  const pointsMinus = document.getElementById("points-minus");
  const pointsMinusFive = document.getElementById("points-minus-five");
  const pointsPlusFive = document.getElementById("points-plus-five");
  const pointsPlus = document.getElementById("points-plus");
  const preview = document.getElementById("score-preview");
  const calculateAction = document.getElementById("calculate-action");
  let partnerChosen = Boolean(partner.value) || Boolean(preview);
  let previousPlayerCount = null;

  const normalize = (value) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("fr");

  function filterPlayers() {
    const query = normalize(search.value.trim());
    let visible = 0;
    for (const input of players) {
      const label = input.closest("label");
      label.hidden = !input.checked && !normalize(input.value).includes(query);
      if (!label.hidden) visible++;
    }
    noResults.hidden = visible > 0;
  }

  function updateSelect(select, names) {
    const previous = select.value;
    select.replaceChildren(select.options[0]);
    for (const name of names) select.add(new Option(name, name));
    select.value = names.includes(previous) ? previous : "";
  }

  function updateRoleCards(container, name, names, chosen, includeAlone = false) {
    container.replaceChildren();
    for (const value of includeAlone ? ["", ...names] : names) {
      const label = document.createElement("label");
      label.className = "player-choice";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = name;
      input.value = value;
      input.checked = value === chosen;
      const card = document.createElement("span");
      const initial = document.createElement("i");
      initial.setAttribute("aria-hidden", "true");
      initial.textContent = value ? [...value][0].toLocaleUpperCase("fr") : "—";
      const text = document.createElement("b");
      text.textContent = value || "Joue seul";
      const check = document.createElement("small");
      check.setAttribute("aria-hidden", "true");
      check.textContent = "✓";
      card.append(initial, text, check);
      label.append(input, card);
      container.append(label);
    }
  }

  function updateExtrasSummary() {
    const groups = [
      ["primes_attaque", "Attaque"],
      ["primes_defense", "Défense"],
      ["miseres", "Misères"],
    ];
    const parts = [];
    for (const [name, label] of groups) {
      const values = [...form.querySelectorAll(`input[name="${name}"]:checked`)].map((input) => input.value);
      if (values.length) parts.push(`${label} : ${values.join(", ")}`);
    }
    extrasSummary.textContent = parts.join(" · ");
    extrasSummary.hidden = parts.length === 0;
    extras.classList.toggle("has-selections", parts.length > 0);
  }

  function updatePlayers() {
    const selected = players.filter((input) => input.checked).map((input) => input.value);
    count.textContent = selected.length ? `${selected.length} JOUEUR${selected.length > 1 ? "S" : ""}` : "3 À 5 JOUEURS";
    if (selected.length >= 3) playerError.hidden = true;
    playersDone.hidden = selected.length < 3;
    playersSummary.textContent = selected.join(", ") || "Aucun joueur sélectionné";
    if (selected.length === 5 && previousPlayerCount !== 5) {
      const moveFocus = previousPlayerCount !== null && playersPicker.contains(document.activeElement);
      playersPicker.open = false;
      if (moveFocus) playersPicker.querySelector("summary").focus();
    }
    previousPlayerCount = selected.length;
    for (const input of players) input.disabled = !input.checked && selected.length >= 5;
    updateSelect(taker, selected);
    takerSummary.textContent = taker.value || "Choisir un joueur";
    if (!taker.value) takerPicker.open = true;
    const previousPartner = partner.value;
    updateSelect(partner, selected.length === 5 ? selected.filter((name) => name !== taker.value) : []);
    partner.disabled = selected.length !== 5;
    partnerField.hidden = partner.disabled;
    if (partner.disabled || (previousPartner && !partner.value)) {
      partnerChosen = false;
      partnerField.open = true;
    }
    partnerSummary.textContent = partner.value || "Aucun · joue seul";
    updateRoleCards(takerChoices, "taker_card", selected, taker.value);
    updateRoleCards(partnerChoices, "partner_card", selected.filter((name) => name !== taker.value), partnerChosen ? partner.value : null, true);
    rolesEmpty.hidden = selected.length > 0;
    const defense = selected.filter((name) => name !== taker.value && name !== partner.value);
    const hasDefenders = Boolean(taker.value && defense.length);
    defenders.textContent = hasDefenders ? defense.join(", ") : "Les autres joueurs sélectionnés seront en défense.";
    defenders.classList.toggle("is-placeholder", !hasDefenders);
    for (const label of miseres) {
      const present = selected.includes(label.dataset.player);
      label.hidden = !present;
      if (!present) label.querySelector("input").checked = false;
    }
    misereEmpty.hidden = selected.length > 0;
    updateExtrasSummary();
    filterPlayers();
  }

  function updateTarget() {
    const bout = form.querySelector('input[name="bouts"]:checked');
    targetHelp.textContent = bout ? `Seuil à atteindre : ${bout.dataset.target} points.` : "Le nombre de bouts fixe le seuil à atteindre.";
  }

  taker.required = false;
  document.getElementById("native-roles").hidden = true;
  document.getElementById("card-roles").hidden = false;
  for (const [container, select, picker] of [
    [takerChoices, taker, takerPicker],
    [partnerChoices, partner, partnerField],
  ]) {
    const closePicker = () => {
      picker.open = false;
      picker.querySelector("summary").focus();
    };
    container.addEventListener("change", (event) => {
      select.value = event.target.value;
      if (container === partnerChoices) partnerChosen = true;
      updatePlayers();
      closePicker();
    });
    container.addEventListener("click", (event) => {
      const alreadyChosen = container === partnerChoices ? partnerChosen : Boolean(taker.value);
      if (alreadyChosen && event.target.matches('input[type="radio"]') && event.target.value === select.value) {
        closePicker();
      }
    });
  }
  for (const [button, direction] of [[pointsMinus, -1], [pointsMinusFive, -5], [pointsPlusFive, 5], [pointsPlus, 1]]) {
    button.hidden = false;
    button.addEventListener("click", () => {
      const previous = points.value;
      const min = Number(points.min);
      const max = Number(points.max);
      if (!Number.isFinite(points.valueAsNumber)) points.value = points.min;
      else if (points.valueAsNumber < min) points.value = points.min;
      else if (points.valueAsNumber > max) points.value = points.max;
      if (direction < 0) points.stepDown(-direction);
      else points.stepUp(direction);
      if (points.value !== previous) points.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  search.hidden = false;
  document.querySelector('label[for="player-search"]').hidden = false;
  search.addEventListener("input", filterPlayers);
  form.addEventListener("change", (event) => {
    if (["primes_attaque", "primes_defense", "miseres"].includes(event.target.name)) {
      updateExtrasSummary();
    }
  });

  for (const input of players) input.addEventListener("change", updatePlayers);
  taker.addEventListener("change", updatePlayers);
  partner.addEventListener("change", updatePlayers);
  for (const input of form.querySelectorAll('input[name="bouts"]')) input.addEventListener("change", updateTarget);
  updatePlayers();
  takerPicker.open = !taker.value;
  partnerField.open = !partnerChosen;
  updateTarget();

  if (preview) {
    const invalidate = (event) => {
      if (event.target === search || event.target.closest("#score-preview")) return;
      preview.remove();
      calculateAction.hidden = false;
    };
    form.addEventListener("input", invalidate);
    form.addEventListener("change", invalidate);
  }

  let submitting = false;
  form.addEventListener("submit", (event) => {
    if (submitting) {
      event.preventDefault();
      return;
    }
    const selected = players.filter((input) => input.checked).length;
    if (selected < 3 || selected > 5) {
      event.preventDefault();
      playerError.hidden = false;
      playersPicker.open = true;
      search.focus();
      return;
    }
    if (!taker.value) {
      event.preventDefault();
      rolesEmpty.textContent = "Choisis le preneur parmi les joueurs.";
      rolesEmpty.hidden = false;
      takerPicker.open = true;
      takerChoices.querySelector("input")?.focus();
      return;
    }
    submitting = true;
    if (event.submitter) event.submitter.setAttribute("aria-busy", "true");
  });
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    submitting = false;
    form.querySelectorAll('[aria-busy="true"]').forEach((element) => element.removeAttribute("aria-busy"));
  });
  document.getElementById("form-error")?.focus();
})();

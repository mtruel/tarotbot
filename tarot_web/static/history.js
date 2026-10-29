(() => {
  const list = document.querySelector(".home-history");
  const nav = document.querySelector(".home-pagination");
  const status = document.querySelector(".home-history-status");
  const next = nav?.querySelector('a[rel="next"]');
  if (!list || !nav || !status || !next || !("IntersectionObserver" in window)) return;

  const pageLabel = nav.querySelector("span");
  let loading = false;
  const observer = new IntersectionObserver(async (entries) => {
    if (loading || !entries.some((entry) => entry.isIntersecting)) return;
    loading = true;
    observer.unobserve(nav);
    status.textContent = "Chargement des parties…";

    try {
      const response = await fetch(next.href, { credentials: "same-origin" });
      if (!response.ok || response.redirected) throw new Error("Historique indisponible");
      const doc = new DOMParser().parseFromString(await response.text(), "text/html");
      const incoming = doc.querySelector(".home-history");
      const incomingNav = doc.querySelector(".home-pagination");
      const incomingCards = incoming?.querySelectorAll(".home-history-card");
      if (!incoming || !incomingNav || !incomingCards?.length) throw new Error("Page invalide");

      const currentCards = list.querySelectorAll(".home-history-card");
      const previousDate = currentCards[currentCards.length - 1]?.querySelector("time")?.dateTime;
      const firstDate = incomingCards[0].querySelector("time")?.dateTime;
      if (previousDate && firstDate && previousDate.slice(0, 10) !== firstDate.slice(0, 10)) {
        const separator = document.createElement("hr");
        separator.className = "home-day-separator";
        separator.setAttribute("aria-label", "Changement de jour");
        list.append(separator);
      }
      list.append(...incoming.children);
      status.textContent = `${incomingCards.length} parties supplémentaires chargées.`;

      const following = incomingNav.querySelector('a[rel="next"]');
      if (!following) {
        next.remove();
        nav.classList.remove("is-auto");
        if (pageLabel) pageLabel.textContent = "Fin de l’historique";
        return;
      }
      next.setAttribute("href", following.getAttribute("href"));
      if (pageLabel) pageLabel.textContent = incomingNav.querySelector("span")?.textContent || "";
      loading = false;
      observer.observe(nav);
    } catch (_error) {
      nav.classList.remove("is-auto");
      status.textContent = "Chargement automatique impossible. Utilise le lien pour continuer.";
    }
  }, { rootMargin: "200px" });

  nav.classList.add("is-auto");
  observer.observe(nav);
})();

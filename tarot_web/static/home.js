(() => {
  const table = document.getElementById("ranking-table");
  if (!table || !table.tBodies.length) return;

  const body = table.tBodies[0];
  const rows = Array.from(body.rows);
  const buttons = Array.from(table.querySelectorAll("thead button[data-sort]"));
  const collator = new Intl.Collator("fr", { sensitivity: "base", numeric: true });
  let active = null;
  let direction = 0;

  buttons.forEach((button, column) => {
    button.disabled = false;
    button.addEventListener("click", () => {
      direction = active === column ? (direction + 1) % 3 : 1;
      active = direction ? column : null;
      buttons.forEach((other) => other.parentElement.setAttribute("aria-sort", "none"));
      if (direction) button.parentElement.setAttribute("aria-sort", direction === 1 ? "ascending" : "descending");

      const ordered = rows.slice();
      if (direction) {
        ordered.sort((a, b) => {
          const left = a.cells[column].dataset.value;
          const right = b.cells[column].dataset.value;
          const comparison = button.dataset.sort === "name"
            ? collator.compare(left, right)
            : Number(left) - Number(right);
          return comparison * (direction === 1 ? 1 : -1) || rows.indexOf(a) - rows.indexOf(b);
        });
      }
      body.append(...ordered);
    });
  });
})();

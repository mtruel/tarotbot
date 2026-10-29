const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../tarot_web/static/history.js"), "utf8");

function setup({ fail = false, last = false, sameDay = false, supportsObserver = true } = {}) {
  const card = (date) => ({ querySelector: () => date ? { dateTime: date } : null });
  const current = [card("2026-01-03T12:00:00")];
  const incoming = [card(sameDay ? "2026-01-03T11:00:00" : "2026-01-02T12:00:00"), card("2026-01-02T11:00:00")];
  const added = [];
  const list = {
    querySelectorAll: () => current,
    append: (...nodes) => { added.push(...nodes); current.push(...nodes.filter((n) => n.querySelector)); },
  };
  const classes = new Set();
  const next = {
    href: "/history?page=2",
    setAttribute: (key, value) => { if (key === "href") next.href = value; },
    remove: () => { next.removed = true; },
  };
  const label = { textContent: "Page 1 / 3" };
  const nav = {
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c) },
    querySelector: (selector) => selector === "span" ? label : next,
  };
  const status = { textContent: "" };
  const following = last ? null : { getAttribute: () => "/history?page=3" };
  const incomingNav = { querySelector: (selector) => selector === "span" ? { textContent: "Page 2 / 3" } : following };
  const incomingList = { children: incoming, querySelectorAll: () => incoming };
  const parsed = { querySelector: (selector) => selector === ".home-history" ? incomingList : incomingNav };
  const document = {
    querySelector: (selector) => ({ ".home-history": list, ".home-pagination": nav, ".home-history-status": status })[selector],
    createElement: () => ({ setAttribute: (key, value) => { added.label = [key, value]; } }),
  };
  let observer;
  class IntersectionObserver {
    constructor(callback) { this.callback = callback; observer = this; }
    observe(target) { assert.equal(target, nav); }
    unobserve(target) { assert.equal(target, nav); }
  }
  const context = {
    document,
    window: supportsObserver ? { IntersectionObserver } : {},
    IntersectionObserver,
    DOMParser: class { parseFromString() { return parsed; } },
    fetch: async () => ({ ok: !fail, redirected: false, text: async () => "" }),
  };
  vm.runInNewContext(source, context);
  return { observer, next, classes, status, label, added, incoming };
}

test("charge la page suivante et sépare les journées", async () => {
  const success = setup();
  assert(success.classes.has("is-auto"));
  await success.observer.callback([{ isIntersecting: true }]);
  assert.equal(success.next.href, "/history?page=3");
  assert.equal(success.added[0].className, "home-day-separator");
  assert.equal(success.added.length, 3);
  assert.equal(success.status.textContent, "2 parties supplémentaires chargées.");
  assert.equal(success.label.textContent, "Page 2 / 3");
});

test("termine l'historique sans séparateur pour une même journée", async () => {
  const last = setup({ last: true, sameDay: true });
  await last.observer.callback([{ isIntersecting: true }]);
  assert.equal(last.added.length, 2);
  assert(last.next.removed);
  assert.equal(last.label.textContent, "Fin de l’historique");
  assert(!last.classes.has("is-auto"));
});

test("conserve le lien de secours en cas d'échec", async () => {
  const error = setup({ fail: true });
  await error.observer.callback([{ isIntersecting: true }]);
  assert(!error.classes.has("is-auto"));
  assert.match(error.status.textContent, /impossible/);
  assert.equal(error.next.href, "/history?page=2");
});

test("conserve la pagination sans IntersectionObserver", () => {
  const unsupported = setup({ supportsObserver: false });
  assert.equal(unsupported.observer, undefined);
  assert(!unsupported.classes.has("is-auto"));
});

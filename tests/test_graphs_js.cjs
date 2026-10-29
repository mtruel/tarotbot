const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const echarts = require("../tarot_web/static/echarts.min.js");

const source = fs.readFileSync(path.join(__dirname, "../tarot_web/static/graphs.js"), "utf8");

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.style = { setProperty(name, value) { this[name] = value; } };
    this.clientWidth = 360;
    this.textContent = "";
    this.hidden = false;
  }

  set innerHTML(_value) { throw new Error("L'insertion HTML est interdite"); }
  setAttribute(name, value) { this.attributes[name] = value; }
  hasAttribute(name) { return Object.hasOwn(this.attributes, name); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  click() { this.listeners.click(); }
  append(...nodes) {
    for (const node of nodes) {
      if (node.tag === "fragment") this.append(...node.children);
      else { node.parent = this; this.children.push(node); }
    }
  }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this);
  }
  getContext() { return { measureText: (text) => ({ width: text.length * 8 }) }; }
}

function fixture(games = 344, playerCount = 18) {
  return {
    games,
    dates: Array.from({ length: games + 1 }, (_, i) => {
      if (i === 0) return null;
      const day = String((i % 28) + 1).padStart(2, "0");
      return i % 2 ? `${day}/01/2026, 20:30:00` : `2026-02-${day}T10:00:00`;
    }),
    players: Array.from({ length: playerCount }, (_, i) => ({
      name: i === 0 ? "<img src=x onerror=alert(1)>" : `Joueur ${i}`,
      values: Array.from({ length: games + 1 }, (_, game) => game === 0 ? 0 : game * (i - 3)),
    })),
  };
}

function setup({ data = fixture(), failure, missingNode } = {}) {
  const nodes = Object.fromEntries(
    ["scores-chart", "scores-chart-players", "scores-chart-fallback", "scores-chart-data"]
      .map((id) => [id, new Element()]),
  );
  nodes["scores-chart-data"].textContent = typeof data === "string" ? data : JSON.stringify(data);
  const errors = [];
  const windowListeners = {};
  let chart;
  let surface;
  let initOptions;

  const document = {
    readyState: "complete",
    getElementById: (id) => id === missingNode ? null : nodes[id],
    createElement: (tag) => {
      const element = new Element(tag);
      if (tag === "canvas" && failure === "canvas") element.getContext = () => null;
      return element;
    },
    createDocumentFragment: () => new Element("fragment"),
  };
  const window = { addEventListener: (name, callback) => { windowListeners[name] = callback; } };
  if (failure !== "library") {
    window.echarts = {
      init: (element, _theme, options) => {
        surface = element;
        initOptions = options;
        if (failure === "init") throw new Error("échec init");
        chart = {
          listeners: {},
          disposed: false,
          on(name, callback) { this.listeners[name] = callback; },
          dispose() { this.disposed = true; },
          resize(size) { this.size = size; },
          setOption(update) {
            if (failure === "render") throw new Error("échec rendu");
            if (!this.options) {
              this.options = update;
              return;
            }
            if (update.series) {
              for (const change of update.series) {
                const current = this.options.series.find((series) => series.id === change.id);
                assert(current, `Série inconnue : ${change.id}`);
                Object.assign(current.lineStyle, change.lineStyle);
                Object.assign(current.endLabel, change.endLabel);
              }
            }
            if (update.xAxis) {
              update.xAxis.forEach((axis, i) => {
                Object.assign(this.options.xAxis[i].axisTick, axis.axisTick);
                Object.assign(this.options.xAxis[i].axisLabel, axis.axisLabel);
              });
            }
          },
        };
        return chart;
      },
    };
  }
  vm.runInNewContext(source, { document, window, console: { error: (...args) => errors.push(args) } });
  return { nodes, chart, surface, initOptions, windowListeners, errors };
}

function controls(result) {
  const children = result.nodes["scores-chart-players"].children;
  return { players: children[1].children, reset: children[2] };
}

function assertSelection(result, selected) {
  const { players, reset } = controls(result);
  players.forEach((button, i) => {
    const series = result.chart.options.series[i];
    assert.equal(button.attributes["aria-pressed"], String(i === selected));
    assert.equal(series.lineStyle.opacity, selected === null || selected === i ? 1 : 0.14);
    assert.equal(series.endLabel.opacity ?? 1, selected === null || selected === i ? 1 : 0.14);
    assert.equal(series.lineStyle.width, selected === i ? 4.5 : 2.5);
  });
  assert.equal(reset.disabled, selected === null);
}

test("toutes les courbes et leurs contrôles conservent les données et les noms", () => {
  const data = fixture();
  const result = setup({ data });
  const { players, reset } = controls(result);
  const series = result.chart.options.series;
  assert.equal(result.nodes["scores-chart-fallback"].hidden, true);
  assert.equal(series.length, data.players.length);
  assert.equal(players.length, data.players.length);
  series.forEach((line, i) => {
    assert.equal(line.type, "line");
    assert.equal(line.triggerLineEvent, true);
    assert.equal(line.name, data.players[i].name);
    assert.deepEqual(Array.from(line.data), data.players[i].values);
    assert.equal(line.endLabel.show, true);
    assert.equal(line.endLabel.formatter(), data.players[i].name);
    assert.equal(players[i].type, "button");
    assert.equal(players[i].textContent, data.players[i].name);
    assert.equal(players[i].attributes["aria-pressed"], "false");
  });
  assert.equal(reset.type, "button");
  assert.equal(reset.disabled, true);
  assert.equal(result.nodes["scores-chart"].attributes.tabindex, "0");
});

test("les couleurs des joueurs correspondent au SVG de repli et sont comprises par ECharts", () => {
  const result = setup({ data: fixture(2, 18) });
  const { players } = controls(result);
  result.chart.options.series.forEach((line, index) => {
    const expected = `hsl(${index * 137 % 360}, 65%, 45%)`;
    assert.equal(line.lineStyle.color, expected);
    assert.equal(line.itemStyle.color, expected);
    assert.equal(line.endLabel.color, expected);
    assert.equal(players[index].style["--scores-player-color"], expected);
    assert(echarts.color.parse(expected), `Couleur non reconnue : ${expected}`);
  });
});

test("sélection persistante, changement et réinitialisation par courbes et boutons", () => {
  const result = setup({ data: fixture(4, 3) });
  const { players, reset } = controls(result);
  const clickCurve = (i) => result.chart.listeners.click({ componentType: "series", seriesIndex: i });
  clickCurve(1);
  assertSelection(result, 1);
  result.chart.listeners.click({ componentType: "xAxis", seriesIndex: 0 });
  assertSelection(result, 1);
  clickCurve(1);
  assertSelection(result, null);
  players[0].click();
  assertSelection(result, 0);
  players[2].click();
  assertSelection(result, 2);
  players[2].click();
  assertSelection(result, null);
  clickCurve(1);
  players[0].click();
  assertSelection(result, 0);
  reset.click();
  assertSelection(result, null);
});

test("344 parties : bornes, dates alignées, graduations espacées et largeur de synthèse", () => {
  const data = fixture();
  const result = setup({ data });
  const { xAxis, yAxis, grid, series } = result.chart.options;
  const [bottom, top] = xAxis;
  assert(result.initOptions.width >= 600 && result.initOptions.width < 1500);
  assert.equal(result.initOptions.renderer, "canvas");
  assert.equal(bottom.position, "bottom");
  assert.equal(top.position, "top");
  assert.equal(bottom.type, "category");
  assert.equal(top.type, "category");
  assert.equal(bottom.boundaryGap, false);
  assert.equal(top.boundaryGap, false);
  assert.equal(bottom.data.length, data.games + 1);
  assert.equal(bottom.data[0], "0");
  assert.equal(bottom.data[data.games], "344");
  assert.deepEqual(Array.from(top.data), Array.from(bottom.data));
  assert.equal(yAxis.type, "value");
  assert.equal(yAxis.scale, false);
  assert.equal(series[0].markLine.data[0].yAxis, 0);

  function checkGraduations(width) {
    const interval = bottom.axisLabel.interval;
    assert.equal(top.axisLabel.interval, interval);
    assert.equal(bottom.axisTick.interval, interval);
    assert.equal(top.axisTick.interval, interval);
    assert((interval + 1) * (width - grid.left - grid.right) / data.games >= 69);
    assert.equal(top.axisLabel.formatter("0", 0), "");
    for (let i = interval + 1; i <= data.games; i += interval + 1) {
      const date = data.dates[i];
      const expected = i % 2 ? date.slice(0, 5) : `${date.slice(8, 10)}/${date.slice(5, 7)}`;
      assert.equal(top.axisLabel.formatter(bottom.data[i], i), expected);
    }
  }
  checkGraduations(result.initOptions.width);
  const initialInterval = bottom.axisLabel.interval;
  controls(result).players[1].click();
  result.nodes["scores-chart"].clientWidth = 1600;
  result.windowListeners.resize();
  assert.equal(result.chart.size.width, 1600);
  assert(bottom.axisLabel.interval < initialInterval);
  checkGraduations(1600);
  assertSelection(result, 1);
});

test("le SVG de repli reste visible lorsque l'initialisation échoue", () => {
  const cases = [
    { failure: "library" },
    { failure: "canvas" },
    { failure: "init" },
    { failure: "render" },
    { data: "{ invalide" },
    { data: { ...fixture(2, 1), dates: [null] } },
    { data: { ...fixture(2, 1), players: [{ name: "A", values: [0, 1] }] } },
    { missingNode: "scores-chart-data" },
  ];
  for (const options of cases) {
    const result = setup(options);
    assert.equal(result.nodes["scores-chart-fallback"].hidden, false, JSON.stringify(options));
    assert.equal(result.nodes["scores-chart-players"].children.length, 0);
    assert.equal(result.nodes["scores-chart"].children.length, 0);
    if (options.failure === "render") assert.equal(result.chart.disposed, true);
  }
});

const assert = require("node:assert/strict");
const test = require("node:test");
const echarts = require("../tarot_web/static/echarts.min.js");

echarts.setPlatformAPI({
  measureText: (text) => ({ width: String(text).length * 7 }),
});

function clickLine(triggerLineEvent, t) {
  const chart = echarts.init(null, null, { renderer: "svg", ssr: true, width: 800, height: 400 });
  t.after(() => chart.dispose());
  chart.setOption({
    animation: false,
    tooltip: { show: false },
    xAxis: { type: "category", data: ["0", "1", "2"], boundaryGap: false },
    yAxis: { type: "value", min: 0, max: 10 },
    series: [{
      type: "line",
      name: "Alice",
      data: [0, 4, 10],
      showSymbol: false,
      triggerLineEvent,
      emphasis: { disabled: true },
    }],
  });

  const start = chart.convertToPixel({ seriesIndex: 0 }, [1, 4]);
  const end = chart.convertToPixel({ seriesIndex: 0 }, [2, 10]);
  const x = (start[0] + end[0]) / 2;
  const y = (start[1] + end[1]) / 2;
  const zr = chart.getZr();
  assert.equal(zr.findHover(x, y).target?.type, "ec-polyline");

  const clicks = [];
  chart.on("click", (event) => clicks.push(event));
  for (const type of ["mousedown", "mouseup", "click"]) {
    zr.handler.dispatch(type, { zrX: x, zrY: y });
  }
  return clicks;
}

test("triggerLineEvent émet un clic de série sur une ligne sans symboles", (t) => {
  const clicks = clickLine(true, t);
  assert.equal(clicks.length, 1);
  assert.equal(clicks[0].componentType, "series");
  assert.equal(clicks[0].seriesIndex, 0);
  assert.equal(clicks[0].seriesName, "Alice");
});

test("sans triggerLineEvent, un clic sur la polyligne ne déclenche pas chart.on", (t) => {
  assert.equal(clickLine(false, t).length, 0);
});

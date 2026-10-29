(() => {
  function start() {
    const container = document.getElementById("scores-chart");
    const controls = document.getElementById("scores-chart-players");
    const fallback = document.getElementById("scores-chart-fallback");
    const source = document.getElementById("scores-chart-data");
    if (!container || !controls || !fallback || !source || !window.echarts) return;

    let chart;
    let surface;
    try {
      const data = JSON.parse(source.textContent);
      if (!Number.isSafeInteger(data.games) || data.games < 1 ||
          !Array.isArray(data.dates) || data.dates.length !== data.games + 1 ||
          data.dates[0] !== null || !Array.isArray(data.players) || !data.players.length ||
          !data.players.every((player) => player && typeof player.name === "string" &&
            Array.isArray(player.values) && player.values.length === data.games + 1 &&
            player.values[0] === 0 && player.values.every(Number.isFinite))) return;

      function shortDate(value) {
        if (typeof value !== "string") return "";
        const french = /^(\d{1,2})\/(\d{1,2})\/\d{4}(?:\b|$)/.exec(value);
        if (french) return `${french[1].padStart(2, "0")}/${french[2].padStart(2, "0")}`;
        const iso = /^\d{4}-(\d{2})-(\d{2})(?:\b|T)/.exec(value);
        return iso ? `${iso[2]}/${iso[1]}` : "";
      }

      // Match chart_svg's palette while using the HSL syntax understood by ECharts.
      const colors = data.players.map((_, index) => `hsl(${index * 137 % 360}, 65%, 45%)`);
      const labels = Array.from({ length: data.games + 1 }, (_, index) => String(index));
      const dates = data.dates.map(shortDate);
      const fragment = document.createDocumentFragment();
      const title = document.createElement("p");
      title.className = "scores-chart-controls-title";
      title.textContent = "Sélectionner un joueur";
      fragment.append(title);
      const list = document.createElement("div");
      list.className = "scores-chart-player-list";
      const buttons = data.players.map((player, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "scores-chart-player";
        button.style.setProperty("--scores-player-color", colors[index]);
        button.setAttribute("aria-pressed", "false");
        button.textContent = player.name;
        list.append(button);
        return button;
      });
      fragment.append(list);
      const reset = document.createElement("button");
      reset.type = "button";
      reset.className = "scores-chart-reset";
      reset.textContent = "Afficher tous les joueurs";
      reset.disabled = true;
      fragment.append(reset);

      surface = document.createElement("div");
      surface.className = "scores-chart-surface";
      surface.setAttribute("role", "img");
      surface.setAttribute("aria-label", "Courbes des points cumulés par partie. Utilisez les boutons pour sélectionner un joueur.");
      container.append(surface);

      // Leave room for complete player names, independently of the plot width.
      const measure = document.createElement("canvas").getContext("2d");
      if (!measure) throw new Error("Canvas indisponible");
      measure.font = "12px sans-serif";
      const nameWidth = Math.ceil(data.players.reduce((max, player) => Math.max(max, measure.measureText(player.name).width), 0));
      const right = Math.max(30, nameWidth + 24);
      const chartWidth = () => Math.max(container.clientWidth, 640 + right);
      const axisInterval = (width) => Math.max(0, Math.ceil(data.games * 70 / (width - 70 - right)) - 1);
      const width = chartWidth();
      const height = Math.max(380, 110 + data.players.length * 24);
      surface.style.width = `${width}px`;
      surface.style.height = `${height}px`;
      chart = window.echarts.init(surface, null, { renderer: "canvas", width, height });
      let selected = null;
      const series = data.players.map((player, index) => ({
        id: `player-${index}`,
        name: player.name,
        type: "line",
        data: player.values,
        showSymbol: false,
        triggerLineEvent: true,
        animation: false,
        lineStyle: { color: colors[index], width: 2.5, opacity: 1 },
        itemStyle: { color: colors[index] },
        endLabel: { show: true, formatter: () => player.name, color: colors[index], fontSize: 12 },
        labelLayout: { moveOverlap: "shiftY" },
        emphasis: { disabled: true },
        ...(index === 0 ? { markLine: {
          silent: true,
          symbol: "none",
          label: { show: false },
          lineStyle: { color: "#52645a", width: 1, type: "solid" },
          data: [{ yAxis: 0 }],
        } } : {}),
      }));

      function select(index) {
        selected = selected === index ? null : index;
        buttons.forEach((button, buttonIndex) => {
          button.setAttribute("aria-pressed", String(selected === buttonIndex));
        });
        reset.disabled = selected === null;
        chart.setOption({ series: series.map((item, itemIndex) => {
          const opacity = selected === null || selected === itemIndex ? 1 : 0.14;
          const width = selected === itemIndex ? 4.5 : 2.5;
          return { id: item.id, lineStyle: { opacity, width }, endLabel: { opacity } };
        }) });
      }

      chart.setOption({
        animation: false,
        grid: { left: 70, right, top: 55, bottom: 55 },
        tooltip: { show: false },
        xAxis: [
          { type: "category", data: labels, boundaryGap: false, position: "bottom",
            axisLine: { onZero: false }, axisTick: { interval: axisInterval(width) },
            axisLabel: { interval: axisInterval(width), showMaxLabel: false }, name: "Partie", nameLocation: "middle", nameGap: 32 },
          { type: "category", data: labels, boundaryGap: false, position: "top",
            axisLine: { onZero: false }, axisTick: { interval: axisInterval(width) },
            axisLabel: { interval: axisInterval(width), showMaxLabel: false, formatter: (_value, index) => dates[index] } },
        ],
        yAxis: { type: "value", scale: false, axisLabel: { hideOverlap: true } },
        series,
      });
      chart.on("click", (event) => {
        if (event.componentType === "series" && Number.isInteger(event.seriesIndex) &&
            event.seriesIndex >= 0 && event.seriesIndex < series.length) select(event.seriesIndex);
      });
      buttons.forEach((button, index) => button.addEventListener("click", () => select(index)));
      reset.addEventListener("click", () => { if (selected !== null) select(selected); });
      controls.replaceChildren(fragment);
      if (!container.hasAttribute("tabindex")) container.setAttribute("tabindex", "0");
      if (!container.hasAttribute("role")) container.setAttribute("role", "region");
      if (!container.hasAttribute("aria-label") && !container.hasAttribute("aria-labelledby")) {
        container.setAttribute("aria-label", "Graphique des points cumulés, défilable");
      }
      window.addEventListener("resize", () => {
        const newWidth = chartWidth();
        const interval = axisInterval(newWidth);
        surface.style.width = `${newWidth}px`;
        chart.resize({ width: newWidth, height });
        chart.setOption({ xAxis: [
          { axisTick: { interval }, axisLabel: { interval } },
          { axisTick: { interval }, axisLabel: { interval } },
        ] });
      });
      fallback.hidden = true;
    } catch (error) {
      if (chart) chart.dispose();
      if (surface) surface.remove();
      console.error("Initialisation du graphique impossible", error);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();

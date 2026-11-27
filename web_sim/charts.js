const SECTOR_COLORS = {
  1: "#2f86bf",
  2: "#4f8a36",
  3: "#d97706",
  4: "#c94a36",
};

function prepCanvas(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth || 380;
  const h = canvas.clientHeight || 155;
  if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

function drawGrid(ctx, w, h, minY, maxY, yLabelStep, refLines = []) {
  const padL = 34;
  const padR = 8;
  const padT = 8;
  const padB = 18;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  ctx.strokeStyle = "#e6dcc2";
  ctx.lineWidth = 1;
  ctx.font = "10px 'IBM Plex Mono', monospace";
  ctx.fillStyle = "#684f3d";

  for (let v = minY; v <= maxY; v += yLabelStep) {
    const y = padT + plotH - ((v - minY) / (maxY - minY)) * plotH;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    ctx.fillText(String(v), 4, y + 3);
  }

  for (const ref of refLines) {
    const y = padT + plotH - ((ref.value - minY) / (maxY - minY)) * plotH;
    ctx.save();
    ctx.setLineDash([4, 3]);
    ctx.strokeStyle = ref.color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    ctx.fillStyle = ref.color;
    ctx.fillText(ref.label, padL + 4, y - 3);
    ctx.restore();
  }

  return { padL, padR, padT, padB, plotW, plotH };
}

export function drawLineChart(canvas, seriesMap, minY, maxY, yStep, refLines = []) {
  const { ctx, w, h } = prepCanvas(canvas);
  const { padL, padT, plotW, plotH } = drawGrid(ctx, w, h, minY, maxY, yStep, refLines);

  for (const sid of [1, 2, 3, 4]) {
    const arr = seriesMap[sid] || [];
    if (arr.length < 2) continue;
    ctx.strokeStyle = SECTOR_COLORS[sid];
    ctx.lineWidth = 2;
    ctx.beginPath();
    let started = false;
    arr.forEach((val, idx) => {
      if (val === null || val === undefined || Number.isNaN(val)) {
        started = false;
        return;
      }
      const clamped = Math.max(minY, Math.min(maxY, Number(val)));
      const x = padL + (idx / Math.max(1, arr.length - 1)) * plotW;
      const y = padT + plotH - ((clamped - minY) / (maxY - minY)) * plotH;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();
  }
}

export function drawActivityBars(canvas, buckets) {
  const { ctx, w, h } = prepCanvas(canvas);
  const maxCount = Math.max(8, ...buckets.map((b) => b.total));
  const { padL, padT, plotW, plotH } = drawGrid(ctx, w, h, 0, maxCount, Math.max(2, Math.ceil(maxCount / 4)));
  if (!buckets.length) return;

  const barW = Math.max(4, plotW / buckets.length - 2);
  buckets.forEach((b, i) => {
    const x = padL + i * (plotW / buckets.length) + 1;
    let curY = padT + plotH;
    const stacks = [
      { count: b.sensors, color: "#2f86bf" },
      { count: b.commands, color: "#d97706" },
      { count: b.acks, color: "#4f8a36" },
      { count: b.alerts, color: "#c94a36" },
    ];
    for (const st of stacks) {
      if (!st.count) continue;
      const bh = (st.count / maxCount) * plotH;
      curY -= bh;
      ctx.fillStyle = st.color;
      ctx.fillRect(x, curY, barW, bh);
    }
  });
}

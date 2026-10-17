// Learning studio drawing layer: pen, highlighter, arrows, boxes, an eraser, a laser pointer, a spotlight,
// zoom, whiteboard paper with pages, and on-screen notes. Everything is drawn into each recorded frame, so it
// is part of the video. The presenter draws on the live preview, which is the recording canvas itself.
window.StudioInk = (() => {
  const Scene = window.StudioScene;
  const SIZES = { thin: 3, medium: 6, thick: 11 }; // line widths at 720p
  const FADE_AFTER = 2500; // fading ink: a line starts fading this long after it is drawn,
  const FADE_FOR = 900; //   and is gone this much later
  const LASER_TRAIL = 450;
  const MAX_ZOOM = 4;
  const NOTES_KEY = "myprogress-studio-notes";
  const MAX_NOTES = 20;
  const NOTE_PLACES = { "top-left": [0, 0], "top-center": [0.5, 0], "top-right": [1, 0], center: [0.5, 0.5], "bottom-left": [0, 1], "bottom-center": [0.5, 1], "bottom-right": [1, 1] };
  // Sizes are at 720p; "margin" keeps notes off the frame's edge.
  const NOTE_MARGIN = 28;
  const MONO = 'ui-monospace, SFMono-Regular, Consolas, monospace';
  const NOTE_STYLES = {
    sticky: { font: unit => `600 ${23 * unit}px ${Scene.DISPLAY_FONT}`, size: 23, line: 31, pad: 22, min: 220, max: 330, lines: 7, background: "#fde68a", color: "#422006" },
    callout: { font: unit => `500 ${21 * unit}px ${Scene.FONT}`, size: 21, line: 29, pad: 18, min: 0, max: 460, lines: 6, background: "rgba(15, 23, 42, .92)", color: "#f8fafc", bar: "#38bdf8" },
    title: { font: unit => `800 ${40 * unit}px ${Scene.DISPLAY_FONT}`, size: 40, line: 50, pad: 24, min: 0, max: 980, lines: 2, background: "rgba(255, 255, 255, .97)", color: "#0f172a", bar: "#16a34a" },
    code: { font: unit => `500 ${19 * unit}px ${MONO}`, size: 19, line: 27, pad: 18, min: 260, max: 640, lines: 10, background: "#0b1220", color: "#e2e8f0", border: "#334155" },
  };
  const LIGHT_PAPER = new Set(["grid", "lined", "dots", "plain"]);
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  // Whiteboard paper, drawn once per style and size.
  function drawPaper(style, w, h) {
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    const unit = h / 720;
    if (style === "chalk") {
      const glow = ctx.createRadialGradient(w / 2, h / 2, h * 0.2, w / 2, h / 2, w * 0.75);
      glow.addColorStop(0, "#26473c");
      glow.addColorStop(1, "#15302a");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);
      return canvas;
    }
    ctx.fillStyle = "#fdfdfb";
    ctx.fillRect(0, 0, w, h);
    ctx.lineWidth = Math.max(1, unit);
    ctx.beginPath();
    if (style === "grid") {
      const step = 36 * unit;
      ctx.strokeStyle = "rgba(37, 99, 235, .16)";
      for (let x = step; x < w; x += step) { ctx.moveTo(x, 0); ctx.lineTo(x, h); }
      for (let y = step; y < h; y += step) { ctx.moveTo(0, y); ctx.lineTo(w, y); }
      ctx.stroke();
    } else if (style === "lined") {
      const step = 40 * unit;
      ctx.strokeStyle = "rgba(37, 99, 235, .25)";
      for (let y = step * 2; y < h; y += step) { ctx.moveTo(0, y); ctx.lineTo(w, y); }
      ctx.stroke();
      ctx.beginPath();
      ctx.strokeStyle = "rgba(220, 38, 38, .35)";
      ctx.moveTo(96 * unit, 0);
      ctx.lineTo(96 * unit, h);
      ctx.stroke();
    } else if (style === "dots") {
      const step = 32 * unit;
      ctx.fillStyle = "rgba(71, 85, 105, .35)";
      for (let x = step; x < w; x += step) for (let y = step; y < h; y += step) { ctx.moveTo(x + 1.6 * unit, y); ctx.arc(x, y, 1.6 * unit, 0, Math.PI * 2); }
      ctx.fill();
    }
    return canvas;
  }

  // Strokes keep their points as fractions of the frame (0–1), so they fit any quality.
  function drawStroke(ctx, stroke, w, h, alpha) {
    const unit = h / 720;
    const highlighter = stroke.tool === "highlighter";
    const width = (SIZES[stroke.size] || SIZES.medium) * unit * (highlighter ? 3.2 : 1);
    const points = stroke.points.map(([x, y]) => [x * w, y * h]);
    const first = points[0];
    const last = points[points.length - 1];
    ctx.save();
    ctx.globalAlpha = alpha * (highlighter ? 0.38 : 1);
    ctx.strokeStyle = stroke.color;
    ctx.fillStyle = stroke.color;
    ctx.lineWidth = width;
    ctx.lineCap = highlighter ? "square" : "round";
    ctx.lineJoin = "round";
    if (stroke.tool === "arrow") {
      const angle = Math.atan2(last[1] - first[1], last[0] - first[0]);
      const head = Math.max(width * 3.4, 16 * unit);
      ctx.beginPath();
      ctx.moveTo(...first);
      ctx.lineTo(last[0] - Math.cos(angle) * head * 0.7, last[1] - Math.sin(angle) * head * 0.7);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(...last);
      ctx.lineTo(last[0] - head * Math.cos(angle - 0.45), last[1] - head * Math.sin(angle - 0.45));
      ctx.lineTo(last[0] - head * Math.cos(angle + 0.45), last[1] - head * Math.sin(angle + 0.45));
      ctx.closePath();
      ctx.fill();
    } else if (stroke.tool === "box") {
      Scene.roundedPath(ctx, Math.min(first[0], last[0]), Math.min(first[1], last[1]), Math.abs(last[0] - first[0]), Math.abs(last[1] - first[1]), 10 * unit);
      ctx.stroke();
    } else if (points.length === 1) {
      ctx.beginPath();
      ctx.arc(first[0], first[1], width / 2, 0, Math.PI * 2);
      ctx.fill();
    } else {
      // Smooth the line through the midpoints of the captured points.
      ctx.beginPath();
      ctx.moveTo(...first);
      for (let index = 1; index < points.length - 1; index += 1) {
        const [x, y] = points[index];
        const [nx, ny] = points[index + 1];
        ctx.quadraticCurveTo(x, y, (x + nx) / 2, (y + ny) / 2);
      }
      ctx.lineTo(...last);
      ctx.stroke();
    }
    ctx.restore();
  }

  // Eraser hit test, in a 1600x900 space so distances are the same in both directions.
  function strokeHit(stroke, x, y, radius) {
    const points = stroke.points.map(([px, py]) => [px * 1600, py * 900]);
    const reach = radius + (SIZES[stroke.size] || SIZES.medium) * 1.25 * (stroke.tool === "highlighter" ? 3.2 : 1) / 2;
    const near = ([ax, ay], [bx, by]) => {
      const dx = bx - ax;
      const dy = by - ay;
      const t = dx || dy ? clamp(((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy), 0, 1) : 0;
      return Math.hypot(x - (ax + t * dx), y - (ay + t * dy)) <= reach;
    };
    const first = points[0];
    const last = points[points.length - 1];
    if (stroke.tool === "box") {
      const corners = [first, [last[0], first[1]], last, [first[0], last[1]]];
      return corners.some((corner, index) => near(corner, corners[(index + 1) % 4]));
    }
    if (stroke.tool === "arrow" || points.length === 1) return near(first, last);
    return points.some((point, index) => index > 0 && near(points[index - 1], point));
  }

  // A code line that fits the width, cut with an ellipsis (code keeps its spacing, unlike wrapped text).
  function fitLine(ctx, text, maxWidth) {
    if (ctx.measureText(text).width <= maxWidth) return text;
    let line = text;
    while (line && ctx.measureText(`${line}…`).width > maxWidth) line = line.slice(0, -1);
    return `${line}…`;
  }

  function layoutNote(ctx, note, w, h) {
    const unit = h / 720;
    const spec = NOTE_STYLES[note.style] || NOTE_STYLES.sticky;
    const pad = spec.pad * unit;
    const left = spec.bar ? 8 * unit : 0;
    const top = note.style === "code" ? 22 * unit : 0;
    ctx.font = spec.font(unit);
    const textMax = Math.min(spec.max * unit, w - NOTE_MARGIN * unit * 2) - pad * 2 - left;
    let lines;
    if (note.style === "code") lines = note.text.split("\n").map(line => fitLine(ctx, line.replace(/\t/g, "  "), textMax));
    else lines = note.text.split("\n").flatMap(paragraph => (paragraph.trim() ? Scene.wrapLines(ctx, paragraph, textMax, spec.lines) : [""]));
    while (lines.length > 1 && !lines[lines.length - 1].trim()) lines.pop();
    if (lines.length > spec.lines) lines = [...lines.slice(0, spec.lines - 1), `${lines[spec.lines - 1]}…`];
    const textWidth = Math.max(0, ...lines.map(line => ctx.measureText(line).width));
    const boxW = Math.max(spec.min * unit, textWidth + pad * 2 + left);
    const boxH = lines.length * spec.line * unit + pad * 2 + top;
    const margin = NOTE_MARGIN * unit;
    const x = margin + clamp(note.ax, 0, 1) * Math.max(0, w - boxW - margin * 2);
    const y = margin + clamp(note.ay, 0, 1) * Math.max(0, h - boxH - margin * 2);
    return { x, y, w: boxW, h: boxH, lines, spec, unit, pad, left, top };
  }

  function drawNote(ctx, note, w, h, now) {
    const box = layoutNote(ctx, note, w, h);
    const { x, y, spec, unit, pad, left, top } = box;
    note.box = { x: x / w, y: y / h, w: box.w / w, h: box.h / h };
    ctx.save();
    ctx.globalAlpha = clamp((now - note.shownAt) / 180, 0, 1);
    if (note.style === "sticky") {
      ctx.translate(x + box.w / 2, y + box.h / 2);
      ctx.rotate(-0.02);
      ctx.translate(-(x + box.w / 2), -(y + box.h / 2));
    }
    ctx.save();
    ctx.shadowColor = "rgba(0, 0, 0, .3)";
    ctx.shadowBlur = 18 * unit;
    ctx.shadowOffsetY = 6 * unit;
    Scene.roundedPath(ctx, x, y, box.w, box.h, (note.style === "sticky" ? 4 : 12) * unit);
    ctx.fillStyle = spec.background;
    ctx.fill();
    ctx.restore();
    if (spec.border) {
      ctx.lineWidth = Math.max(1, unit);
      ctx.strokeStyle = spec.border;
      Scene.roundedPath(ctx, x, y, box.w, box.h, 12 * unit);
      ctx.stroke();
    }
    if (spec.bar) {
      ctx.fillStyle = spec.bar;
      Scene.roundedPath(ctx, x, y, 6 * unit, box.h, 3 * unit);
      ctx.fill();
    }
    if (note.style === "sticky") {
      ctx.fillStyle = "rgba(255, 255, 255, .5)";
      ctx.fillRect(x + box.w / 2 - 40 * unit, y - 9 * unit, 80 * unit, 20 * unit);
    }
    if (note.style === "code") {
      ["#f87171", "#fbbf24", "#4ade80"].forEach((color, index) => {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x + pad + index * 14 * unit, y + 16 * unit, 4 * unit, 0, Math.PI * 2);
        ctx.fill();
      });
    }
    ctx.font = spec.font(unit);
    ctx.fillStyle = spec.color;
    ctx.textBaseline = "middle";
    ctx.textAlign = note.style === "title" ? "center" : "left";
    const textX = note.style === "title" ? x + left / 2 + box.w / 2 : x + pad + left;
    box.lines.forEach((line, index) => ctx.fillText(line, textX, y + top + pad + (index + 0.5) * spec.line * unit));
    ctx.restore();
  }

  function loadNotes() {
    try {
      const saved = JSON.parse(localStorage.getItem(NOTES_KEY) || "[]");
      return Array.isArray(saved) ? saved.filter(note => typeof note?.text === "string").slice(0, MAX_NOTES).map((note, index) => ({ id: index + 1, text: note.text.slice(0, 240), style: NOTE_STYLES[note.style] ? note.style : "sticky", ax: clamp(Number(note.ax) || 0, 0, 1), ay: clamp(Number(note.ay) || 0, 0, 1), shown: false, shownAt: 0 })) : [];
    } catch {
      return []; // private browsing or blocked storage
    }
  }

  /*
   * dialog: the recorder dialog (toolbar, preview canvas, and notes pane are found inside it).
   * settings / save: the recorder's remembered settings (tool, inkColor, inkSize, fadeInk, paper, noteStyle, notePlace).
   * redraw(): draw a frame now, so ink follows the pen without waiting for the next tick.
   * say(text, tone): show a status message. onBoard(on): the whiteboard was turned on or off.
   */
  function create(dialog, { settings, save, redraw, say, onBoard }) {
    const canvas = dialog.querySelector("[data-recorder-live]");
    const toolbar = dialog.querySelector("[data-ink-toolbar]");
    const pagesBox = toolbar.querySelector("[data-ink-pages]");
    const pageLabel = toolbar.querySelector("[data-ink-page]");
    const noteText = dialog.querySelector("[data-note-text]");
    const noteList = dialog.querySelector("[data-note-list]");
    const noteEmpty = dialog.querySelector("[data-note-empty]");
    let screenInk = [];
    let pages = [[]];
    let page = 0;
    let board = false;
    let history = [];
    let active = null; // the line being drawn
    let erasing = false;
    let dragging = null; // a note being moved
    let trail = [];
    let screenRect = null; // where the screen sits in the frame, for zoom
    let papers = {};
    let zoomCanvas = null;
    let pending = 0;
    let lastStep = 0;
    const pointer = { x: 0.5, y: 0.5, inside: false };
    const zoom = { scale: 1, x: 0.5, y: 0.5, target: 1, tx: 0.5, ty: 0.5 };
    let notes = loadNotes();
    let nextId = notes.length + 1;

    const layer = () => (board ? pages[page] : screenInk);
    const schedule = () => { if (!pending) pending = requestAnimationFrame(() => { pending = 0; redraw(); }); };
    const remember = list => { history.push({ list, before: list.slice() }); if (history.length > 100) history.shift(); };
    const saveNotes = () => {
      try {
        localStorage.setItem(NOTES_KEY, JSON.stringify(notes.map(({ text, style, ax, ay }) => ({ text, style, ax, ay }))));
      } catch {
        // not saved; the notes still work for this visit
      }
    };

    function sync() {
      toolbar.querySelectorAll("[data-ink-tool]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.inkTool === settings.tool)));
      toolbar.querySelectorAll("[data-ink-color]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.inkColor === settings.inkColor)));
      toolbar.querySelectorAll("[data-ink-size]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.inkSize === settings.inkSize)));
      toolbar.querySelector('[data-ink-action="fade"]').setAttribute("aria-pressed", String(Boolean(settings.fadeInk)));
      toolbar.querySelector('[data-ink-action="board"]').setAttribute("aria-pressed", String(board));
      pagesBox.hidden = !board;
      pageLabel.textContent = `${page + 1} / ${pages.length}`;
      toolbar.querySelector('[data-ink-action="prev-page"]').disabled = page === 0;
      toolbar.querySelector('[data-ink-action="next-page"]').disabled = page === pages.length - 1;
      canvas.dataset.tool = settings.tool;
      canvas.dataset.zoomed = String(zoom.target > 1);
      toolbar.dataset.board = String(board);
    }

    function setTool(tool) {
      settings.tool = tool;
      save();
      if (tool === "zoom" && (board || !screenRect)) say(board ? "Zoom works on your screen. Turn off the whiteboard to use it." : "Zoom works when you record your screen.", "warn");
      sync();
      schedule();
    }

    function setColor(color) {
      settings.inkColor = color;
      save();
      if (!["pen", "highlighter", "arrow", "box"].includes(settings.tool)) settings.tool = "pen";
      sync();
    }

    function setBoard(on) {
      board = Boolean(on);
      zoom.target = zoom.scale = 1;
      // Keep the ink visible on the paper: dark ink on light paper, light ink on the chalkboard.
      const light = LIGHT_PAPER.has(settings.paper);
      if (board && light && settings.inkColor === "#ffffff") settings.inkColor = "#0f172a";
      if (board && !light && settings.inkColor === "#0f172a") settings.inkColor = "#ffffff";
      if (board && ["pointer", "spotlight", "zoom"].includes(settings.tool)) settings.tool = "pen";
      save();
      sync();
      onBoard?.(board);
      schedule();
    }

    function undo() {
      const step = history.pop();
      if (!step) return;
      step.list.splice(0, step.list.length, ...step.before);
      schedule();
    }

    function clear() {
      const list = layer();
      if (!list.length) return;
      remember(list);
      list.length = 0;
      say("Drawing cleared. Press Ctrl+Z to bring it back.", "ok");
      schedule();
    }

    function turnPage(step) {
      if (step === "new") {
        pages.splice(page + 1, 0, []);
        page += 1;
      } else {
        page = clamp(page + step, 0, pages.length - 1);
      }
      sync();
      schedule();
    }

    // Point on the preview, as fractions of the frame.
    function framePoint(event) {
      const rect = canvas.getBoundingClientRect();
      return [clamp((event.clientX - rect.left) / rect.width, 0, 1), clamp((event.clientY - rect.top) / rect.height, 0, 1)];
    }

    function noteAt([x, y]) {
      return [...notes].reverse().find(note => note.shown && note.box && x >= note.box.x && x <= note.box.x + note.box.w && y >= note.box.y && y <= note.box.y + note.box.h);
    }

    // The point on the screen recording (fractions) under a point of the frame, given the current zoom.
    function screenPoint([x, y]) {
      if (!screenRect || x < screenRect.x || x > screenRect.x + screenRect.w || y < screenRect.y || y > screenRect.y + screenRect.h) return null;
      const u = (x - screenRect.x) / screenRect.w;
      const v = (y - screenRect.y) / screenRect.h;
      const view = 1 / zoom.scale;
      const left = clamp(zoom.x - view / 2, 0, 1 - view);
      const top = clamp(zoom.y - view / 2, 0, 1 - view);
      return [left + u * view, top + v * view];
    }

    function zoomClick(point) {
      if (board || !screenRect) return setTool("zoom");
      if (zoom.target > 1) {
        zoom.target = 1;
      } else {
        const target = screenPoint(point);
        if (!target) return;
        [zoom.tx, zoom.ty] = target;
        zoom.target = 2;
      }
      sync();
    }

    function eraseAt([x, y]) {
      const list = layer();
      const kept = list.filter(stroke => !strokeHit(stroke, x * 1600, y * 900, 14));
      if (kept.length !== list.length) list.splice(0, list.length, ...kept);
    }

    canvas.addEventListener("pointerdown", event => {
      if (event.button !== 0) return;
      const point = framePoint(event);
      Object.assign(pointer, { x: point[0], y: point[1], inside: true });
      const tool = settings.tool;
      if (tool === "pointer") {
        const note = noteAt(point);
        if (note) {
          dragging = { note, from: point, ax: note.ax, ay: note.ay };
          canvas.setPointerCapture(event.pointerId);
          canvas.dataset.dragging = "true";
        }
        return;
      }
      if (tool === "zoom") return zoomClick(point);
      if (tool === "spotlight") return;
      event.preventDefault();
      canvas.setPointerCapture(event.pointerId);
      if (tool === "eraser") {
        remember(layer());
        erasing = true;
        eraseAt(point);
      } else {
        active = { tool, color: settings.inkColor, size: settings.inkSize, points: [point] };
      }
      schedule();
    });
    canvas.addEventListener("pointermove", event => {
      const point = framePoint(event);
      Object.assign(pointer, { x: point[0], y: point[1], inside: true });
      const now = performance.now();
      if (settings.tool === "pointer") {
        trail.push({ x: point[0], y: point[1], t: now });
        if (!dragging) canvas.dataset.overNote = String(Boolean(noteAt(point)));
      }
      if (dragging) {
        const { note, from } = dragging;
        const box = note.box || { w: 0.2, h: 0.2 };
        const freeX = 1 - box.w - (NOTE_MARGIN * 2) / 1280;
        const freeY = 1 - box.h - (NOTE_MARGIN * 2) / 720;
        note.ax = clamp(dragging.ax + (freeX > 0.01 ? (point[0] - from[0]) / freeX : 0), 0, 1);
        note.ay = clamp(dragging.ay + (freeY > 0.01 ? (point[1] - from[1]) / freeY : 0), 0, 1);
      } else if (erasing) {
        eraseAt(point);
      } else if (active) {
        if (active.tool === "arrow" || active.tool === "box") active.points = [active.points[0], point];
        else {
          const [lx, ly] = active.points[active.points.length - 1];
          if (Math.hypot((point[0] - lx) * 16, (point[1] - ly) * 9) > 0.02) active.points.push(point);
        }
      }
      schedule();
    });
    const finish = () => {
      if (active) {
        const [first] = active.points;
        const last = active.points[active.points.length - 1];
        const tiny = Math.hypot((last[0] - first[0]) * 16, (last[1] - first[1]) * 9) < 0.15;
        if (!((active.tool === "arrow" || active.tool === "box") && tiny)) {
          remember(layer());
          layer().push({ ...active, done: performance.now() });
        }
        active = null;
      }
      if (dragging) {
        saveNotes();
        dragging = null;
        delete canvas.dataset.dragging;
      }
      erasing = false;
      schedule();
    };
    canvas.addEventListener("pointerup", finish);
    canvas.addEventListener("pointercancel", finish);
    canvas.addEventListener("pointerleave", () => {
      if (!active && !dragging && !erasing) pointer.inside = false;
      schedule();
    });
    canvas.addEventListener("wheel", event => {
      if (settings.tool !== "zoom" || board || !screenRect) return;
      event.preventDefault();
      const target = clamp(zoom.target * (event.deltaY < 0 ? 1.2 : 1 / 1.2), 1, MAX_ZOOM);
      if (target > zoom.target) {
        const point = screenPoint(framePoint(event));
        if (point) [zoom.tx, zoom.ty] = point;
      }
      zoom.target = target < 1.05 ? 1 : target;
      sync();
    }, { passive: false });

    toolbar.addEventListener("click", event => {
      const button = event.target.closest("button");
      if (!button) return;
      if (button.dataset.inkTool) return setTool(button.dataset.inkTool);
      if (button.dataset.inkColor) return setColor(button.dataset.inkColor);
      if (button.dataset.inkSize) {
        settings.inkSize = button.dataset.inkSize;
        save();
        return sync();
      }
      const action = button.dataset.inkAction;
      if (action === "fade") {
        settings.fadeInk = !settings.fadeInk;
        save();
        say(settings.fadeInk ? "Fading ink is on: new lines disappear a few seconds after you draw them." : "Fading ink is off: lines stay until you clear them.", "ok");
        sync();
      } else if (action === "undo") undo();
      else if (action === "clear") clear();
      else if (action === "board") setBoard(!board);
      else if (action === "prev-page") turnPage(-1);
      else if (action === "next-page") turnPage(1);
      else if (action === "new-page") turnPage("new");
    });

    // On-screen notes, written in the Notes tab and shown in the video one click at a time.
    function renderNotes() {
      noteList.replaceChildren(...notes.map((note, index) => {
        const item = document.createElement("li");
        item.className = `note-item is-${note.style}`;
        item.dataset.shown = String(note.shown);
        const key = document.createElement("span");
        key.className = "note-key";
        key.textContent = index < 9 ? String(index + 1) : "";
        const text = document.createElement("span");
        text.className = "note-text";
        text.textContent = note.text;
        const show = document.createElement("button");
        show.type = "button";
        show.className = "note-show";
        show.dataset.noteToggle = String(index);
        show.setAttribute("aria-pressed", String(note.shown));
        show.textContent = note.shown ? "Hide" : "Show";
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "note-delete";
        remove.dataset.noteDelete = String(index);
        remove.setAttribute("aria-label", `Delete note ${index + 1}`);
        remove.textContent = "×";
        item.append(key, text, show, remove);
        return item;
      }));
      noteEmpty.hidden = notes.length > 0;
    }

    function toggleNote(index) {
      const note = notes[index];
      if (!note) return;
      note.shown = !note.shown;
      note.shownAt = performance.now();
      renderNotes();
      schedule();
    }

    dialog.querySelector("[data-note-add]").addEventListener("click", () => {
      const text = noteText.value.replace(/\s+$/, "").replace(/^\s*\n/, "");
      if (!text.trim()) {
        noteText.focus();
        return say("Write the note first.", "warn");
      }
      if (notes.length >= MAX_NOTES) return say(`You can keep up to ${MAX_NOTES} notes. Delete one to add another.`, "warn");
      const [ax, ay] = NOTE_PLACES[settings.notePlace] || NOTE_PLACES["top-right"];
      notes.push({ id: nextId++, text: text.slice(0, 240), style: NOTE_STYLES[settings.noteStyle] ? settings.noteStyle : "sticky", ax, ay, shown: false, shownAt: 0 });
      noteText.value = "";
      saveNotes();
      renderNotes();
      say(notes.length <= 9 ? `Note added. Press ${notes.length} or click Show to put it in the video.` : "Note added. Click Show to put it in the video.", "ok");
    });
    noteList.addEventListener("click", event => {
      const toggle = event.target.closest("[data-note-toggle]");
      const remove = event.target.closest("[data-note-delete]");
      if (toggle) toggleNote(Number(toggle.dataset.noteToggle));
      if (remove) {
        notes.splice(Number(remove.dataset.noteDelete), 1);
        saveNotes();
        renderNotes();
        schedule();
      }
    });
    renderNotes();
    sync();

    return {
      get board() {
        return board;
      },
      // What to draw as the screen this frame: the whiteboard paper, the zoomed-in screen, or the screen.
      source(screen, w, h) {
        if (board) {
          const key = `${settings.paper}-${w}x${h}`;
          if (!papers[key]) papers = { [key]: drawPaper(settings.paper, w, h) };
          return papers[key];
        }
        const width = screen?.videoWidth;
        if (!width || zoom.scale < 1.01) return screen;
        const height = screen.videoHeight;
        const fit = Math.min(1, 1920 / width, 1080 / height);
        zoomCanvas ||= document.createElement("canvas");
        if (zoomCanvas.width !== Math.round(width * fit) || zoomCanvas.height !== Math.round(height * fit)) {
          zoomCanvas.width = Math.round(width * fit);
          zoomCanvas.height = Math.round(height * fit);
        }
        const viewW = width / zoom.scale;
        const viewH = height / zoom.scale;
        const sx = clamp(zoom.x * width - viewW / 2, 0, width - viewW);
        const sy = clamp(zoom.y * height - viewH / 2, 0, height - viewH);
        zoomCanvas.getContext("2d").drawImage(screen, sx, sy, viewW, viewH, 0, 0, zoomCanvas.width, zoomCanvas.height);
        return zoomCanvas;
      },
      // Ease the zoom toward its target, and let fading ink go.
      step(now) {
        const elapsed = lastStep ? Math.min(100, now - lastStep) : 16;
        lastStep = now;
        const ease = 1 - Math.exp(-elapsed / 140);
        zoom.scale += (zoom.target - zoom.scale) * ease;
        zoom.x += (zoom.tx - zoom.x) * ease;
        zoom.y += (zoom.ty - zoom.y) * ease;
        if (Math.abs(zoom.scale - zoom.target) < 0.003) zoom.scale = zoom.target;
        if (settings.fadeInk) {
          const list = layer();
          const kept = list.filter(stroke => now - stroke.done < FADE_AFTER + FADE_FOR);
          if (kept.length !== list.length) list.splice(0, list.length, ...kept);
        }
        trail = trail.filter(point => now - point.t < LASER_TRAIL);
      },
      // Ink, the spotlight, notes, and the laser pointer, on top of the scene.
      drawOver(ctx, w, h, layout, now) {
        screenRect = layout?.screen ? { x: layout.screen.x / w, y: layout.screen.y / h, w: layout.screen.w / w, h: layout.screen.h / h } : null;
        const unit = h / 720;
        for (const stroke of layer()) {
          const age = now - stroke.done;
          drawStroke(ctx, stroke, w, h, settings.fadeInk ? clamp(1 - (age - FADE_AFTER) / FADE_FOR, 0, 1) : 1);
        }
        if (active) drawStroke(ctx, active, w, h, 1);
        if (settings.tool === "spotlight" && pointer.inside) {
          const x = pointer.x * w;
          const y = pointer.y * h;
          const radius = h * 0.16;
          const dim = ctx.createRadialGradient(x, y, radius * 0.82, x, y, radius * 1.2);
          dim.addColorStop(0, "rgba(2, 6, 23, 0)");
          dim.addColorStop(1, "rgba(2, 6, 23, .68)");
          ctx.fillStyle = dim;
          ctx.fillRect(0, 0, w, h);
        }
        for (const note of notes) if (note.shown) drawNote(ctx, note, w, h, now);
        if (settings.tool === "pointer") {
          ctx.save();
          ctx.lineCap = "round";
          for (let index = 1; index < trail.length; index += 1) {
            const fade = 1 - (now - trail[index].t) / LASER_TRAIL;
            ctx.strokeStyle = `rgba(239, 68, 68, ${(fade * 0.7).toFixed(3)})`;
            ctx.lineWidth = fade * 7 * unit + unit;
            ctx.beginPath();
            ctx.moveTo(trail[index - 1].x * w, trail[index - 1].y * h);
            ctx.lineTo(trail[index].x * w, trail[index].y * h);
            ctx.stroke();
          }
          if (pointer.inside && !dragging && trail.length && now - trail[trail.length - 1].t < 1500) {
            const x = pointer.x * w;
            const y = pointer.y * h;
            const glow = ctx.createRadialGradient(x, y, 0, x, y, 22 * unit);
            glow.addColorStop(0, "rgba(239, 68, 68, .55)");
            glow.addColorStop(1, "rgba(239, 68, 68, 0)");
            ctx.fillStyle = glow;
            ctx.beginPath();
            ctx.arc(x, y, 22 * unit, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = "#ef4444";
            ctx.strokeStyle = "#fff";
            ctx.lineWidth = 2 * unit;
            ctx.beginPath();
            ctx.arc(x, y, 6.5 * unit, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
          }
          ctx.restore();
        }
      },
      // A fresh drawing for a new recording; notes are kept but hidden.
      reset({ board: on = false } = {}) {
        screenInk = [];
        pages = [[]];
        page = 0;
        history = [];
        active = null;
        dragging = null;
        erasing = false;
        trail = [];
        Object.assign(zoom, { scale: 1, x: 0.5, y: 0.5, target: 1, tx: 0.5, ty: 0.5 });
        notes.forEach(note => { note.shown = false; });
        renderNotes();
        settings.tool = "pointer"; // so a first click on the preview never draws by surprise; the whiteboard starts with the pen
        setBoard(on);
      },
      setBoard,
      paperChanged() {
        papers = {};
        setBoard(board); // also fixes the ink color for the new paper
      },
      // Drawing shortcuts while the studio is live. Returns true when the key was used.
      keydown(event) {
        const key = event.key.toLowerCase();
        if ((event.ctrlKey || event.metaKey) && !event.altKey && key === "z") {
          undo();
          return true;
        }
        if (event.ctrlKey || event.metaKey || event.altKey) return false;
        const tools = { l: "pointer", d: "pen", h: "highlighter", a: "arrow", b: "box", e: "eraser", f: "spotlight", z: "zoom" };
        if (tools[key]) setTool(tools[key]);
        else if (key === "w") setBoard(!board);
        else if (key === "c") clear();
        else if (/^[1-9]$/.test(key)) toggleNote(Number(key) - 1);
        else return false;
        return true;
      },
    };
  }

  return { create };
})();

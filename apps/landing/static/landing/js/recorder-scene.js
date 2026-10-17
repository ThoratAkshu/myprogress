// Learning studio scenes: draw the screen and camera into one video frame with a layout template
// (full screen, framed, or side by side), and draw styled thumbnails from a frame. The "screen" can also
// be a canvas, such as the whiteboard paper or a zoomed-in screen.
window.StudioScene = (() => {
  const BACKGROUNDS = {
    midnight: ["#0f172a", "#1e3a8a"],
    ocean: ["#1d4ed8", "#0ea5e9"],
    sunset: ["#f97316", "#db2777"],
    forest: ["#065f46", "#0d9488"],
    graphite: ["#111827", "#374151"],
  };
  const CAMERA_SIZES = { small: 0.19, medium: 0.26, large: 0.34 };
  const FONT = '"DM Sans", "Segoe UI", system-ui, sans-serif';
  const DISPLAY_FONT = 'Manrope, "DM Sans", "Segoe UI", system-ui, sans-serif';
  // Video elements report their size as videoWidth (0 until a frame arrives); canvases as width.
  const sizeOf = source => ({ width: source.videoWidth ?? source.width, height: source.videoHeight ?? source.height });
  const ready = source => Boolean(source && sizeOf(source).width);

  function roundedPath(ctx, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  }

  function fillBackground(ctx, w, h, name) {
    const [from, to] = BACKGROUNDS[name] || BACKGROUNDS.midnight;
    const gradient = ctx.createLinearGradient(0, 0, w, h);
    gradient.addColorStop(0, from);
    gradient.addColorStop(1, to);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, w, h);
  }

  // Fit the whole video inside the box (letterboxed); returns where it landed.
  function containRect(video, x, y, w, h) {
    const size = sizeOf(video);
    const scale = Math.min(w / size.width, h / size.height);
    const width = size.width * scale;
    const height = size.height * scale;
    return { x: x + (w - width) / 2, y: y + (h - height) / 2, w: width, h: height };
  }

  // Fill the box with the video, cropping the edges.
  function drawCover(ctx, video, x, y, w, h, mirror) {
    const size = sizeOf(video);
    const scale = Math.max(w / size.width, h / size.height);
    const sw = w / scale;
    const sh = h / scale;
    const sx = (size.width - sw) / 2;
    const sy = (size.height - sh) / 2;
    ctx.save();
    if (mirror) {
      ctx.translate(x + w, y);
      ctx.scale(-1, 1);
      ctx.drawImage(video, sx, sy, sw, sh, 0, 0, w, h);
    } else {
      ctx.drawImage(video, sx, sy, sw, sh, x, y, w, h);
    }
    ctx.restore();
  }

  function drawFramedVideo(ctx, video, rect, radius) {
    ctx.save();
    ctx.shadowColor = "rgba(0, 0, 0, .35)";
    ctx.shadowBlur = radius * 2;
    ctx.shadowOffsetY = radius / 2;
    roundedPath(ctx, rect.x, rect.y, rect.w, rect.h, radius);
    ctx.fillStyle = "#000";
    ctx.fill();
    ctx.restore();
    ctx.save();
    roundedPath(ctx, rect.x, rect.y, rect.w, rect.h, radius);
    ctx.clip();
    ctx.drawImage(video, rect.x, rect.y, rect.w, rect.h);
    ctx.restore();
  }

  function cameraPath(ctx, x, y, w, h, shape) {
    if (shape === "circle") {
      ctx.beginPath();
      ctx.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2);
    } else {
      roundedPath(ctx, x, y, w, h, Math.min(w, h) * 0.16);
    }
  }

  function drawCamera(ctx, video, x, y, w, h, options) {
    ctx.save();
    ctx.shadowColor = "rgba(0, 0, 0, .35)";
    ctx.shadowBlur = w * 0.08;
    cameraPath(ctx, x, y, w, h, options.shape);
    ctx.fillStyle = "#0f172a";
    ctx.fill();
    ctx.restore();
    ctx.save();
    cameraPath(ctx, x, y, w, h, options.shape);
    ctx.clip();
    drawCover(ctx, video, x, y, w, h, options.mirror);
    ctx.restore();
    ctx.lineWidth = Math.max(3, w * 0.025);
    ctx.strokeStyle = "#fff";
    cameraPath(ctx, x, y, w, h, options.shape);
    ctx.stroke();
  }

  // The camera bubble in a corner of `area` (the whole canvas, or the framed screen).
  function cornerCamera(ctx, video, area, canvasW, canvasH, options) {
    const size = Math.round(Math.min(canvasW, canvasH) * (CAMERA_SIZES[options.size] || CAMERA_SIZES.medium));
    const margin = Math.round(size * 0.12);
    const [vertical, horizontal] = (options.position || "bottom-right").split("-");
    const x = horizontal === "left" ? area.x + margin : area.x + area.w - size - margin;
    const y = vertical === "top" ? area.y + margin : area.y + area.h - size - margin;
    drawCamera(ctx, video, x, y, size, size, options);
  }

  function wrapLines(ctx, text, maxWidth, maxLines) {
    const words = String(text || "").split(/\s+/).filter(Boolean);
    const lines = [];
    let line = "";
    for (const word of words) {
      const next = line ? `${line} ${word}` : word;
      if (ctx.measureText(next).width <= maxWidth || !line) line = next;
      else {
        lines.push(line);
        line = word;
        if (lines.length === maxLines) break;
      }
    }
    if (line && lines.length < maxLines) lines.push(line);
    if (lines.length === maxLines && words.join(" ") !== lines.join(" ")) {
      let last = lines[maxLines - 1];
      while (last && ctx.measureText(`${last}…`).width > maxWidth) last = last.slice(0, -1);
      lines[maxLines - 1] = `${last.trimEnd()}…`;
    }
    return lines;
  }

  // Lower-third name tag: the presenter's name and what the video is about.
  function nameTag(ctx, w, h, options, side) {
    const name = (options.name || "").trim();
    const subtitle = (options.subtitle || "").trim();
    if (!options.nameTag || (!name && !subtitle)) return;
    const unit = h / 720;
    const padX = 18 * unit;
    ctx.font = `800 ${24 * unit}px ${DISPLAY_FONT}`;
    const nameWidth = ctx.measureText(name).width;
    ctx.font = `500 ${16 * unit}px ${FONT}`;
    const subtitleLine = wrapLines(ctx, subtitle, w * 0.42, 1)[0] || "";
    const subtitleWidth = ctx.measureText(subtitleLine).width;
    const boxW = Math.max(nameWidth, subtitleWidth) + padX * 2 + 6 * unit;
    const boxH = (subtitleLine && name ? 70 : 46) * unit;
    const x = side === "right" ? w - boxW - 28 * unit : 28 * unit;
    const y = h - boxH - 26 * unit;
    ctx.save();
    ctx.shadowColor = "rgba(0, 0, 0, .3)";
    ctx.shadowBlur = 16 * unit;
    roundedPath(ctx, x, y, boxW, boxH, 12 * unit);
    ctx.fillStyle = "rgba(255, 255, 255, .96)";
    ctx.fill();
    ctx.restore();
    ctx.fillStyle = options.accent || "#16a34a";
    roundedPath(ctx, x, y, 6 * unit, boxH, 3 * unit);
    ctx.fill();
    ctx.textBaseline = "alphabetic";
    let baseline = y + (name && subtitleLine ? 31 : 30) * unit;
    if (name) {
      ctx.font = `800 ${24 * unit}px ${DISPLAY_FONT}`;
      ctx.fillStyle = "#0f172a";
      ctx.fillText(name, x + padX + 6 * unit, baseline);
      baseline += 25 * unit;
    }
    if (subtitleLine) {
      ctx.font = `500 ${16 * unit}px ${FONT}`;
      ctx.fillStyle = "#475569";
      ctx.fillText(subtitleLine, x + padX + 6 * unit, name ? baseline : y + 29 * unit);
    }
  }

  /*
   * Draw one video frame.
   * sources: { screen, camera } video elements or canvases (either may be missing)
   * options: { layout: "full" | "framed" | "side", position, size, shape, background, mirror,
   *            showCamera, nameTag, name, subtitle, accent }
   * Returns { screen: {x, y, w, h} } with where the screen landed, or { screen: null }.
   */
  function draw(ctx, w, h, sources, options) {
    const screen = ready(sources.screen) ? sources.screen : null;
    const camera = ready(sources.camera) && options.showCamera !== false ? sources.camera : null;
    const layout = options.layout || "full";
    const tagSide = (options.position || "").endsWith("left") ? "right" : "left";
    if (!screen) {
      if (!camera) {
        fillBackground(ctx, w, h, options.background);
        return { screen: null };
      }
      if (layout === "full") drawCover(ctx, camera, 0, 0, w, h, options.mirror);
      else {
        fillBackground(ctx, w, h, options.background);
        const pad = w * 0.06;
        const rect = { x: pad, y: pad, w: w - pad * 2, h: h - pad * 2 };
        ctx.save();
        roundedPath(ctx, rect.x, rect.y, rect.w, rect.h, w * 0.02);
        ctx.clip();
        drawCover(ctx, camera, rect.x, rect.y, rect.w, rect.h, options.mirror);
        ctx.restore();
      }
      nameTag(ctx, w, h, options, "left");
      return { screen: null };
    }
    if (layout === "side" && camera) {
      fillBackground(ctx, w, h, options.background);
      const pad = w * 0.035;
      const column = w * 0.26;
      const area = containRect(screen, pad, pad, w - column - pad * 3, h - pad * 2);
      drawFramedVideo(ctx, screen, area, w * 0.012);
      const cardW = column;
      const cardH = Math.min(h - pad * 2 - (options.nameTag ? h * 0.16 : 0), cardW * 1.3);
      const cardX = w - column - pad;
      const cardY = options.nameTag ? pad : (h - cardH) / 2;
      drawCamera(ctx, camera, cardX, cardY, cardW, cardH, { ...options, shape: "rounded" });
      if (options.nameTag) {
        const unit = h / 720;
        ctx.textAlign = "left";
        ctx.font = `800 ${26 * unit}px ${DISPLAY_FONT}`;
        ctx.fillStyle = "#fff";
        const nameLines = wrapLines(ctx, options.name, cardW, 2);
        nameLines.forEach((line, index) => ctx.fillText(line, cardX, cardY + cardH + (40 + index * 30) * unit));
        ctx.font = `500 ${17 * unit}px ${FONT}`;
        ctx.fillStyle = "rgba(255, 255, 255, .82)";
        wrapLines(ctx, options.subtitle, cardW, 2).forEach((line, index) => ctx.fillText(line, cardX, cardY + cardH + (44 + nameLines.length * 30 + index * 22) * unit));
      }
      return { screen: area };
    }
    if (layout === "framed") {
      fillBackground(ctx, w, h, options.background);
      const pad = w * 0.045;
      const bottom = options.nameTag ? h * 0.11 : pad;
      const area = containRect(screen, pad, pad, w - pad * 2, h - pad - bottom);
      drawFramedVideo(ctx, screen, area, w * 0.012);
      if (camera) cornerCamera(ctx, camera, area, w, h, options);
      nameTag(ctx, w, h, options, tagSide);
      return { screen: area };
    }
    ctx.fillStyle = "#0b1220";
    ctx.fillRect(0, 0, w, h);
    const area = containRect(screen, 0, 0, w, h);
    ctx.drawImage(screen, area.x, area.y, area.w, area.h);
    if (camera) cornerCamera(ctx, camera, { x: 0, y: 0, w, h }, w, h, options);
    nameTag(ctx, w, h, options, tagSide);
    return { screen: area };
  }

  /*
   * A 1280x720 thumbnail from a video frame.
   * style: "plain" (the frame), "title" (frame with the title over a dark fade), "card" (title on a colored panel beside the frame)
   */
  function thumbnail(video, style, options) {
    const w = 1280;
    const h = 720;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    const title = (options.title || "").trim() || "How I built it";
    const name = (options.name || "").trim();
    if (style === "card") {
      fillBackground(ctx, w, h, options.background);
      const rect = containRect(video, w * 0.46, h * 0.12, w * 0.5, h * 0.76);
      drawFramedVideo(ctx, video, rect, 18);
      ctx.fillStyle = "#fff";
      ctx.font = `800 64px ${DISPLAY_FONT}`;
      const lines = wrapLines(ctx, title, w * 0.36, 4);
      const top = h / 2 - (lines.length * 74) / 2 + 40;
      lines.forEach((line, index) => ctx.fillText(line, w * 0.05, top + index * 74));
      if (name) {
        ctx.font = `600 28px ${FONT}`;
        ctx.fillStyle = "rgba(255, 255, 255, .85)";
        ctx.fillText(name, w * 0.05, top + lines.length * 74 + 24);
      }
    } else {
      drawCover(ctx, video, 0, 0, w, h, false);
      if (style === "title") {
        const fade = ctx.createLinearGradient(0, h * 0.35, 0, h);
        fade.addColorStop(0, "rgba(2, 6, 23, 0)");
        fade.addColorStop(1, "rgba(2, 6, 23, .9)");
        ctx.fillStyle = fade;
        ctx.fillRect(0, 0, w, h);
        ctx.font = `800 66px ${DISPLAY_FONT}`;
        const lines = wrapLines(ctx, title, w * 0.86, 2);
        ctx.fillStyle = "#fff";
        const bottom = h - (name ? 96 : 56);
        lines.forEach((line, index) => ctx.fillText(line, 60, bottom - (lines.length - 1 - index) * 76));
        if (name) {
          ctx.font = `600 28px ${FONT}`;
          ctx.fillStyle = "rgba(255, 255, 255, .85)";
          ctx.fillText(name, 60, h - 48);
        }
      }
    }
    return new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.88));
  }

  return { BACKGROUNDS, FONT, DISPLAY_FONT, draw, thumbnail, roundedPath, wrapLines, sizeOf };
})();

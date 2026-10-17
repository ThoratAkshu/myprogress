// Learning studio editor: trim the start and end of a video and cut out any parts on a timeline with a
// filmstrip. While editing, playback skips the removed parts. Browsers can't cut a video file directly, so
// the edit is saved by playing the kept parts once into a new recording, with chapters and captions moved
// to match.
window.StudioEditor = (() => {
  const MIN_CUT = 0.2; // shortest part that can be cut, in seconds
  const MIN_KEEP = 1; // the edit keeps at least this much video
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const formatTime = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
  const formatPrecise = seconds => `${formatTime(seconds)}.${Math.floor((seconds % 1) * 10)}`;

  // Wait until the video has a frame to show; false if it can't be played.
  async function whenReady(video, ms = 10000) {
    const deadline = Date.now() + ms;
    while (video.readyState < 2 || !video.videoWidth) {
      if (video.error || Date.now() > deadline) return false;
      await wait(50);
    }
    return true;
  }

  function seek(video, time) {
    return new Promise(resolve => {
      if (Math.abs(video.currentTime - time) < 0.01 && !video.seeking) return resolve();
      const done = () => { clearTimeout(timer); video.removeEventListener("seeked", done); resolve(); };
      const timer = setTimeout(done, 4000);
      video.addEventListener("seeked", done);
      video.currentTime = time;
    });
  }

  // Videos recorded in a browser often don't say how long they are (the duration reads as Infinity). Seeking
  // far past the end makes the browser read to the end and work it out.
  function findDuration(video) {
    if (Number.isFinite(video.duration)) return Promise.resolve(video.duration);
    return new Promise(resolve => {
      const done = () => {
        clearTimeout(timer);
        video.removeEventListener("durationchange", check);
        const duration = video.duration;
        video.currentTime = 0;
        resolve(Number.isFinite(duration) ? duration : 0);
      };
      const check = () => { if (Number.isFinite(video.duration)) done(); };
      const timer = setTimeout(done, 8000);
      video.addEventListener("durationchange", check);
      video.currentTime = 1e101;
    });
  }

  // The parts of the video that stay, as [start, end] pairs in seconds.
  function keptParts(edit) {
    const parts = [];
    let from = edit.start;
    for (const [a, b] of edit.cuts) {
      if (b <= from || a >= edit.end) continue;
      if (a > from) parts.push([from, Math.min(a, edit.end)]);
      from = Math.max(from, b);
    }
    if (edit.end > from) parts.push([from, edit.end]);
    return parts.filter(([a, b]) => b - a >= 0.05);
  }
  const partsLength = parts => parts.reduce((total, [a, b]) => total + b - a, 0);

  // Where a moment of the original lands in the edit; moments in a removed part move to where the next
  // kept part starts. null when it is past the end.
  function mapTime(time, parts) {
    let offset = 0;
    for (const [a, b] of parts) {
      if (time < a) return offset;
      if (time <= b) return offset + time - a;
      offset += b - a;
    }
    return null;
  }

  // Chapters as { time, title } in whole seconds; when two land on the same second, the later one wins.
  function remapChapters(chapters, parts) {
    const total = partsLength(parts);
    const moved = new Map();
    for (const chapter of [...chapters].sort((a, b) => a.time - b.time)) {
      const time = mapTime(chapter.time, parts);
      if (time !== null && time < total - 1) moved.set(Math.floor(time), { time: Math.floor(time), title: chapter.title });
    }
    return [...moved.values()];
  }

  const CUE = /^((?:\d+:)?\d{1,2}:\d{2}[.,]\d{3})\s+-->\s+((?:\d+:)?\d{1,2}:\d{2}[.,]\d{3})/;
  const stampSeconds = stamp => stamp.replace(",", ".").split(":").reduce((total, part) => total * 60 + Number(part), 0);
  const stamp = seconds => {
    const pad = (value, size = 2) => String(value).padStart(size, "0");
    return `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor((seconds % 3600) / 60))}:${pad(Math.floor(seconds % 60))}.${pad(Math.floor((seconds % 1) * 1000), 3)}`;
  };

  // WebVTT captions with cues in removed parts dropped and the rest moved to match the edit.
  function remapCaptions(vtt, parts) {
    const cues = [];
    for (const block of (vtt || "").replace(/\r\n/g, "\n").split(/\n\s*\n/)) {
      const lines = block.trim().split("\n");
      const index = lines.findIndex(line => CUE.test(line.trim()));
      if (index < 0) continue;
      const [, from, to] = lines[index].trim().match(CUE);
      const text = lines.slice(index + 1).join("\n").trim();
      const start = stampSeconds(from);
      const end = stampSeconds(to);
      const kept = parts.filter(([a, b]) => b > start && a < end);
      if (!text || !kept.length) continue;
      const newStart = mapTime(Math.max(start, kept[0][0]), parts);
      const newEnd = mapTime(Math.min(end, kept[kept.length - 1][1]), parts);
      if (newEnd - newStart >= 0.2) cues.push({ start: newStart, end: newEnd, text });
    }
    if (!cues.length) return "";
    return `WEBVTT\n\n${cues.map((cue, index) => `${index + 1}\n${stamp(cue.start)} --> ${stamp(cue.end)}\n${cue.text}`).join("\n\n")}\n`;
  }

  /*
   * Save the edit: play each kept part of `src` once into a new recording.
   * options: { mimeType, bitrate(width, height), audioBitsPerSecond, mount (element to show the playback in),
   *            onProgress(fraction), signal (AbortSignal) }
   */
  async function render(src, parts, { mimeType, bitrate, audioBitsPerSecond, mount, onProgress, signal }) {
    const video = document.createElement("video");
    video.playsInline = true;
    video.preload = "auto";
    video.src = src;
    mount?.replaceChildren(video);
    let ticker = null;
    let audioContext = null;
    let canvasTrack = null;
    let recorder = null;
    let fail = () => {};
    const failed = new Promise((_, reject) => { fail = reject; });
    failed.catch(() => {});
    const abort = () => fail(new DOMException("Cancelled", "AbortError"));
    signal?.addEventListener("abort", abort, { once: true });
    try {
      if (signal?.aborted) abort();
      if (!await Promise.race([whenReady(video), failed])) throw new Error("This video can't be played in the browser, so the edit can't be saved.");
      const fit = Math.min(1, 1920 / video.videoWidth, 1080 / video.videoHeight);
      const width = Math.round((video.videoWidth * fit) / 2) * 2;
      const height = Math.round((video.videoHeight * fit) / 2) * 2;
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      const paint = () => context.drawImage(video, 0, 0, width, height);
      // The sound goes into the new recording only, so saving is silent.
      audioContext = new AudioContext();
      const destination = audioContext.createMediaStreamDestination();
      audioContext.createMediaElementSource(video).connect(destination);
      await audioContext.resume().catch(() => {});
      canvasTrack = canvas.captureStream(30).getVideoTracks()[0];
      const stream = new MediaStream([canvasTrack, ...destination.stream.getAudioTracks()]);
      recorder = new MediaRecorder(stream, { ...(mimeType && { mimeType }), videoBitsPerSecond: bitrate(width, height), audioBitsPerSecond });
      const chunks = [];
      recorder.addEventListener("dataavailable", event => { if (event.data.size) chunks.push(event.data); });
      const stopped = new Promise(resolve => recorder.addEventListener("stop", resolve, { once: true }));
      const total = partsLength(parts);
      let done = 0;
      let part = null;
      let reached = null;
      let lastTime = -1;
      let lastMove = performance.now();
      // A worker clock keeps frames coming even if the page's timers slow down.
      const clockUrl = URL.createObjectURL(new Blob(["setInterval(() => postMessage(0), 1000 / 30)"], { type: "text/javascript" }));
      ticker = new Worker(clockUrl);
      URL.revokeObjectURL(clockUrl);
      ticker.onmessage = () => {
        paint();
        if (!part) return;
        const time = video.currentTime;
        onProgress?.(clamp((done + time - part[0]) / total, 0, 1));
        if (time !== lastTime) {
          lastTime = time;
          lastMove = performance.now();
        } else if (!video.paused && performance.now() - lastMove > 15000) {
          fail(new Error("The video stopped playing, so the edit couldn't be saved. Keep this tab open and try again."));
        }
        if (reached && (time >= part[1] - 0.02 || video.ended)) {
          const finish = reached;
          reached = null;
          finish();
        }
      };
      for (const [index, kept] of parts.entries()) {
        await Promise.race([seek(video, kept[0]), failed]);
        paint();
        if (index === 0) recorder.start(1000);
        else recorder.resume();
        part = kept;
        const partDone = new Promise(resolve => { reached = resolve; });
        await Promise.race([video.play(), failed]);
        await Promise.race([partDone, failed]);
        video.pause();
        recorder.pause();
        done += kept[1] - kept[0];
        part = null;
      }
      onProgress?.(1);
      recorder.stop();
      await Promise.race([stopped, failed]);
      return new Blob(chunks, { type: (recorder.mimeType || "video/webm").split(";")[0] });
    } finally {
      signal?.removeEventListener("abort", abort);
      ticker?.terminate();
      if (recorder && recorder.state !== "inactive") recorder.stop();
      canvasTrack?.stop();
      audioContext?.close().catch(() => {});
      video.pause();
      video.removeAttribute("src");
      video.load();
      mount?.replaceChildren();
    }
  }

  /*
   * The timeline under the review player.
   * root: the [data-clip-editor] element; video: the review player.
   * onChange(): the edit changed. say(text, tone): show a status message.
   * snap(time, duration): optional; where an edit may land instead, for videos that can only be cut at keyframes.
   */
  function create(root, { video, onChange, say, snap }) {
    const track = root.querySelector("[data-clip-track]");
    const strip = root.querySelector("[data-clip-strip]");
    const marks = root.querySelector("[data-clip-marks]");
    const selectionBox = root.querySelector("[data-clip-selection]");
    const playhead = root.querySelector("[data-clip-playhead]");
    const summary = root.querySelector("[data-clip-summary]");
    const cutList = root.querySelector("[data-clip-cuts]");
    const handles = { start: root.querySelector('[data-clip-handle="start"]'), end: root.querySelector('[data-clip-handle="end"]') };
    const button = action => root.querySelector(`[data-clip-action="${action}"]`);
    let edit = { duration: 0, start: 0, end: 0, cuts: [] };
    let selection = null;
    let history = [];
    let chapters = [];
    let drag = null;
    let frame = 0;
    let filmToken = 0;
    let src = "";

    const percent = time => `${(edit.duration ? (time / edit.duration) * 100 : 0).toFixed(3)}%`;
    const timeAt = clientX => {
      const rect = track.getBoundingClientRect();
      return clamp((clientX - rect.left) / rect.width, 0, 1) * edit.duration;
    };
    const snapshot = () => JSON.stringify({ start: edit.start, end: edit.end, cuts: edit.cuts });
    const parts = () => keptParts(edit);
    const hasEdits = () => edit.duration > 0 && (edit.start > 0.05 || edit.end < edit.duration - 0.05 || parts().length > 1);

    function normalize() {
      if (snap) {
        edit.start = snap(edit.start, edit.duration);
        edit.end = snap(edit.end, edit.duration);
        edit.cuts = edit.cuts.map(([a, b]) => [snap(a, edit.duration), snap(b, edit.duration)]);
      }
      const cuts = edit.cuts.map(([a, b]) => [clamp(Math.min(a, b), 0, edit.duration), clamp(Math.max(a, b), 0, edit.duration)]).filter(([a, b]) => b - a >= MIN_CUT).sort((x, y) => x[0] - y[0]);
      edit.cuts = cuts.reduce((merged, cut) => {
        const last = merged[merged.length - 1];
        if (last && cut[0] <= last[1] + 0.05) last[1] = Math.max(last[1], cut[1]);
        else merged.push([...cut]);
        return merged;
      }, []);
    }

    // Change the edit with undo, refusing changes that would leave less than a second.
    function change(apply) {
      const before = snapshot();
      apply();
      normalize();
      if (partsLength(parts()) < MIN_KEEP) {
        Object.assign(edit, JSON.parse(before));
        say?.("Keep at least one second of video.", "warn");
      } else if (snapshot() !== before) {
        history.push(before);
      }
      refresh();
    }

    function refresh() {
      handles.start.style.left = percent(edit.start);
      handles.end.style.left = percent(edit.end);
      const removed = [];
      if (edit.start > 0) removed.push(["trim", 0, edit.start]);
      edit.cuts.filter(([a, b]) => b > edit.start && a < edit.end).forEach(([a, b]) => removed.push(["cut", Math.max(a, edit.start), Math.min(b, edit.end)]));
      if (edit.end < edit.duration) removed.push(["trim", edit.end, edit.duration]);
      marks.replaceChildren(
        ...removed.map(([kind, a, b]) => {
          const element = document.createElement("span");
          element.className = `clip-gone is-${kind}`;
          element.style.left = percent(a);
          element.style.width = percent(b - a);
          return element;
        }),
        ...chapters.filter(chapter => chapter.time > 0).map(chapter => {
          const tick = document.createElement("span");
          tick.className = "clip-chapter";
          tick.style.left = percent(chapter.time);
          tick.title = `${formatTime(chapter.time)} ${chapter.title}`;
          return tick;
        }),
      );
      selectionBox.hidden = !selection;
      if (selection) {
        selectionBox.style.left = percent(selection[0]);
        selectionBox.style.width = percent(selection[1] - selection[0]);
      }
      const length = partsLength(parts());
      const gone = edit.duration - length;
      summary.textContent = edit.duration ? `Final length ${formatTime(length)}${gone >= 0.1 ? ` · ${formatPrecise(gone)} removed` : ""}` : "";
      button("cut").disabled = !selection || selection[1] - selection[0] < MIN_CUT;
      button("undo").disabled = !history.length;
      button("reset").disabled = !hasEdits();
      const cuts = edit.cuts.map((cut, index) => [...cut, index]).filter(([a, b]) => b > edit.start && a < edit.end);
      cutList.replaceChildren(...cuts.map(([a, b, index]) => {
        const item = document.createElement("li");
        const label = document.createElement("span");
        label.textContent = `Cut ${formatPrecise(a)} – ${formatPrecise(b)}`;
        const restore = document.createElement("button");
        restore.type = "button";
        restore.dataset.clipRestore = String(index);
        restore.textContent = "Restore";
        item.append(label, restore);
        return item;
      }));
      track.setAttribute("aria-valuemax", String(Math.round(edit.duration)));
      onChange?.();
    }

    // Keep the playhead in step, and skip the removed parts while playing.
    function follow() {
      frame = requestAnimationFrame(follow);
      const time = video.currentTime;
      playhead.style.left = percent(time);
      track.setAttribute("aria-valuenow", String(Math.round(time)));
      track.setAttribute("aria-valuetext", formatPrecise(time));
      if (video.paused || video.seeking || !edit.duration) return;
      if (time < edit.start - 0.05) video.currentTime = edit.start;
      else if (time >= edit.end - 0.02 && edit.end < edit.duration - 0.05) {
        video.pause();
        video.currentTime = edit.end;
      } else {
        const cut = edit.cuts.find(([a, b]) => time >= a && time < b - 0.02);
        if (cut) video.currentTime = cut[1];
      }
    }
    video.addEventListener("play", () => {
      if (edit.duration && video.currentTime >= edit.end - 0.05) video.currentTime = edit.start;
    });

    async function filmstrip(token) {
      const count = clamp(Math.round((track.clientWidth || 640) / 72), 6, 18);
      const frames = Array.from({ length: count }, () => {
        const canvas = document.createElement("canvas");
        canvas.width = 128;
        canvas.height = 72;
        return canvas;
      });
      strip.replaceChildren(...frames);
      const probe = document.createElement("video");
      probe.muted = true;
      probe.playsInline = true;
      probe.preload = "auto";
      probe.src = src;
      try {
        if (!await whenReady(probe)) return;
        for (const [index, canvas] of frames.entries()) {
          if (token !== filmToken) return;
          await seek(probe, Math.min(edit.duration - 0.1, ((index + 0.5) * edit.duration) / count));
          if (token !== filmToken) return;
          const context = canvas.getContext("2d");
          const scale = Math.max(128 / probe.videoWidth, 72 / probe.videoHeight);
          const w = probe.videoWidth * scale;
          const h = probe.videoHeight * scale;
          context.drawImage(probe, (128 - w) / 2, (72 - h) / 2, w, h);
        }
      } finally {
        probe.removeAttribute("src");
        probe.load();
      }
    }

    track.addEventListener("pointerdown", event => {
      if (!edit.duration || event.button !== 0 || event.target.closest("button")) return;
      const handle = event.target.closest("[data-clip-handle]")?.dataset.clipHandle;
      track.setPointerCapture(event.pointerId);
      video.pause();
      if (handle) drag = { handle, before: snapshot() };
      else {
        const time = timeAt(event.clientX);
        drag = { from: time, x: event.clientX, moved: false };
        video.currentTime = time;
      }
      event.preventDefault();
      track.focus({ preventScroll: true });
    });
    track.addEventListener("pointermove", event => {
      if (!drag) return;
      const time = timeAt(event.clientX);
      if (drag.handle === "start") {
        edit.start = clamp(time, 0, edit.end - MIN_KEEP);
        video.currentTime = edit.start;
      } else if (drag.handle === "end") {
        edit.end = clamp(time, edit.start + MIN_KEEP, edit.duration);
        video.currentTime = edit.end;
      } else {
        drag.moved ||= Math.abs(event.clientX - drag.x) > 4;
        if (!drag.moved) return;
        selection = [Math.min(drag.from, time), Math.max(drag.from, time)];
        video.currentTime = time;
      }
      refresh();
    });
    const endDrag = () => {
      if (!drag) return;
      if (drag.handle) {
        normalize();
        if (partsLength(parts()) < MIN_KEEP) Object.assign(edit, JSON.parse(drag.before));
        else if (snapshot() !== drag.before) history.push(drag.before);
      } else if (!drag.moved) {
        selection = null;
      }
      drag = null;
      refresh();
    };
    track.addEventListener("pointerup", endDrag);
    track.addEventListener("pointercancel", endDrag);

    const actions = {
      play() {
        const [first] = parts();
        if (!first) return;
        video.currentTime = first[0];
        video.play().catch(() => {});
      },
      "start-here": () => change(() => { edit.start = clamp(video.currentTime, 0, edit.end - MIN_KEEP); }),
      "end-here": () => change(() => { edit.end = clamp(video.currentTime, edit.start + MIN_KEEP, edit.duration); }),
      "mark-in": () => {
        const time = video.currentTime;
        selection = [time, selection && selection[1] > time ? selection[1] : time];
        refresh();
        say?.(`Marked in at ${formatPrecise(time)}. Move to where the part ends and press Mark out (O).`);
      },
      "mark-out": () => {
        const time = video.currentTime;
        selection = [selection && selection[0] < time ? selection[0] : time, time];
        refresh();
        if (selection[1] - selection[0] >= MIN_CUT) say?.(`Selected ${formatPrecise(selection[0])} – ${formatPrecise(selection[1])}. Press Cut selection (Delete) to remove it.`);
      },
      cut: () => {
        if (!selection || selection[1] - selection[0] < MIN_CUT) return;
        const [a, b] = selection;
        const before = history.length;
        selection = null;
        change(() => { edit.cuts.push([a, b]); });
        if (history.length > before) say?.(`Cut ${formatPrecise(a)} – ${formatPrecise(b)}. Restore it below, or press Ctrl+Z, if you change your mind.`, "ok");
        if (video.currentTime >= a && video.currentTime < b) video.currentTime = Math.min(b, edit.end);
      },
      undo: () => {
        const before = history.pop();
        if (!before) return;
        Object.assign(edit, JSON.parse(before));
        selection = null;
        refresh();
      },
      reset: () => change(() => {
        edit.start = 0;
        edit.end = edit.duration;
        edit.cuts = [];
        selection = null;
      }),
    };
    root.addEventListener("click", event => {
      const action = event.target.closest("[data-clip-action]")?.dataset.clipAction;
      if (action) actions[action]?.();
      const restore = event.target.closest("[data-clip-restore]");
      if (restore) change(() => { edit.cuts.splice(Number(restore.dataset.clipRestore), 1); });
    });

    return {
      // Load a video into the editor; resolves with its length in seconds (0 if it can't be read).
      async load(source, durationHint, marked = []) {
        this.unload();
        src = source;
        chapters = marked;
        history = [];
        selection = null;
        const token = ++filmToken;
        const deadline = Date.now() + 8000;
        while (video.readyState < 1 && !video.error && Date.now() < deadline) await wait(50);
        if (token !== filmToken) return 0;
        const found = video.readyState >= 1 ? await findDuration(video) : 0;
        if (token !== filmToken) return 0;
        const duration = found > 0 ? found : durationHint;
        if (!duration) return 0;
        edit = { duration, start: 0, end: duration, cuts: [] };
        refresh();
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(follow);
        filmstrip(token).catch(() => {});
        return duration;
      },
      unload() {
        filmToken += 1;
        cancelAnimationFrame(frame);
        edit = { duration: 0, start: 0, end: 0, cuts: [] };
        selection = null;
        history = [];
        strip.replaceChildren();
        marks.replaceChildren();
        cutList.replaceChildren();
        summary.textContent = "";
        selectionBox.hidden = true;
      },
      hasEdits,
      parts,
      // Start from an edit saved earlier: the parts it keeps, as [start, end] seconds.
      setParts(kept) {
        if (!edit.duration || !kept?.length) return;
        edit.start = clamp(kept[0][0], 0, edit.duration);
        edit.end = clamp(kept[kept.length - 1][1], edit.start, edit.duration);
        edit.cuts = kept.slice(1).map((part, index) => [kept[index][1], part[0]]);
        normalize();
        history = [];
        refresh();
      },
      // Editing shortcuts in review. Returns true when the key was used.
      keydown(event) {
        const key = event.key.toLowerCase();
        if ((event.ctrlKey || event.metaKey) && !event.altKey && key === "z") {
          actions.undo();
          return true;
        }
        if (event.ctrlKey || event.metaKey || event.altKey) return false;
        if (key === "i") actions["mark-in"]();
        else if (key === "o") actions["mark-out"]();
        else if ((key === "delete" || key === "backspace") && selection) actions.cut();
        else if ((key === "arrowleft" || key === "arrowright") && event.target === track) {
          video.currentTime = clamp(video.currentTime + (key === "arrowleft" ? -1 : 1) * (event.shiftKey ? 5 : 1), 0, edit.duration);
        } else if ((key === "home" || key === "end") && event.target === track) {
          video.currentTime = key === "home" ? edit.start : edit.end;
        } else return false;
        return true;
      },
    };
  }

  return { create, render, keptParts, remapChapters, remapCaptions, formatPrecise };
})();

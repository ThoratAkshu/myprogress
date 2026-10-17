// Editing a class recording before it's published: the studio's trim-and-cut timeline over the whole recording,
// with cuts held to the recording's keyframes (that's where the server can cut without re-encoding), chapters
// added at the playhead, and a thumbnail taken from the frame on screen.
(() => {
  const form = document.querySelector("[data-recording-editor]");
  if (!form) return;
  const data = JSON.parse(document.getElementById("recording-editor-data").textContent);
  const video = form.querySelector("[data-rec-video]");
  const status = form.querySelector("[data-rec-say]");
  const chapters = form.elements.chapters;
  const thumbInput = form.querySelector("[data-rec-thumb-input]");
  const thumb = form.querySelector("[data-rec-thumb]");
  const thumbEmpty = form.querySelector("[data-rec-thumb-empty]");
  let editor = null;
  let ready = false;
  let dirty = false;
  let sending = false;
  const say = (text, tone = "") => {
    status.textContent = text;
    status.dataset.tone = tone;
  };
  const stamp = seconds => {
    const whole = Math.floor(seconds);
    const hours = Math.floor(whole / 3600);
    const rest = `${String(Math.floor((whole % 3600) / 60)).padStart(hours ? 2 : 1, "0")}:${String(whole % 60).padStart(2, "0")}`;
    return hours ? `${hours}:${rest}` : rest;
  };
  // Chapters written as "m:ss Title", shown as ticks on the timeline.
  const chapterMarks = () => chapters.value.split("\n").map(line => line.trim().match(/^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s+(.+)$/)).filter(Boolean)
    .map(([, hours, minutes, secs, title]) => ({ time: Number(hours || 0) * 3600 + Number(minutes) * 60 + Number(secs), title }));

  const root = form.querySelector("[data-clip-editor]");
  if (root && window.StudioEditor && data.marks.length) {
    // The nearest place the recording can be cut: a keyframe, or its end.
    const snap = (time, duration) => data.marks.reduce((best, mark) => (Math.abs(mark - time) < Math.abs(best - time) ? mark : best), duration);
    editor = window.StudioEditor.create(root, { video, say, snap, onChange: () => { if (ready) dirty = true; } });
    editor.load(video.currentSrc || video.src, data.duration, chapterMarks()).then(duration => {
      if (!duration) return say("The recording couldn't be loaded for editing. Reload the page to try again.", "error");
      if (data.parts.length) editor.setParts(data.parts);
      ready = true;
    });
    document.addEventListener("keydown", event => {
      if (!ready || event.target.closest("input, textarea, select, [contenteditable]")) return;
      if (editor.keydown(event)) event.preventDefault();
    });
  }

  form.querySelector("[data-rec-chapter]").addEventListener("click", () => {
    const line = `${stamp(video.currentTime || 0)} `;
    chapters.value = chapters.value.trim() ? `${chapters.value.trim()}\n${line}` : line;
    chapters.focus();
    chapters.setSelectionRange(chapters.value.length, chapters.value.length);
    dirty = true;
  });

  function showThumbnail(blob) {
    thumb.src = URL.createObjectURL(blob);
    thumb.hidden = false;
    thumbEmpty.hidden = true;
    dirty = true;
  }
  form.querySelector("[data-rec-frame]").addEventListener("click", () => {
    if (!video.videoWidth) return say("Play the recording, or move to a moment on the timeline, first.", "warn");
    const scale = Math.min(1, 1280 / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(blob => {
      if (!blob) return say("That frame couldn't be captured. Try another moment.", "warn");
      const files = new DataTransfer();
      files.items.add(new File([blob], "frame.jpg", { type: "image/jpeg" }));
      thumbInput.files = files.files;
      showThumbnail(blob);
      say(`The frame at ${stamp(video.currentTime)} becomes the thumbnail when you save.`, "ok");
    }, "image/jpeg", 0.88);
  });
  thumbInput.addEventListener("change", () => { if (thumbInput.files[0]) showThumbnail(thumbInput.files[0]); });
  form.addEventListener("input", () => { dirty = true; });

  form.addEventListener("submit", event => {
    // Only a timeline that loaded sends its edit; otherwise the last saved edit is kept.
    if (editor && ready) form.elements.parts.value = JSON.stringify(editor.parts().map(([a, b]) => [Number(a.toFixed(3)), Number(b.toFixed(3))]));
    sending = true;
    const button = event.submitter;
    form.querySelectorAll("button[name=action]").forEach(other => { other.disabled = true; });
    if (button?.dataset.busy) {
      button.textContent = button.dataset.busy;
      // The disabled button isn't sent, so its choice goes along as a field.
      form.append(Object.assign(document.createElement("input"), { type: "hidden", name: "action", value: button.value }));
    }
  });
  window.addEventListener("beforeunload", event => {
    if (dirty && !sending) event.preventDefault();
  });
})();

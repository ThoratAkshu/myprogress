// Learning studio: list the chosen project's branches and fill the form with a drafted post. After a
// recording with live captions, the draft also uses what the author said (and works without a project).
// Institutes get a lecture planner instead (data-mode="lecture"): a topic, points to cover, and who it's for.
document.querySelectorAll("[data-studio]").forEach(studio => {
  const form = studio.closest("form");
  const lecture = studio.dataset.mode === "lecture";
  const planInput = name => studio.querySelector(`[data-lecture-${name}]`);
  const branchSelect = studio.querySelector('select[name="branch"]');
  const draftButton = studio.querySelector("[data-draft]");
  const status = studio.querySelector("[data-studio-status]");
  const draftFields = ["title", "summary", "body", "video_script"].map(name => form.elements[name]).filter(Boolean);
  const say = (text, tone = "") => { status.textContent = text; status.dataset.tone = tone; };
  const selectedProject = () => form.querySelector('input[name="project"]:checked')?.value || "";
  // The spoken words from the WebVTT captions, without the header, cue numbers, and timings.
  const transcript = () => (form.elements.captions?.value || "").split(/\r?\n/).filter(line => line.trim() && !line.startsWith("WEBVTT") && !line.includes("-->") && !/^\d+$/.test(line.trim())).join(" ").trim();
  const canDraft = () => Boolean((lecture ? planInput("topic").value.trim() : selectedProject()) || transcript());
  function setOptions(options, disabled) {
    branchSelect.replaceChildren(...options.map(([label, value]) => new Option(label, value)));
    branchSelect.disabled = disabled;
  }
  async function loadBranches(keep) {
    const project = selectedProject();
    draftButton.disabled = !canDraft();
    if (!project) return setOptions([["Pick a project first", ""]], true);
    setOptions([["Loading branches…", ""]], true);
    try {
      const response = await fetch(`${studio.dataset.branchesUrl}?project=${encodeURIComponent(project)}`, { headers: { Accept: "application/json" } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not load branches.");
      const none = data.branches.length ? "No branch (project details only)" : data.has_repository ? "No code pushed yet" : "No repository yet";
      setOptions([[none, ""], ...data.branches.map(branch => [branch.name === data.default ? `${branch.name} (default)` : branch.name, branch.name])], !data.branches.length);
      const wanted = keep || data.default;
      if (data.branches.some(branch => branch.name === wanted)) branchSelect.value = wanted;
      say("");
    } catch (error) {
      setOptions([["Branches unavailable", ""]], true);
      say(error.message || "Could not load branches.", "error");
    }
  }
  if (lecture) planInput("topic").addEventListener("input", () => { draftButton.disabled = !canDraft(); });
  form.querySelectorAll('input[name="project"]').forEach(radio => radio.addEventListener("change", () => loadBranches("")));
  form.elements.captions?.addEventListener("input", () => { draftButton.disabled = !canDraft(); });
  draftButton.addEventListener("click", async () => {
    if (draftFields.some(field => field.value.trim()) && !confirm(lecture ? "Replace the title, summary, notes, and lecture script with a new draft?" : "Replace the title, summary, article, and video script with a new draft?")) return;
    const body = new FormData();
    body.append("csrfmiddlewaretoken", form.elements.csrfmiddlewaretoken.value);
    if (lecture) {
      ["topic", "points", "audience"].forEach(name => body.append(name, planInput(name).value));
    } else {
      body.append("project", selectedProject());
      body.append("branch", selectedProject() ? branchSelect.value : "");
    }
    body.append("kind", form.querySelector('input[name="kind"]:checked')?.value || "article");
    body.append("transcript", transcript());
    body.append("chapters", form.elements.chapters?.value || "");
    draftButton.disabled = true;
    studio.classList.add("is-drafting");
    const from = [!lecture && selectedProject() && branchSelect.value && `${branchSelect.value}`, transcript() && "your recording"].filter(Boolean);
    if (lecture) say(`Writing lecture notes and a script${transcript() ? " from your plan and your recording" : ""}. This can take up to a minute.`, "busy");
    else say(from.length ? `Reading ${from.join(" and ")} and writing your draft. This can take up to a minute.` : "Writing your draft from the project details.", "busy");
    try {
      const response = await fetch(studio.dataset.draftUrl, { method: "POST", body, headers: { Accept: "application/json" } });
      const draft = await response.json().catch(() => ({}));
      if (!response.ok || typeof draft.body !== "string") {
        throw new Error(draft.error || (response.status === 429 ? "You've made a lot of drafts this hour. Try again later." : "Could not write a draft right now. Try again."));
      }
      draftFields.forEach(field => { field.value = draft[field.name] || ""; field.dispatchEvent(new Event("input", { bubbles: true })); });
      say(draft.notice || (lecture ? "Lecture drafted. Check the facts, fill in the parts in [brackets], then record or share it." : "Draft ready. Replace the parts in [brackets] with your own story, then publish."), draft.source === "ai" ? "ok" : "info");
      form.elements.title.focus();
    } catch (error) {
      say(error.message, "error");
    } finally {
      draftButton.disabled = !canDraft();
      studio.classList.remove("is-drafting");
    }
  });
  if (lecture) draftButton.disabled = !canDraft();
  else loadBranches(branchSelect.dataset.current);
});

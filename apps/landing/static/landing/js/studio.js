// Learning studio: list the chosen project's branches and fill the form with a drafted post.
document.querySelectorAll("[data-studio]").forEach(studio => {
  const form = studio.closest("form");
  const branchSelect = studio.querySelector('select[name="branch"]');
  const draftButton = studio.querySelector("[data-draft]");
  const status = studio.querySelector("[data-studio-status]");
  const draftFields = ["title", "summary", "body", "video_script"].map(name => form.elements[name]).filter(Boolean);
  const say = (text, tone = "") => { status.textContent = text; status.dataset.tone = tone; };
  const selectedProject = () => form.querySelector('input[name="project"]:checked')?.value || "";
  function setOptions(options, disabled) {
    branchSelect.replaceChildren(...options.map(([label, value]) => new Option(label, value)));
    branchSelect.disabled = disabled;
  }
  async function loadBranches(keep) {
    const project = selectedProject();
    draftButton.disabled = !project;
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
  form.querySelectorAll('input[name="project"]').forEach(radio => radio.addEventListener("change", () => loadBranches("")));
  draftButton.addEventListener("click", async () => {
    if (draftFields.some(field => field.value.trim()) && !confirm("Replace the title, summary, article, and video script with a new draft?")) return;
    const body = new FormData();
    body.append("csrfmiddlewaretoken", form.elements.csrfmiddlewaretoken.value);
    body.append("project", selectedProject());
    body.append("branch", branchSelect.value);
    body.append("kind", form.querySelector('input[name="kind"]:checked')?.value || "article");
    draftButton.disabled = true;
    studio.classList.add("is-drafting");
    say(branchSelect.value ? `Reading ${branchSelect.value} and writing your draft. This can take up to a minute.` : "Writing your draft from the project details.", "busy");
    try {
      const response = await fetch(studio.dataset.draftUrl, { method: "POST", body, headers: { Accept: "application/json" } });
      const draft = await response.json().catch(() => ({}));
      if (!response.ok || typeof draft.body !== "string") {
        throw new Error(draft.error || (response.status === 429 ? "You've made a lot of drafts this hour. Try again later." : "Could not write a draft right now. Try again."));
      }
      draftFields.forEach(field => { field.value = draft[field.name] || ""; field.dispatchEvent(new Event("input", { bubbles: true })); });
      say(draft.notice || "Draft ready. Replace the parts in [brackets] with your own story, then publish.", draft.source === "ai" ? "ok" : "info");
      form.elements.title.focus();
    } catch (error) {
      say(error.message, "error");
    } finally {
      draftButton.disabled = !selectedProject();
      studio.classList.remove("is-drafting");
    }
  });
  loadBranches(branchSelect.dataset.current);
});

// Edit profile: show the student or the working professional questions, and preview a new photo before saving.
(() => {
  const form = document.querySelector("[data-profile-form]");
  if (!form) return;

  const choice = form.querySelector("[data-occupation-switch]");
  choice?.addEventListener("change", () => {
    const chosen = choice.querySelector("input:checked")?.value || "";
    form.querySelectorAll("[data-for-occupation]").forEach(group => { group.hidden = group.dataset.forOccupation !== chosen; });
  });

  const photo = form.elements.avatar;
  const preview = form.querySelector("[data-photo-preview]");
  const remove = form.elements.remove_logo;
  const saved = preview.innerHTML;
  let objectUrl = "";
  photo.addEventListener("change", () => {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    const file = photo.files[0];
    objectUrl = file ? URL.createObjectURL(file) : "";
    if (file) {
      const image = document.createElement("img");
      image.src = objectUrl;
      image.alt = "";
      preview.replaceChildren(image);
      if (remove) remove.checked = false;
    } else {
      preview.innerHTML = saved;
    }
    preview.classList.remove("is-removed");
  });
  remove?.addEventListener("change", () => { preview.classList.toggle("is-removed", remove.checked && !photo.files.length); });
})();

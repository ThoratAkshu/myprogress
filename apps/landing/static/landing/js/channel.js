// Customize channel: a live preview of the channel header, and a logo maker for people without a logo file.
// The made logo is a PNG put into the normal logo upload, so the server checks and stores it like any upload.
(() => {
  const form = document.querySelector("[data-channel-form]");
  if (!form) return;
  const preview = form.querySelector("[data-channel-preview]");
  const find = selector => form.querySelector(selector);
  const nameOut = find("[data-preview-name]");
  const taglineOut = find("[data-preview-tagline]");
  const linksOut = find("[data-preview-links]");
  const bannerOut = find("[data-preview-banner]");
  const logoInput = form.elements.avatar;
  const bannerInput = form.elements.banner;
  const objectUrls = {};

  function showImage(target, file, key) {
    if (objectUrls[key]) URL.revokeObjectURL(objectUrls[key]);
    objectUrls[key] = file ? URL.createObjectURL(file) : "";
    target.forEach(element => {
      if (file) {
        const image = document.createElement("img");
        image.src = objectUrls[key];
        image.alt = "";
        element.replaceChildren(image);
      } else if (element.dataset.initial !== undefined) {
        element.innerHTML = element.dataset.initial;
      }
    });
  }
  const logoSpots = [find("[data-preview-logo]"), find("[data-logo-current]")];
  logoSpots.forEach(spot => { spot.dataset.initial = spot.innerHTML; });
  bannerOut.dataset.initial = bannerOut.innerHTML;

  // Basics and links, as you type.
  form.elements.channel_name.addEventListener("input", () => { nameOut.textContent = form.elements.channel_name.value.trim() || nameOut.dataset.default; });
  form.elements.headline.addEventListener("input", () => { taglineOut.textContent = form.elements.headline.value.trim(); });
  const linkInputs = [...form.querySelectorAll('input[name^="link_"]')];
  const linkIcons = Object.fromEntries(linkInputs.map(input => [input.name, input.closest(".channel-link-field").querySelector("svg")?.outerHTML || ""]));
  function renderLinks() {
    linksOut.replaceChildren(...linkInputs.filter(input => /^https:\/\/\S+\.\S+/.test(input.value.trim())).map(input => {
      const item = document.createElement("li");
      const label = input.closest(".channel-link-field").querySelector("label").textContent.trim();
      item.innerHTML = `<span>${linkIcons[input.name]}<span></span></span>`;
      item.querySelector("span span").textContent = label;
      return item;
    }));
  }
  linkInputs.forEach(input => input.addEventListener("input", renderLinks));

  // Brand colour: the banner gradient when there's no banner image.
  form.querySelectorAll('input[name="brand_color"]').forEach(radio => radio.addEventListener("change", () => {
    preview.style.setProperty("--brand-from", radio.dataset.from);
    preview.style.setProperty("--brand-to", radio.dataset.to);
  }));
  bannerInput.addEventListener("change", () => showImage([bannerOut], bannerInput.files[0], "banner"));
  form.elements.remove_banner?.addEventListener("change", event => { bannerOut.hidden = event.target.checked; });
  logoInput.addEventListener("change", () => {
    showImage(logoSpots, logoInput.files[0], "logo");
    if (logoInput.files[0] && form.elements.remove_logo) form.elements.remove_logo.checked = false;
  });

  // Logo maker: letters on a coloured circle, rounded tile or square.
  const maker = find("[data-logo-maker]");
  const canvas = find("[data-logo-canvas]");
  const lettersInput = find("[data-logo-text]");
  const note = find("[data-logo-note]");
  const context = canvas.getContext("2d");
  const size = canvas.width;
  const picked = name => form.querySelector(`input[name="${name}"]:checked`);
  const initialsOf = text => text.split(/\s+/).filter(word => /^[\p{L}\p{N}]/u.test(word)).slice(0, 2).map(word => word[0]).join("").toUpperCase();
  lettersInput.value = initialsOf(form.elements.channel_name.value || nameOut.dataset.default) || "MP";

  function shapePath(shape) {
    context.beginPath();
    if (shape === "circle") context.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
    else if (shape === "rounded") context.roundRect(0, 0, size, size, size * 0.22);
    else context.rect(0, 0, size, size);
  }
  function drawLogo() {
    const color = picked("logo-color");
    const fill = picked("logo-fill").value;
    const from = color?.dataset.from || "#0369a1";
    const to = color?.dataset.to || "#0ea5e9";
    context.clearRect(0, 0, size, size);
    shapePath(picked("logo-shape").value);
    if (fill === "light") {
      context.fillStyle = "#f8fafc";
    } else if (fill === "solid") {
      context.fillStyle = from;
    } else {
      const gradient = context.createLinearGradient(0, 0, size, size);
      gradient.addColorStop(0, from);
      gradient.addColorStop(1, to);
      context.fillStyle = gradient;
    }
    context.fill();
    if (fill === "light") {
      context.lineWidth = size * 0.035;
      context.strokeStyle = from;
      shapePath(picked("logo-shape").value);
      context.save();
      context.clip();
      context.stroke();
      context.restore();
    }
    const letters = (lettersInput.value.trim() || "?").toUpperCase().slice(0, 3);
    const fontSize = { 1: 290, 2: 220, 3: 160 }[letters.length] * (size / 512);
    context.font = `800 ${fontSize}px Manrope, "DM Sans", system-ui, sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillStyle = fill === "light" ? from : "#ffffff";
    context.fillText(letters, size / 2, size / 2 + fontSize * 0.04);
  }
  maker.addEventListener("input", drawLogo);
  maker.addEventListener("change", drawLogo);
  maker.addEventListener("toggle", () => { if (maker.open) document.fonts.ready.then(drawLogo); });
  find("[data-logo-use]").addEventListener("click", () => {
    drawLogo();
    canvas.toBlob(blob => {
      if (!blob) return;
      const transfer = new DataTransfer();
      transfer.items.add(new File([blob], "logo.png", { type: "image/png" }));
      logoInput.files = transfer.files;
      logoInput.dispatchEvent(new Event("change", { bubbles: true }));
      note.textContent = "Logo ready. Save the channel to keep it.";
      note.dataset.tone = "ok";
    }, "image/png");
  });
  drawLogo();
})();

// Who you are: show the student or the working professional questions.
(() => {
  const choice = document.querySelector("[data-occupation-switch]");
  if (!choice) return;
  choice.addEventListener("change", () => {
    const chosen = choice.querySelector("input:checked")?.value || "";
    document.querySelectorAll("[data-for-occupation]").forEach(group => { group.hidden = group.dataset.forOccupation !== chosen; });
  });
})();

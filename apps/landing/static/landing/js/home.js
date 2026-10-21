// Home: the Watch row scrolls with its arrows and plays a silent preview of the tile you point at. The side
// columns stay in view while the feed scrolls; one taller than the window sticks by its bottom instead of its top,
// so everything in it can still be reached.
(() => {
  document.querySelectorAll("[data-shelf]").forEach(shelf => {
    const row = shelf.querySelector("[data-shelf-row]");
    const [back, on] = shelf.querySelectorAll("[data-shelf-step]");
    const update = () => {
      back.disabled = row.scrollLeft <= 4;
      on.disabled = row.scrollLeft + row.clientWidth >= row.scrollWidth - 4;
    };
    [back, on].forEach(button => button.addEventListener("click", () => {
      row.scrollBy({ left: Number(button.dataset.shelfStep) * row.clientWidth * 0.8, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }));
    row.addEventListener("scroll", update, { passive: true });
    addEventListener("resize", update);
    update();
    if (window.MyProgressVideo?.still) return;
    row.querySelectorAll("[data-shelf-video]").forEach(video => {
      const tile = video.closest("a");
      const start = () => video.play().catch(() => {});
      const stop = () => video.pause();
      tile.addEventListener("mouseenter", start);
      tile.addEventListener("focus", start);
      tile.addEventListener("mouseleave", stop);
      tile.addEventListener("blur", stop);
    });
  });

  const columns = [...document.querySelectorAll(".feed-left, .feed-right")];
  const stick = () => columns.forEach(column => { column.style.top = `${Math.min(84, innerHeight - column.offsetHeight - 16)}px`; });
  if ("ResizeObserver" in window) columns.forEach(column => new ResizeObserver(stick).observe(column));
  addEventListener("resize", stick);
  stick();
})();

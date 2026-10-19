// The home page's Matrioshka brain: shells of points nested around a thinking core, drawn in 3D on a canvas. Each shell
// turns on its own tilted axis, signals travel between the core's neurons, and the view leans towards the pointer.
// The hero shows it behind the headline; "Inside the brain" flies the camera through the shells as you scroll, one
// dashboard feature per shell. In normal mode it's drawn in ink on a daylight sky; in developer mode it glows in the
// editor's colours. People who ask for less motion get a
// still picture, and the journey becomes a plain list (landing-dev.css).
(() => {
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const root = document.documentElement;
  const TAU = Math.PI * 2;
  const GOLDEN = Math.PI * (3 - Math.sqrt(5));
  const PALETTES = {
    normal: { shells: ["79,70,229", "14,165,233", "124,58,237", "219,39,119"], core: "79,70,229", link: "99,102,241", pulse: "14,165,233", glow: "167,139,250", ring: 1.7, wiring: 1.7 },  // daylight
    dev: { shells: ["56,189,248", "34,197,94", "125,211,252", "134,239,172"], core: "125,211,252", link: "56,189,248", pulse: "190,242,100", glow: "14,165,233", ring: 1, wiring: 1 },  // the night editor
  };
  // Shells from the outside in: radius, points, tilt of the axis it turns on, and speed (negative turns the other way).
  const SHELLS = [[1, 520, 0.42, 0.05], [0.8, 380, -0.6, -0.08], [0.62, 270, 0.9, 0.11], [0.45, 190, -0.3, -0.15]];

  function sphere(count, radius) {
    const points = [];
    for (let i = 0; i < count; i += 1) {
      const y = 1 - (i / (count - 1)) * 2;
      const ring = Math.sqrt(1 - y * y);
      points.push([Math.cos(GOLDEN * i) * ring * radius, y * radius, Math.sin(GOLDEN * i) * ring * radius]);
    }
    return points;
  }

  // The core: two hemispheres with folds, and each neuron wired to its nearest neighbours.
  function core(count) {
    const nodes = sphere(count, 1).map(([x, y, z]) => {
      const fold = 1 + 0.1 * Math.sin(7 * Math.atan2(y, z)) * Math.cos(5 * x);
      return [(x * 1.12 + Math.sign(x) * 0.12) * fold * 0.27, y * 0.9 * fold * 0.27, z * 1.04 * fold * 0.27];
    });
    const links = new Set();
    nodes.forEach((a, i) => {
      nodes.map((b, j) => [j, (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2]).filter(([j]) => j !== i)
        .sort((p, q) => p[1] - q[1]).slice(0, 3).forEach(([j]) => links.add(i < j ? `${i}-${j}` : `${j}-${i}`));
    });
    return { nodes, links: [...links].map(key => key.split("-").map(Number)) };
  }

  // The glow behind the core, drawn once for each colour and then scaled.
  const halos = {};
  function halo(rgb) {
    if (halos[rgb]) return halos[rgb];
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 256;
    const c = canvas.getContext("2d");
    const gradient = c.createRadialGradient(128, 128, 0, 128, 128, 128);
    gradient.addColorStop(0, `rgba(${rgb},0.28)`);
    gradient.addColorStop(0.45, `rgba(${rgb},0.08)`);
    gradient.addColorStop(1, `rgba(${rgb},0)`);
    c.fillStyle = gradient;
    c.fillRect(0, 0, 256, 256);
    halos[rgb] = canvas;
    return canvas;
  }

  const turn = ([x, y, z], yaw, pitch) => {
    const cy = Math.cos(yaw);
    const sy = Math.sin(yaw);
    const x1 = x * cy + z * sy;
    const z1 = -x * sy + z * cy;
    const cp = Math.cos(pitch);
    const sp = Math.sin(pitch);
    return [x1, y * cp - z1 * sp, y * sp + z1 * cp];
  };

  class Brain {
    constructor(canvas, { center = [0.5, 0.5], scale = 1, mobileCenter = [0.5, 0.4] } = {}) {
      this.canvas = canvas;
      this.context = canvas.getContext("2d");
      this.center = center;
      this.mobileCenter = mobileCenter;
      this.scale = scale;
      const small = window.matchMedia("(max-width: 700px)").matches;
      this.shells = SHELLS.map(([radius, count, tilt, speed]) => ({ radius, tilt, speed, points: sphere(Math.round(count * (small ? 0.55 : 1)), radius) }));
      this.core = core(small ? 110 : 170);
      this.pulses = [];
      this.orbiters = Array.from({ length: 7 }, (_, i) => ({ radius: 0.52 + (i % 4) * 0.13, tilt: (i * 0.9) % 1.6 - 0.8, speed: 0.25 + (i % 3) * 0.12, phase: i * 1.7 }));
      this.distance = 3.2;
      this.targetDistance = 3.2;
      this.focus = -1;
      this.lean = [0, 0];
      this.targetLean = [0, 0];
      this.running = false;
      this.fit();
      new ResizeObserver(() => this.fit()).observe(canvas.parentElement);
    }

    fit() {
      const ratio = Math.min(2, window.devicePixelRatio || 1);
      const host = this.canvas.parentElement;  // its layout size: a bounding box would shrink while the page turns in 3D
      this.width = host.clientWidth;
      this.height = host.clientHeight;
      this.canvas.width = Math.round(this.width * ratio);
      this.canvas.height = Math.round(this.height * ratio);
      this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
      if (!this.running) this.draw(performance.now());
    }

    aim(x, y) {  // the pointer, from -1 to 1 across the canvas
      this.targetLean = [x * 0.35, y * 0.22];
    }

    start() {
      if (this.running || calm) return;
      this.running = true;
      let last = 0;
      const loop = now => {  // 30 frames a second is plenty for something this slow, and halves the work
        if (!this.running) return;
        if (now - last >= 32) { last = now; this.draw(now); }
        requestAnimationFrame(loop);
      };
      requestAnimationFrame(loop);
    }

    stop() { this.running = false; }

    draw(now) {
      const { context: c, width, height } = this;
      if (!width || !height) return;
      const palette = root.classList.contains("dev-on") ? PALETTES.dev : PALETTES.normal;
      const t = now / 1000;
      this.distance += (this.targetDistance - this.distance) * 0.08;
      this.lean[0] += (this.targetLean[0] - this.lean[0]) * 0.05;
      this.lean[1] += (this.targetLean[1] - this.lean[1]) * 0.05;
      const [fx, fy] = width < 700 ? this.mobileCenter : this.center;
      const cx = width * fx;
      const cy = height * fy;
      const lens = Math.min(width, height) * 1.34 * this.scale;
      const yaw = t * 0.12 + this.lean[0];
      const pitch = 0.32 + Math.sin(t * 0.21) * 0.06 + this.lean[1];
      const D = this.distance;
      const project = point => {
        const [x, y, z] = turn(point, yaw, pitch);
        const depth = z + D;
        if (depth < 0.06) return null;
        return [cx + (x / depth) * lens, cy + (y / depth) * lens, depth, z];
      };
      c.clearRect(0, 0, width, height);

      // A soft glow behind the core, from a picture drawn once per colour.
      const middle = project([0, 0, 0]);
      if (middle) {
        const glow = Math.min(width, height) * 0.5 * Math.min(2.6, 3.2 / Math.max(D, 0.4)) * this.scale;
        c.drawImage(halo(palette.glow), middle[0] - glow, middle[1] - glow, glow * 2, glow * 2);
      }

      // The shells, each turning on its own axis, with a ring or two to show their shape. Points are batched by
      // brightness, so the canvas changes colour a few times a frame rather than once a point.
      this.shells.forEach((shell, index) => {
        const spin = t * shell.speed;
        const tilt = shell.tilt;
        const place = point => {  // turn about the shell's own axis, then tilt that axis
          const [a, b, d] = turn(point, spin, 0);
          return [a, b * Math.cos(tilt) - d * Math.sin(tilt), b * Math.sin(tilt) + d * Math.cos(tilt)];
        };
        const focused = this.focus === index;
        const dim = this.focus === -1 ? 1 : focused ? 1.7 : 0.4;
        const rgb = palette.shells[index];
        c.lineWidth = focused ? 1.3 : 0.8;
        c.strokeStyle = `rgba(${rgb},${(0.13 * dim * palette.ring).toFixed(3)})`;
        c.beginPath();
        for (const latitude of [0, 0.55]) {
          let drawing = false;
          for (let step = 0; step <= 72; step += 1) {
            const angle = (step / 72) * TAU;
            const ring = Math.cos(latitude) * shell.radius;
            const spot = project(place([Math.cos(angle) * ring, Math.sin(latitude) * shell.radius, Math.sin(angle) * ring]));
            if (!spot) { drawing = false; continue; }
            if (drawing) c.lineTo(spot[0], spot[1]); else c.moveTo(spot[0], spot[1]);
            drawing = true;
          }
        }
        c.stroke();
        const near = [];
        const far = [];
        for (const point of shell.points) {
          const spot = project(place(point));
          if (!spot) continue;
          const size = Math.min(3.4, Math.max(0.5, (lens / spot[2]) * 0.0042 * (focused ? 1.35 : 1)));
          (spot[3] > 0 ? far : near).push(spot[0] - size / 2, spot[1] - size / 2, size);
        }
        for (const [batch, back] of [[far, 0.35], [near, 1]]) {
          c.fillStyle = `rgba(${rgb},${Math.min(0.95, 0.62 * back * dim).toFixed(3)})`;
          for (let i = 0; i < batch.length; i += 3) c.fillRect(batch[i], batch[i + 1], batch[i + 2], batch[i + 2]);
        }
      });

      // The core: neurons, their wiring (one stroke for all of it), and signals running along it.
      const core = this.core.nodes.map(node => project(turn(node, t * 0.3, 0)));
      const coreDim = this.focus === -1 ? 1 : this.focus === 4 ? 1.6 : 0.6;
      c.lineWidth = 0.7;
      c.strokeStyle = `rgba(${palette.link},${Math.min(0.6, 0.22 * coreDim * palette.wiring).toFixed(3)})`;
      c.beginPath();
      for (const [a, b] of this.core.links) {
        const p = core[a];
        const q = core[b];
        if (!p || !q) continue;
        c.moveTo(p[0], p[1]);
        c.lineTo(q[0], q[1]);
      }
      c.stroke();
      c.fillStyle = `rgba(${palette.core},${Math.min(1, 0.75 * coreDim).toFixed(3)})`;
      for (const spot of core) {
        if (!spot) continue;
        const size = Math.min(4, Math.max(0.8, (lens / spot[2]) * 0.006));
        c.fillRect(spot[0] - size / 2, spot[1] - size / 2, size, size);
      }
      if (this.pulses.length < 14 && Math.random() < 0.18) this.pulses.push({ link: this.core.links[Math.floor(Math.random() * this.core.links.length)], born: now });
      this.pulses = this.pulses.filter(pulse => now - pulse.born < 650);
      for (const pulse of this.pulses) {
        const p = core[pulse.link[0]];
        const q = core[pulse.link[1]];
        if (!p || !q) continue;
        const k = (now - pulse.born) / 650;
        c.fillStyle = `rgba(${palette.pulse},${(0.9 * (1 - Math.abs(0.5 - k) * 1.2)).toFixed(3)})`;
        c.beginPath();
        c.arc(p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k, 1.8, 0, TAU);
        c.fill();
      }

      // Satellites between the shells, with short trails.
      for (const orbiter of this.orbiters) {
        for (let trail = 0; trail < 6; trail += 1) {
          const angle = (t - trail * 0.035) * orbiter.speed * TAU * 0.25 + orbiter.phase;
          const spot = project([Math.cos(angle) * orbiter.radius, Math.sin(angle) * orbiter.radius * Math.sin(orbiter.tilt), Math.sin(angle) * orbiter.radius * Math.cos(orbiter.tilt)]);
          if (!spot) continue;
          c.fillStyle = `rgba(${palette.pulse},${(0.55 * (1 - trail / 6)).toFixed(3)})`;
          c.beginPath();
          c.arc(spot[0], spot[1], Math.max(0.6, 2.2 - trail * 0.3), 0, TAU);
          c.fill();
        }
      }
    }
  }

  // Run a brain only while it's on screen and the tab is in front.
  function run(brain, host) {
    let shown = false;
    const update = () => (shown && !document.hidden ? brain.start() : brain.stop());
    new IntersectionObserver(entries => { shown = entries.some(entry => entry.isIntersecting); update(); }).observe(host);
    document.addEventListener("visibilitychange", update);
    if (!calm) {
      host.addEventListener("pointermove", event => {
        const box = host.getBoundingClientRect();
        brain.aim(((event.clientX - box.left) / box.width) * 2 - 1, ((event.clientY - box.top) / box.height) * 2 - 1);
      }, { passive: true });
      host.addEventListener("pointerleave", () => brain.aim(0, 0));
    }
    return brain;
  }

  const pair = (text, fallback) => (text ? text.split(",").map(Number) : fallback);
  const heroCanvas = document.querySelector("[data-brain=hero]");  // the home page's hero, or the sign-up story
  if (heroCanvas) {
    const { center, scale, mobileCenter } = heroCanvas.dataset;
    run(new Brain(heroCanvas, { center: pair(center, [0.44, 0.5]), scale: Number(scale) || 1.05, mobileCenter: pair(mobileCenter, [0.5, 0.3]) }), heroCanvas.parentElement);
  }

  // Inside the brain: scrolling flies the camera from the outer shell to the core, one feature per shell.
  const journey = document.querySelector("[data-journey]");
  if (journey) {
    const canvas = journey.querySelector("[data-brain=journey]");
    const brain = run(new Brain(canvas, { center: [0.66, 0.5], scale: 0.95, mobileCenter: [0.5, 0.3] }), journey.querySelector(".journey-sticky"));
    const stages = [...journey.querySelectorAll("[data-stage]")];
    const dots = [...journey.querySelectorAll("[data-journey-dot]")];
    const bar = journey.querySelector("[data-journey-bar]");
    const DISTANCES = [3.1, 2.25, 1.65, 1.2, 0.5];  // the camera's distance at each stage: through the shells, into the core
    let current = -1;
    const follow = () => {
      const box = journey.getBoundingClientRect();
      const travel = Math.max(1, box.height - window.innerHeight);
      const progress = Math.min(1, Math.max(0, -box.top / travel));
      const position = progress * (stages.length - 1);
      const index = Math.min(stages.length - 1, Math.round(position));
      const low = Math.floor(position);
      const high = Math.min(stages.length - 1, low + 1);
      brain.targetDistance = DISTANCES[low] + (DISTANCES[high] - DISTANCES[low]) * (position - low);
      brain.focus = index;
      if (bar) bar.style.transform = `scaleY(${progress})`;
      if (index === current) return;
      current = index;
      stages.forEach((stage, i) => stage.classList.toggle("is-active", i === index));
      dots.forEach((dot, i) => dot.setAttribute("aria-current", String(i === index)));
    };
    let queued = false;
    window.addEventListener("scroll", () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; follow(); });
    }, { passive: true });
    dots.forEach((dot, i) => dot.addEventListener("click", () => {
      const travel = journey.offsetHeight - window.innerHeight;
      window.scrollTo({ top: journey.offsetTop + (travel * i) / (stages.length - 1) + 2, behavior: calm ? "auto" : "smooth" });
    }));
    follow();
  }
})();

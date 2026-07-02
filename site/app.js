/* SUBLIME // AI SIGNAL — dashboard logic (no dependencies) */
(() => {
  "use strict";

  const REFRESH_MS = 30 * 60 * 1000;
  const state = { news: null, projects: null, course: null, lesson: [0, 0], section: "all", savedTab: "fav-news" };

  const $ = (sel) => document.querySelector(sel);

  /* ---------- tiny helpers ---------- */

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  function timeAgo(iso) {
    if (!iso) return "";
    const mins = Math.max(1, Math.round((Date.now() - new Date(iso)) / 60000));
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.round(mins / 60);
    if (hours < 48) return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
  }

  function md(text) {
    let src = esc(text ?? "");
    const blocks = [];
    src = src.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, _lang, code) => {
      blocks.push(code.trim());
      return ` ${blocks.length - 1} `;
    });
    src = src
      .replace(/^#{1,4}\s+(.+)$/gm, "<h4>$1</h4>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    const lines = src.split("\n");
    let out = "", list = null;
    const closeList = () => { if (list) { out += `</${list}>`; list = null; } };
    for (const line of lines) {
      const t = line.trim();
      if (!t) { closeList(); continue; }
      if (/^[-*]\s+/.test(t)) {
        if (list !== "ul") { closeList(); out += "<ul>"; list = "ul"; }
        out += `<li>${t.replace(/^[-*]\s+/, "")}</li>`;
      } else if (/^\d+[.)]\s+/.test(t)) {
        if (list !== "ol") { closeList(); out += "<ol>"; list = "ol"; }
        out += `<li>${t.replace(/^\d+[.)]\s+/, "")}</li>`;
      } else if (/^<h4>/.test(t) || /^ \d+ $/.test(t)) {
        closeList(); out += t;
      } else {
        closeList(); out += `<p>${t}</p>`;
      }
    }
    closeList();
    return out.replace(/ (\d+) /g, (_, i) => `<code class="code-block">${blocks[+i]}</code>`);
  }

  /* ---------- favorites & history ---------- */

  function getFavs(key) {
    try { return JSON.parse(localStorage.getItem(`signal-fav:${key}`)) || []; }
    catch { return []; }
  }
  function setFavs(key, arr) { localStorage.setItem(`signal-fav:${key}`, JSON.stringify(arr)); }
  function isFav(key, id) { return getFavs(key).includes(id); }
  function toggleFav(key, id) {
    const favs = getFavs(key);
    const idx = favs.indexOf(id);
    if (idx === -1) favs.push(id); else favs.splice(idx, 1);
    setFavs(key, favs);
    return idx === -1;
  }

  function addHistory(type, title, url) {
    const history = getHistory();
    history.unshift({ type, title, url, ts: new Date().toISOString() });
    if (history.length > 50) history.length = 50;
    localStorage.setItem("signal-history", JSON.stringify(history));
  }
  function getHistory() {
    try { return JSON.parse(localStorage.getItem("signal-history")) || []; }
    catch { return []; }
  }

  /* ---------- data loading ---------- */

  async function loadJSON(path) {
    const resp = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
    if (!resp.ok) throw new Error(`${path}: HTTP ${resp.status}`);
    return resp.json();
  }

  async function refresh() {
    try {
      const [news, projects] = await Promise.all([
        loadJSON("data/news.json"),
        loadJSON("data/projects.json"),
      ]);
      const changed = JSON.stringify(news) !== JSON.stringify(state.news) ||
                      JSON.stringify(projects) !== JSON.stringify(state.projects);
      state.news = news;
      state.projects = projects;
      if (changed) renderAll();
      $("#status-line").textContent =
        `LIVE · SIGNAL UPDATED ${timeAgo(news.updatedAt).toUpperCase()}`;
    } catch (err) {
      $("#status-line").textContent = "OFFLINE · SERVE OVER HTTP TO LOAD DATA";
      $("#news-list").innerHTML =
        `<div class="empty-state"><span class="mono">NO DATA LINK</span>
         Could not load data files (${esc(err.message)}).<br>
         If you opened index.html directly, run <code>python -m http.server</code> in the site folder,
         or visit the GitHub Pages URL.</div>`;
    }
  }

  /* ---------- render: news ---------- */

  function renderNews() {
    const { news } = state;
    $("#signal-sub").textContent =
      `Machine-curated ${new Date(news.updatedAt).toLocaleString(undefined, {
        weekday: "long", year: "numeric", month: "long", day: "numeric",
      })}. Each story ships with one idea for your day and one for Sublime.`;
    $("#footer-model").textContent = news.model
      ? `DIGEST MODEL: ${news.model.toUpperCase()}`
      : "DIGEST: FEED EXCERPTS (AI PENDING FIRST RUN)";

    const items = state.section === "all"
      ? news.items
      : news.items.filter((n) => (n.section || "ai-news") === state.section);

    $("#news-list").innerHTML = items.length ? items.map((n) => {
      const favored = isFav("news", n.title);
      const section = n.section || "ai-news";
      return `
      <li class="news-card">
        <div class="news-rank">${String(n.rank).padStart(2, "0")}</div>
        <div class="news-body">
          <h3 class="news-title"><a href="${esc(n.url)}" target="_blank" rel="noopener" data-track-title="${esc(n.title)}">${esc(n.title)}</a></h3>
          <div class="news-meta">
            <span class="chip ${esc(n.category)}">${esc(n.category)}</span>
            <span class="section-chip">${esc(section.replace(/-/g, " "))}</span>
            <span>${esc(n.source)}</span>
            <span>· ${timeAgo(n.publishedAt)}</span>
            ${n.engagement ? `<span>· ${esc(n.engagement)}</span>` : ""}
          </div>
          <p class="news-summary">${esc(n.summary)}</p>
          <div class="idea-row">
            <div class="idea-box"><strong>⚡ USE IT TODAY</strong>${esc(n.lifeIdea)}</div>
            <div class="idea-box sublime"><strong>◆ SUBLIME ANGLE</strong>${esc(n.sublimeAngle)}</div>
          </div>
        </div>
        <button class="fav-btn ${favored ? "active" : ""}" data-fav-key="news" data-fav-id="${esc(n.title)}" title="${favored ? "Remove from saved" : "Save this item"}">★</button>
      </li>`;
    }).join("") : '<li class="saved-empty">No items in this section yet.</li>';

    bindFavButtons();
    bindTrackLinks();
  }

  function bindFavButtons() {
    document.querySelectorAll(".fav-btn").forEach((btn) =>
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const key = btn.dataset.favKey;
        const id = btn.dataset.favId;
        const nowFav = toggleFav(key, id);
        btn.classList.toggle("active", nowFav);
        btn.title = nowFav ? "Remove from saved" : "Save this item";
      })
    );
  }

  function bindTrackLinks() {
    document.querySelectorAll("[data-track-title]").forEach((a) =>
      a.addEventListener("click", () => {
        addHistory("news", a.dataset.trackTitle, a.href);
      })
    );
  }

  /* ---------- section tabs ---------- */

  document.querySelectorAll(".section-tab").forEach((tab) =>
    tab.addEventListener("click", () => {
      document.querySelectorAll(".section-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      state.section = tab.dataset.section;
      renderNews();
    })
  );

  /* ---------- render: projects ---------- */

  const progressKey = (id) => `signal-progress:${id}`;

  function getProgress(id) {
    try { return JSON.parse(localStorage.getItem(progressKey(id))) || {}; }
    catch { return {}; }
  }

  function lessonCount(project) {
    return project.modules.reduce((n, m) => n + m.lessons.length, 0);
  }

  function doneCount(project) {
    const prog = getProgress(project.id);
    return Object.values(prog).filter(Boolean).length;
  }

  function renderProjects() {
    const { projects } = state;
    $("#lab-sub").textContent =
      `${projects.projects.length} hands-on courses generated from the signal on ` +
      `${new Date(projects.generatedAt).toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" })}. ` +
      `Progress is saved in this browser. Regenerate any time from the Actions tab.`;

    $("#project-grid").innerHTML = projects.projects.map((p) => {
      const total = lessonCount(p);
      const done = doneCount(p);
      const pct = total ? Math.round((100 * done) / total) : 0;
      const favored = isFav("projects", p.id);
      const section = p.section || "ai-news";
      return `
      <div class="project-card">
        <div class="project-head">
          <h3 class="project-title">${esc(p.title)}</h3>
          <button class="fav-btn ${favored ? "active" : ""}" data-fav-key="projects" data-fav-id="${esc(p.id)}" title="${favored ? "Remove from saved" : "Save this course"}">★</button>
        </div>
        <span class="section-chip">${esc(section.replace(/-/g, " "))}</span>
        <p class="project-tagline">${esc(p.tagline)}</p>
        <div class="project-facts">
          <span>${esc(p.difficulty)}</span>
          <span>${esc(p.timeEstimate)}</span>
          ${(p.skills || []).slice(0, 3).map((s) => `<span>${esc(s)}</span>`).join("")}
        </div>
        <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
        <p class="project-inspired">INSPIRED BY <em>${esc(p.inspiredBy)}</em></p>
        <button class="start-btn" data-project="${esc(p.id)}">
          ${done ? (done === total ? "✓ COMPLETED — REVIEW" : `RESUME · ${pct}%`) : "START COURSE →"}
        </button>
      </div>`;
    }).join("");

    document.querySelectorAll("#project-grid .start-btn").forEach((btn) =>
      btn.addEventListener("click", () => openCourse(btn.dataset.project))
    );
    bindFavButtons();
  }

  /* ---------- render: course ---------- */

  function openCourse(id) {
    const project = state.projects.projects.find((p) => p.id === id);
    if (!project) return;
    state.course = project;
    state.lesson = [0, 0];
    switchView("course");
    renderCourse();
  }

  function flatIndex(project, mi, li) {
    let idx = 0;
    for (let m = 0; m < mi; m++) idx += project.modules[m].lessons.length;
    return idx + li;
  }

  function renderCourse() {
    const p = state.course;
    const [mi, li] = state.lesson;
    const prog = getProgress(p.id);
    const total = lessonCount(p);
    const done = Object.values(prog).filter(Boolean).length;

    $("#course-nav").innerHTML = `
      <h2>${esc(p.title)}</h2>
      <p class="course-progress-label">${done}/${total} LESSONS · ${Math.round((100 * done) / total)}%</p>
      <div class="progress-track"><div class="progress-fill" style="width:${(100 * done) / total}%"></div></div>
      ${p.modules.map((m, mIdx) => `
        <div class="module-block">
          <div class="module-title">${esc(m.title)}</div>
          ${m.lessons.map((l, lIdx) => {
            const key = flatIndex(p, mIdx, lIdx);
            const cls = ["lesson-link", prog[key] ? "done" : "", mIdx === mi && lIdx === li ? "current" : ""].join(" ");
            return `<button class="${cls}" data-m="${mIdx}" data-l="${lIdx}">
              <span class="tick">${prog[key] ? "◆" : "◇"}</span>${esc(l.title)}
            </button>`;
          }).join("")}
        </div>`).join("")}`;

    const lesson = p.modules[mi].lessons[li];
    const key = flatIndex(p, mi, li);
    const isDone = !!prog[key];
    const isFirst = mi === 0 && li === 0;
    const isLast = mi === p.modules.length - 1 && li === p.modules[mi].lessons.length - 1;

    $("#course-content").innerHTML = `
      <p class="lesson-kicker">${esc(p.modules[mi].title).toUpperCase()} · LESSON ${li + 1}/${p.modules[mi].lessons.length}</p>
      <h3>${esc(lesson.title)}</h3>
      <p class="lesson-duration">◷ ${esc(lesson.duration || "10 min")}</p>
      <div class="lesson-body">
        ${md(lesson.content)}
        ${lesson.code ? `<code class="code-block">${esc(lesson.code)}</code>` : ""}
      </div>
      ${lesson.checkpoint ? `<div class="checkpoint-box"><strong>▣ CHECKPOINT</strong>${esc(lesson.checkpoint)}</div>` : ""}
      <div class="lesson-actions">
        <button class="nav-btn" id="prev-lesson" ${isFirst ? "disabled" : ""}>← PREV</button>
        <button class="complete-btn ${isDone ? "done" : ""}" id="toggle-done">
          ${isDone ? "✓ COMPLETED (UNDO)" : "MARK COMPLETE"}
        </button>
        <button class="nav-btn" id="next-lesson" ${isLast ? "disabled" : ""}>NEXT →</button>
      </div>`;

    document.querySelectorAll(".lesson-link").forEach((btn) =>
      btn.addEventListener("click", () => {
        state.lesson = [+btn.dataset.m, +btn.dataset.l];
        renderCourse();
      })
    );
    $("#prev-lesson")?.addEventListener("click", () => step(-1));
    $("#next-lesson")?.addEventListener("click", () => step(1));
    $("#toggle-done")?.addEventListener("click", () => {
      const updated = getProgress(p.id);
      updated[key] = !updated[key];
      localStorage.setItem(progressKey(p.id), JSON.stringify(updated));
      if (updated[key] && !isLast) step(1); else renderCourse();
      renderProjects();
    });
  }

  function step(dir) {
    const p = state.course;
    let [mi, li] = state.lesson;
    li += dir;
    if (li < 0) { mi--; li = p.modules[mi].lessons.length - 1; }
    else if (li >= p.modules[mi].lessons.length) { mi++; li = 0; }
    if (mi < 0 || mi >= p.modules.length) return;
    state.lesson = [mi, li];
    renderCourse();
    $("#course-content").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /* ---------- render: saved ---------- */

  function renderSaved() {
    const container = $("#saved-content");
    const tab = state.savedTab;

    if (tab === "fav-news") {
      const favIds = getFavs("news");
      if (!favIds.length || !state.news) {
        container.innerHTML = '<div class="saved-empty">No saved news yet. Click the ★ icon on any news item to save it.</div>';
        return;
      }
      const items = state.news.items.filter((n) => favIds.includes(n.title));
      if (!items.length) {
        container.innerHTML = '<div class="saved-empty">Saved items no longer in current data. They\'ll reappear next refresh if still in feed.</div>';
        return;
      }
      container.innerHTML = `<ol class="news-list">${items.map((n) => `
        <li class="news-card">
          <div class="news-rank">${String(n.rank).padStart(2, "0")}</div>
          <div class="news-body">
            <h3 class="news-title"><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a></h3>
            <div class="news-meta">
              <span class="chip ${esc(n.category)}">${esc(n.category)}</span>
              <span>${esc(n.source)}</span>
              <span>· ${timeAgo(n.publishedAt)}</span>
            </div>
            <p class="news-summary">${esc(n.summary)}</p>
          </div>
          <button class="fav-btn active" data-fav-key="news" data-fav-id="${esc(n.title)}" title="Remove from saved">★</button>
        </li>`).join("")}</ol>`;
      bindFavButtons();
    } else if (tab === "fav-projects") {
      const favIds = getFavs("projects");
      if (!favIds.length || !state.projects) {
        container.innerHTML = '<div class="saved-empty">No saved courses yet. Click the ★ icon on any course card to save it.</div>';
        return;
      }
      const items = state.projects.projects.filter((p) => favIds.includes(p.id));
      if (!items.length) {
        container.innerHTML = '<div class="saved-empty">Saved courses no longer in current data.</div>';
        return;
      }
      container.innerHTML = `<div class="project-grid">${items.map((p) => {
        const total = lessonCount(p);
        const done = doneCount(p);
        const pct = total ? Math.round((100 * done) / total) : 0;
        return `
        <div class="project-card">
          <div class="project-head">
            <h3 class="project-title">${esc(p.title)}</h3>
            <button class="fav-btn active" data-fav-key="projects" data-fav-id="${esc(p.id)}" title="Remove from saved">★</button>
          </div>
          <p class="project-tagline">${esc(p.tagline)}</p>
          <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
          <button class="start-btn" data-project="${esc(p.id)}">
            ${done ? (done === total ? "✓ COMPLETED — REVIEW" : `RESUME · ${pct}%`) : "START COURSE →"}
          </button>
        </div>`;
      }).join("")}</div>`;
      document.querySelectorAll("#saved-content .start-btn").forEach((btn) =>
        btn.addEventListener("click", () => openCourse(btn.dataset.project))
      );
      bindFavButtons();
    } else if (tab === "history") {
      const history = getHistory();
      if (!history.length) {
        container.innerHTML = '<div class="saved-empty">No history yet. Links you click will appear here.</div>';
        return;
      }
      container.innerHTML = `<div class="history-list">${history.map((h) => `
        <a class="history-item" href="${esc(h.url)}" target="_blank" rel="noopener">
          <span class="history-type">${esc(h.type)}</span>
          <span class="history-title">${esc(h.title)}</span>
          <span class="history-time">${timeAgo(h.ts)}</span>
        </a>`).join("")}</div>`;
    }
  }

  /* saved sub-tabs */
  document.querySelectorAll(".saved-tab").forEach((tab) =>
    tab.addEventListener("click", () => {
      document.querySelectorAll(".saved-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      state.savedTab = tab.dataset.saved;
      renderSaved();
    })
  );

  /* ---------- view switching ---------- */

  function switchView(name) {
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    $(`#view-${name}`).classList.add("active");
    document.querySelectorAll(".tab").forEach((t) => {
      const active = t.dataset.view === name || (name === "course" && t.dataset.view === "lab");
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", String(active));
    });
    if (name === "saved") renderSaved();
  }

  function renderAll() {
    if (state.news) renderNews();
    if (state.projects) renderProjects();
  }

  document.querySelectorAll(".tab").forEach((tab) =>
    tab.addEventListener("click", () => switchView(tab.dataset.view))
  );
  $("#course-back").addEventListener("click", () => switchView("lab"));

  function showToast(msg) {
    let toast = $("#toast-msg");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "toast-msg";
      toast.className = "toast-msg mono";
      document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.classList.add("visible");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toast.classList.remove("visible"), 3000);
  }

  async function manualRefresh(btn) {
    const oldNews = JSON.stringify(state.news);
    const oldProjects = JSON.stringify(state.projects);
    btn.classList.add("spinning");
    btn.disabled = true;
    await refresh();
    const changed = JSON.stringify(state.news) !== oldNews || JSON.stringify(state.projects) !== oldProjects;
    showToast(changed ? "NEW DATA LOADED ✓" : "DATA IS UP TO DATE — NO CHANGES YET");
    setTimeout(() => { btn.classList.remove("spinning"); btn.disabled = false; }, 600);
  }

  $("#refresh-news")?.addEventListener("click", function () { manualRefresh(this); });
  $("#refresh-projects")?.addEventListener("click", function () { manualRefresh(this); });

  refresh();
  setInterval(refresh, REFRESH_MS);
})();
